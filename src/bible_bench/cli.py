"""bible-bench command-line runner.

    bible-bench run       run the benchmark against a model, write + score results
    bible-bench score     re-score an existing run under the current SCORING_VERSION
    bible-bench publish   mark a run published (appears on the leaderboard)
    bible-bench unpublish
    bible-bench build-dataset   draw a fresh item set from the spec (audit/preview)

API keys come from env vars (never bare CLI args). Ground-truth Bible API
credentials come from YV_API_* env vars.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from .adversarial.encounter import summarize_encounters
from .adversarial.goals import Goal, load_goals
from .config import (
    ConfigError,
    LlmEndpointConfig,
    load_bible_api_config,
    load_llm_endpoint,
)
from .dataset import BenchmarkItem, DatasetSampler, load_spec
from .llm import LlmClient
from .phantom import PhantomItem, build_phantom_items, load_phantom_config
from .prompts import BENCHMARK_SYSTEM_PROMPT
from .report import build_summary, summarize_phantom, summarize_simple, summarize_topical
from .results_store import (
    GcsResultsStore,
    LocalResultsStore,
    ResultsStore,
    rebuild_leaderboard,
)
from .runner import (
    generate_phantom,
    generate_simple,
    generate_topical,
    prefetch_versions,
    run_adversarial,
    score_phantom_items,
    score_simple,
    score_topical_items,
)
from .scoring import SCORING_VERSION
from .topical import TopicalItem, build_topical_items, load_topics
from .version import BENCHMARK_VERSION
from .yv_client import BibleClient

# The benchmark always runs all tracks — there is no track selection.
# Adversarial (misquote-resistance) is paused this round; the phantom
# (hallucination-resistance) track takes its place. The adversarial code path
# stays wired but dormant (never in ALL_TRACKS).
ALL_TRACKS = ("simple", "topical", "phantom")

console = Console()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cache_dir(args) -> str | None:
    """Local Bible-text cache dir: --cache-dir, else BENCH_CACHE_DIR env, else
    none (in-memory only)."""
    return getattr(args, "cache_dir", None) or os.environ.get("BENCH_CACHE_DIR") or None


def _bible_client(args, offline: bool = False) -> BibleClient:
    return BibleClient(load_bible_api_config(), cache_dir=_cache_dir(args), offline=offline)


def _require_cache(args) -> str:
    """Evaluations run offline against the local cache. Fail hard and fast if
    it isn't there — never silently fetch or prefetch mid-run."""
    cache = _cache_dir(args)
    if not cache:
        console.print("[red]No Bible-text cache configured.[/red] Set BENCH_CACHE_DIR "
                      "(or pass --cache-dir), then run: [bold]bible-bench prefetch[/bold]")
        raise SystemExit(2)
    p = Path(cache)
    if not p.is_dir() or not any(p.glob("v*/version.json")):
        console.print(f"[red]Bible-text cache at {cache} is missing or empty.[/red] "
                      "Run: [bold]bible-bench prefetch[/bold] first.")
        raise SystemExit(2)
    return cache


def _store_from_args(args) -> ResultsStore:
    if args.local_dir:
        return LocalResultsStore(args.local_dir)
    if args.gcs_bucket:
        return GcsResultsStore(args.gcs_bucket)
    return LocalResultsStore("results")


def _items_from_json(rows: list[dict]) -> list[BenchmarkItem]:
    return [BenchmarkItem(**r) for r in rows]


def _topical_items_from_json(rows: list[dict]) -> list[TopicalItem]:
    return [TopicalItem(**r) for r in rows]


def _phantom_items_from_json(rows: list[dict]) -> list[PhantomItem]:
    return [PhantomItem(**r) for r in rows]


def _goals_from_json(rows: list[dict]) -> list[Goal]:
    return [Goal(**r) for r in rows]


def _build_attacker(args) -> LlmClient:
    """Attacker (harness) model. Dummy in --dummy mode; else from HARNESS_* env."""
    if args.dummy:
        return LlmClient(
            LlmEndpointConfig(base_url="", api_key="", model="dummy-attacker",
                              label="dummy-attacker"),
            dummy=True,
        )
    return LlmClient(load_llm_endpoint("HARNESS"))


async def _sample_items(client: BibleClient, spec_path: str, seed: str, scale: float
                        ) -> list[BenchmarkItem]:
    spec = load_spec(spec_path)
    sampler = DatasetSampler(client, spec, Path(spec_path))
    return await sampler.sample(seed, counts_scale=scale)


async def cmd_run(args) -> int:
    try:
        bible_cfg = load_bible_api_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        return 2

    _require_cache(args)  # runs read only from the local cache; fail fast if absent

    api_key = os.environ.get(args.api_key_env, "")
    if not api_key and not args.dummy:
        api_key = getpass.getpass(f"API key for {args.model} (input hidden): ").strip()
    if not api_key and not args.dummy:
        console.print("[red]No API key provided.[/red]")
        return 2

    provider_routing = None
    if args.provider.strip():
        order = [p.strip() for p in args.provider.split(",") if p.strip()]
        provider_routing = {"order": order, "allow_fallbacks": False}
        if urlparse(args.base_url).hostname != "openrouter.ai":
            console.print("[yellow]--provider is set but --base-url isn't OpenRouter; "
                          "the pin will be ignored.[/yellow]")
    model_cfg = LlmEndpointConfig(
        base_url=args.base_url, api_key=api_key, model=args.model, label=args.label,
        provider_routing=provider_routing,
    )
    store = _store_from_args(args)
    client = BibleClient(bible_cfg, cache_dir=_cache_dir(args), offline=True)
    model = LlmClient(model_cfg, dummy=args.dummy)

    tracks = set(ALL_TRACKS)
    run_version = BENCHMARK_VERSION  # the benchmark version comes from the codebase
    run_key = _run_key(run_version, model_cfg.model)  # identity = version + model id
    run_dir = f"runs/{run_key}"
    tracks_str = ",".join(sorted(tracks))
    console.print(f"[bold]Run:[/bold] {run_key}  ·  model [cyan]{model_cfg.model}[/cyan] "
                  f"([cyan]{model_cfg.label}[/cyan])  ·  version [cyan]{run_version}[/cyan]  ·  "
                  f"tracks [cyan]{tracks_str}[/cyan]")

    try:
        # Overwrite: a given (model, run-version) always writes the same place.
        # Wipe any prior results there and build the item set fresh. The sample
        # is seeded by run-version, so every model at a version gets the same set.
        store.clear(run_dir)
        items = []
        topical_items = []
        if "simple" in tracks:
            with console.status("Sampling simple-track items from spec…"):
                items = await _sample_items(client, args.spec, run_version, args.scale)
            console.print(f"Sampled [bold]{len(items)}[/bold] simple items across "
                          f"{len({i.language_tag for i in items})} languages.")
        if "topical" in tracks:
            cfg = load_topics(args.topics)
            topical_langs = (
                [x.strip() for x in args.topical_languages.split(",") if x.strip()]
                if args.topical_languages else None
            )
            topical_items = build_topical_items(cfg, languages=topical_langs)
            if args.scale < 1.0:
                keep = max(1, int(len(topical_items) * args.scale))
                topical_items = topical_items[:keep]
            console.print(f"Built [bold]{len(topical_items)}[/bold] topical items.")
        adv_goals = []
        adv_cfg = None
        if "adversarial" in tracks:
            adv_cfg = load_goals(args.goals)
            adv_goals = adv_cfg.goals
            if args.scale < 1.0:
                keep = max(1, int(len(adv_goals) * args.scale))
                adv_goals = adv_goals[:keep]
            console.print(f"Loaded [bold]{len(adv_goals)}[/bold] adversarial goals.")
        phantom_items = []
        if "phantom" in tracks:
            pcfg = load_phantom_config(args.phantom)
            phantom_langs = (
                [x.strip() for x in args.phantom_languages.split(",") if x.strip()]
                if args.phantom_languages else None
            )
            phantom_items = await build_phantom_items(client, pcfg, languages=phantom_langs)
            if args.scale < 1.0:
                keep = max(1, int(len(phantom_items) * args.scale))
                phantom_items = phantom_items[:keep]
            console.print(f"Built [bold]{len(phantom_items)}[/bold] phantom items across "
                          f"{len({i.language_tag for i in phantom_items})} languages.")
        manifest = {
            "run_key": run_key,
            "run_version": run_version,
            "dataset_spec": args.spec,
            "topics_file": args.topics,
            "goals_file": args.goals,
            "phantom_file": args.phantom,
            "tracks": sorted(tracks),
            "scale": args.scale,
            "scoring_version": SCORING_VERSION,
            "system_prompt": BENCHMARK_SYSTEM_PROMPT,
            "model": {
                "label": model_cfg.label,
                "model": model_cfg.model,
                "base_url_host": urlparse(model_cfg.base_url).hostname or "",
                "provider_routing": model_cfg.provider_routing,
            },
            "adversarial": {
                "version_id": adv_cfg.version_id,
                "accepted_version_ids": adv_cfg.accepted_version_ids,
                "turn_depth": adv_cfg.turn_depth,
                "goals": [g.to_json() for g in adv_goals],
            } if adv_cfg else None,
            "started_at": _now(),
            "finished_at": None,
            "published": False,
            "items": [i.to_json() for i in items],
            "topical_items": [i.to_json() for i in topical_items],
            "phantom_items": [i.to_json() for i in phantom_items],
        }
        store.write_json(f"{run_dir}/manifest.json", manifest)

        # 2. Generation passes (fresh — the run dir was cleared above).
        if items:
            await _generate_track(
                store, run_dir, "responses.jsonl", "Querying model (simple)",
                lambda done, cp, tick: generate_simple(
                    items, client, model, already_done=done, checkpoint=cp, progress=tick),
            )
        if topical_items:
            await _generate_track(
                store, run_dir, "responses_topical.jsonl", "Querying model (topical)",
                lambda done, cp, tick: generate_topical(
                    topical_items, model, already_done=done, checkpoint=cp, progress=tick),
            )
        if phantom_items:
            await _generate_track(
                store, run_dir, "responses_phantom.jsonl", "Querying model (phantom)",
                lambda done, cp, tick: generate_phantom(
                    phantom_items, model, already_done=done, checkpoint=cp, progress=tick),
            )
        if adv_goals:
            adv_meta = manifest["adversarial"]
            attacker = _build_attacker(args)
            await _generate_track(
                store, run_dir, "adversarial.jsonl", "Adversarial encounters",
                lambda done, cp, tick: run_adversarial(
                    adv_goals, attacker, model, client,
                    adv_meta["version_id"], adv_meta["accepted_version_ids"],
                    turn_depth=adv_meta["turn_depth"],
                    already_done=done, checkpoint=cp, progress=tick),
                id_key="goal_id",
            )

        manifest["finished_at"] = _now()
        store.write_json(f"{run_dir}/manifest.json", manifest)

        # 3. Scoring pass.
        await _score_and_summarize(
            store, run_dir, items, topical_items, phantom_items, client, model
        )
    finally:
        await client.aclose()

    console.print(f"[green]Done.[/green] Results in [bold]{run_dir}[/bold]. "
                  f"Publish with: bible-bench publish --model {model_cfg.model}")
    return 0


async def _generate_track(store, run_dir, filename, desc, gen, *, id_key="item_id") -> None:
    """Run one generation pass, checkpointing progress to the run dir."""
    with _progress(desc) as (prog, task):
        def write_checkpoint(new_records: list[dict]) -> None:
            lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in new_records)
            store.write_text(f"{run_dir}/{filename}", lines + "\n")

        def tick(ev: dict) -> None:
            if ev["phase"] == "generate":
                prog.update(task, total=ev["total"], completed=ev["completed"])

        await gen(set(), write_checkpoint, tick)


async def _score_and_summarize(
    store, run_dir, items, topical_items, phantom_items, client, model
) -> None:
    track_summaries: dict[str, dict] = {}

    if items:
        responses = store.read_jsonl(f"{run_dir}/responses.jsonl")
        with _progress("Scoring (simple)") as (prog, task):
            prog.update(task, total=len(responses))

            def tick(ev: dict) -> None:
                if ev["phase"] == "score":
                    prog.update(task, completed=ev["completed"])

            scored = await score_simple({i.id: i for i in items}, responses, client, progress=tick)
        store.write_text(
            f"{run_dir}/items.jsonl",
            "\n".join(json.dumps(r, ensure_ascii=False) for r in scored) + "\n",
        )
        if scored:
            track_summaries["simple"] = summarize_simple(scored)

    if topical_items:
        responses = store.read_jsonl(f"{run_dir}/responses_topical.jsonl")
        with _progress("Scoring (topical)") as (prog, task):
            prog.update(task, total=len(responses))

            def tick(ev: dict) -> None:
                if ev["phase"] == "score":
                    prog.update(task, completed=ev["completed"])

            scored_t = await score_topical_items(
                {i.id: i for i in topical_items}, responses, client, progress=tick)
        store.write_text(
            f"{run_dir}/items_topical.jsonl",
            "\n".join(json.dumps(r, ensure_ascii=False) for r in scored_t) + "\n",
        )
        if scored_t:
            track_summaries["topical"] = summarize_topical(scored_t)

    if phantom_items:
        responses = store.read_jsonl(f"{run_dir}/responses_phantom.jsonl")
        with _progress("Scoring (phantom)") as (prog, task):
            prog.update(task, total=len(responses))

            def tick(ev: dict) -> None:
                if ev["phase"] == "score":
                    prog.update(task, completed=ev["completed"])

            scored_p = await score_phantom_items(
                {i.id: i for i in phantom_items}, responses, client, progress=tick)
        store.write_text(
            f"{run_dir}/items_phantom.jsonl",
            "\n".join(json.dumps(r, ensure_ascii=False) for r in scored_p) + "\n",
        )
        if scored_p:
            track_summaries["phantom"] = summarize_phantom(scored_p)

    adv_records = store.read_jsonl(f"{run_dir}/adversarial.jsonl")
    if adv_records:
        from .adversarial.encounter import EncounterResult, Turn

        results = [
            EncounterResult(
                goal_id=r["goal_id"], category=r["category"], target_usfm=r.get("target_usfm"),
                reached=r["reached"], reached_turn=r.get("reached_turn"),
                corrected_ever=r.get("corrected_ever", False),
                errored=r.get("errored", False), error=r.get("error"),
                turns=[Turn(**t) for t in r.get("turns", [])],
            )
            for r in adv_records
        ]
        track_summaries["adversarial"] = summarize_encounters(results)

    summary = build_summary(
        track_summaries,
        usage={
            "input_tokens": model.usage.input_tokens,
            "output_tokens": model.usage.output_tokens,
            "calls": model.usage.calls,
        },
    )
    store.write_json(f"{run_dir}/summary.json", summary)
    _print_summary(summary)


async def cmd_score(args) -> int:
    store = _store_from_args(args)
    run_key = _run_key(args.run_version, args.model)
    run_dir = f"runs/{run_key}"
    manifest = store.read_json(f"{run_dir}/manifest.json")
    if not manifest:
        console.print(f"[red]No run found for {run_key} (version={args.run_version}, "
                      f"model={args.model!r}).[/red]")
        return 2
    _require_cache(args)  # scoring reads only from the local cache
    client = _bible_client(args, offline=True)
    items = _items_from_json(manifest.get("items", []))
    topical_items = _topical_items_from_json(manifest.get("topical_items", []))
    phantom_items = _phantom_items_from_json(manifest.get("phantom_items", []))
    no_usage = SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0, calls=0))
    try:
        await _score_and_summarize(
            store, run_dir, items, topical_items, phantom_items, client, no_usage
        )
    finally:
        await client.aclose()
    return 0


def cmd_publish(args, published: bool) -> int:
    store = _store_from_args(args)
    run_key = _run_key(args.run_version, args.model)
    run_dir = f"runs/{run_key}"
    manifest = store.read_json(f"{run_dir}/manifest.json")
    if not manifest:
        console.print(f"[red]No run found for {run_key} (version={args.run_version}, "
                      f"model={args.model!r}).[/red]")
        return 2
    manifest["published"] = published
    store.write_json(f"{run_dir}/manifest.json", manifest)
    board = rebuild_leaderboard(store)
    console.print(f"[green]{'Published' if published else 'Unpublished'}[/green] {run_key}. "
                  f"Leaderboard now has {len(board['entries'])} run(s).")
    return 0


async def cmd_build_dataset(args) -> int:
    client = _bible_client(args)
    try:
        with console.status("Sampling…"):
            items = await _sample_items(client, args.spec, args.run_version, args.scale)
    finally:
        await client.aclose()
    if args.out:
        lines = "\n".join(json.dumps(i.to_json(), ensure_ascii=False) for i in items)
        Path(args.out).write_text(lines + "\n")
        console.print(f"Wrote {len(items)} items to {args.out}")
    by_lang: dict[str, int] = {}
    for i in items:
        by_lang[i.language_tag] = by_lang.get(i.language_tag, 0) + 1
    console.print(f"Sampled [bold]{len(items)}[/bold] items: " +
                  ", ".join(f"{k}={v}" for k, v in sorted(by_lang.items())))
    return 0


def _prefetch_version_ids(args, tracks: set[str]) -> list[int]:
    """Union of every version id the benchmark touches, for the chosen tracks."""
    ids: set[int] = set()
    if "simple" in tracks:
        spec = load_spec(args.spec)
        for lang in spec.get("languages", {}).values():
            ids.update(lang.get("versions", []))
        for pool in spec.get("distractor_pools", {}).values():
            ids.update(pool)
    if "topical" in tracks:
        cfg = load_topics(args.topics)
        for block in cfg.languages.values():
            ids.add(block["version_id"])
            ids.update(block.get("accepted_version_ids", []))
    if "adversarial" in tracks:
        adv = load_goals(args.goals)
        ids.add(adv.version_id)
        ids.update(adv.accepted_version_ids)
    if "phantom" in tracks:
        pcfg = load_phantom_config(args.phantom)
        for block in pcfg.languages.values():
            ids.add(block["version_id"])
            ids.update(block.get("accepted_version_ids", []))
    return sorted(ids)


async def cmd_prefetch(args) -> int:
    cache = _cache_dir(args)
    if not cache:
        console.print("[red]--cache-dir (or BENCH_CACHE_DIR) is required for prefetch.[/red]")
        return 2
    tracks = set(ALL_TRACKS)
    try:
        version_ids = _prefetch_version_ids(args, tracks)
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        return 2
    console.print(f"Prefetching [bold]{len(version_ids)}[/bold] versions "
                  f"({', '.join(sorted(tracks))}) into [cyan]{cache}[/cyan]")
    client = _bible_client(args)
    try:
        with _progress("Caching Bible text") as (prog, task):
            def tick(ev: dict) -> None:
                if ev["phase"] == "prefetch":
                    prog.update(task, total=ev["total"], completed=ev["completed"])
            stats = await prefetch_versions(client, version_ids, progress=tick)
    finally:
        await client.aclose()
    console.print(f"[green]Cached[/green] {stats['chapters']} chapters across "
                  f"{stats['versions']} versions in {cache}. Runs pointed at this "
                  f"cache dir will reuse it and avoid re-fetching.")
    return 0


def _progress(desc: str):
    prog = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        console=console,
    )
    task = prog.add_task(desc, total=1)

    class _Ctx:
        def __enter__(self):
            prog.start()
            return prog, task

        def __exit__(self, *a):
            prog.stop()

    return _Ctx()


def _print_summary(summary: dict) -> None:
    t = Table(title="Run summary")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Headline score", f"{summary['headline_score']}"
              + (" (partial)" if summary.get("headline_partial") else ""))
    for track, score in summary.get("by_track", {}).items():
        t.add_row(f"  {track} track", f"{100 * score:.1f}")
    simple = summary.get("tracks", {}).get("simple")
    if simple:
        t.add_row("Verbatim rate", f"{100 * simple['verbatim_rate']:.1f}%")
        t.add_row("Fabrication rate", f"{100 * simple['fabrication_rate']:.1f}%")
        t.add_row("Refusal rate", f"{100 * simple['refusal_rate']:.1f}%")
        t.add_row("Wrong-version rate", f"{100 * simple['wrong_version_rate']:.1f}%")
    topical = summary.get("tracks", {}).get("topical")
    if topical:
        emit = topical.get("emission_rate_by_level", {})
        t.add_row("Topical emission (by level)",
                  ", ".join(f"{k}={100 * v:.0f}%" for k, v in emit.items()) or "—")
        if topical.get("sensitive_topic_score") is not None:
            t.add_row("Sensitive-topic score", f"{100 * topical['sensitive_topic_score']:.1f}")
        t.add_row("Topical fabricated quotes", str(topical.get("fabricated_quote_count", 0)))
    phantom = summary.get("tracks", {}).get("phantom")
    if phantom:
        t.add_row("Hallucination resistance", f"{100 * phantom['track_score']:.1f}")
        t.add_row("Declined phantom refs", f"{100 * phantom.get('refusal_rate', 0):.1f}%")
        t.add_row("Hallucinated a verse", f"{100 * phantom.get('hallucination_rate', 0):.1f}%")
    adv = summary.get("tracks", {}).get("adversarial")
    if adv:
        t.add_row("Adversarial resistance@1", f"{100 * adv.get('resistance_at_1', 0):.1f}%")
        t.add_row("Adversarial resistance@3", f"{100 * adv.get('resistance_at_3', 0):.1f}%")
        t.add_row("Misquotes induced", f"{adv.get('misquotes_confirmed', 0)}/{adv.get('n', 0)}")
        t.add_row("Correction rate", f"{100 * adv.get('correction_rate', 0):.1f}%")
    console.print(t)
    console.print(f"[dim]{summary['scoring_scope_note']}[/dim]")


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")[:40]


def _run_key(run_version: str, model: str) -> str:
    """Deterministic run identifier from (run-version, model id). The model id
    is the official identifier sent in the API call — NOT the display label.
    Re-running the same (version, model) resolves to the same location and
    overwrites it; there is no separate run-id concept."""
    v = "".join(c if (c.isalnum() or c in ".-") else "-" for c in run_version).strip("-")
    return f"{v}--{_slug(model)}"


def _add_cache_arg(p) -> None:
    p.add_argument("--cache-dir",
                   help="Local dir for cached Bible text (reused across runs; "
                        "defaults to BENCH_CACHE_DIR env). Keep it gitignored.")


def _add_store_args(p) -> None:
    p.add_argument("--local-dir", help="Write results to a local directory (dev mode)")
    p.add_argument("--gcs-bucket", help="Write results to a GCS bucket (prod mode)")


def main(argv: list[str] | None = None) -> int:
    # Load a local .env from the directory the command is run in (BENCH_CACHE_DIR,
    # Bible API headers, harness config, etc.). Explicit + cwd-based so it works
    # regardless of how the package is installed.
    load_dotenv(find_dotenv(usecwd=True))

    parser = argparse.ArgumentParser(prog="bible-bench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run the benchmark against a model")
    r.add_argument("--base-url", required=True)
    r.add_argument("--model", required=True,
                   help="Official model id sent in the API call; also identifies the run")
    r.add_argument("--label", required=True,
                   help="Human-readable display name, stored in the result for the "
                        "website (not used in the API call or run identity)")
    # No --run-version: the benchmark version comes from the codebase
    # (bible_bench.version.BENCHMARK_VERSION) and identifies + seeds the run.
    r.add_argument("--api-key-env", default="TARGET_API_KEY",
                   help="Env var holding the API key (default TARGET_API_KEY)")
    r.add_argument("--provider", default="",
                   help="OpenRouter only: comma-separated upstream provider slug(s) to "
                        "pin routing to (e.g. 'fireworks' or 'together,deepinfra'), with "
                        "fallbacks disabled — fixes the upstream and its quantization so "
                        "scoring is reproducible. Ignored for native endpoints; find a "
                        "model's provider slugs on its OpenRouter page.")
    r.add_argument("--spec", default="dataset/spec-v1.json")
    r.add_argument("--topics", default="dataset/topics-v1.json")
    r.add_argument("--topical-languages", default="",
                   help="Comma-separated language tags to limit the topical track to "
                        "(e.g. 'eng'); default all languages in the topics file")
    r.add_argument("--goals", default="dataset/adversarial-goals-v1.json")
    r.add_argument("--phantom", default="dataset/phantom-v1.json")
    r.add_argument("--phantom-languages", default="",
                   help="Comma-separated language tags to limit the hallucination track "
                        "to (e.g. 'eng'); default all languages in the phantom file")
    r.add_argument("--scale", type=float, default=1.0,
                   help="Scale factor on per-tier counts (use <1 for quick pilots)")
    r.add_argument("--dummy", action="store_true", help="Echo mode; no API key needed")
    _add_cache_arg(r)
    _add_store_args(r)

    # For managing existing runs, --run-version is optional and defaults to the
    # current codebase version; pass it explicitly to touch an older run (v0.1).
    s = sub.add_parser("score", help="Re-score an existing run")
    s.add_argument("--run-version", default=BENCHMARK_VERSION,
                   help="Benchmark version of the run to score (default: current codebase)")
    s.add_argument("--model", required=True, help="Model id used for the run")
    _add_cache_arg(s)
    _add_store_args(s)

    for name in ("publish", "unpublish"):
        p = sub.add_parser(name)
        p.add_argument("--run-version", default=BENCHMARK_VERSION,
                       help="Benchmark version of the run (default: current codebase)")
        p.add_argument("--model", required=True, help="Model id used for the run")
        _add_store_args(p)

    b = sub.add_parser("build-dataset", help="Draw a fresh item set from the spec")
    b.add_argument("--spec", default="dataset/spec-v1.json")
    b.add_argument("--run-version", default=BENCHMARK_VERSION,
                   help="Seeds the verse sample (default: current codebase version)")
    b.add_argument("--scale", type=float, default=1.0)
    b.add_argument("--out")
    _add_cache_arg(b)
    _add_store_args(b)

    pf = sub.add_parser("prefetch",
                        help="Download Bible text for all benchmark versions into a "
                             "local cache (run once; reused across runs)")
    pf.add_argument("--spec", default="dataset/spec-v1.json")
    pf.add_argument("--topics", default="dataset/topics-v1.json")
    pf.add_argument("--goals", default="dataset/adversarial-goals-v1.json")
    pf.add_argument("--phantom", default="dataset/phantom-v1.json")
    _add_cache_arg(pf)

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(cmd_run(args))
    if args.cmd == "score":
        return asyncio.run(cmd_score(args))
    if args.cmd == "publish":
        return cmd_publish(args, True)
    if args.cmd == "unpublish":
        return cmd_publish(args, False)
    if args.cmd == "build-dataset":
        return asyncio.run(cmd_build_dataset(args))
    if args.cmd == "prefetch":
        return asyncio.run(cmd_prefetch(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
