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
from .report import build_summary, summarize_simple, summarize_topical
from .results_store import (
    GcsResultsStore,
    LocalResultsStore,
    ResultsStore,
    rebuild_leaderboard,
)
from .runner import (
    generate_simple,
    generate_topical,
    run_adversarial,
    score_simple,
    score_topical_items,
)
from .scoring import SCORING_VERSION
from .topical import TopicalItem, build_topical_items, load_topics
from .yv_client import BibleClient

DEFAULT_TRACKS = "simple,topical,adversarial"

console = Console()


def _now() -> str:
    return datetime.now(UTC).isoformat()


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

    api_key = os.environ.get(args.api_key_env, "")
    if not api_key and not args.dummy:
        api_key = getpass.getpass(f"API key for {args.model} (input hidden): ").strip()
    if not api_key and not args.dummy:
        console.print("[red]No API key provided.[/red]")
        return 2

    model_cfg = LlmEndpointConfig(
        base_url=args.base_url, api_key=api_key, model=args.model, label=args.label or args.model
    )
    store = _store_from_args(args)
    client = BibleClient(bible_cfg)
    model = LlmClient(model_cfg, dummy=args.dummy)

    tracks = {t.strip() for t in args.tracks.split(",") if t.strip()}
    run_id = args.run_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{_slug(model_cfg.label)}"
    run_dir = f"runs/{run_id}"
    tracks_str = ",".join(sorted(tracks))
    console.print(f"[bold]Run:[/bold] {run_id}  ·  model [cyan]{model_cfg.label}[/cyan]  ·  "
                  f"seed [cyan]{args.seed}[/cyan]  ·  tracks [cyan]{tracks_str}[/cyan]")

    try:
        # 1. Fix the item set once: reuse on resume, else sample/build and persist
        #    the manifest immediately (so an interrupted run resumes the same set).
        manifest = store.read_json(f"{run_dir}/manifest.json")
        if manifest and manifest.get("tracks"):
            items = _items_from_json(manifest.get("items", []))
            topical_items = _topical_items_from_json(manifest.get("topical_items", []))
            adv_meta = manifest.get("adversarial")
            adv_goals = _goals_from_json(adv_meta["goals"]) if adv_meta else []
            console.print(f"Resuming: {len(items)} simple + {len(topical_items)} topical "
                          f"+ {len(adv_goals)} adversarial.")
        else:
            items = []
            topical_items = []
            if "simple" in tracks:
                with console.status("Sampling simple-track items from spec…"):
                    items = await _sample_items(client, args.spec, args.seed, args.scale)
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
            manifest = {
                "run_id": run_id,
                "dataset_spec": args.spec,
                "topics_file": args.topics,
                "goals_file": args.goals,
                "tracks": sorted(tracks),
                "seed": args.seed,
                "scale": args.scale,
                "scoring_version": SCORING_VERSION,
                "model": {
                    "label": model_cfg.label,
                    "model": model_cfg.model,
                    "base_url_host": urlparse(model_cfg.base_url).hostname or "",
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
            }
            store.write_json(f"{run_dir}/manifest.json", manifest)

        # 2. Generation passes (resumable via already-written responses).
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
        await _score_and_summarize(store, run_dir, items, topical_items, client, model)
    finally:
        await client.aclose()

    console.print(f"[green]Done.[/green] Results in [bold]{run_dir}[/bold]. "
                  f"Publish with: bible-bench publish {run_id}")
    return 0


async def _generate_track(store, run_dir, filename, desc, gen, *, id_key="item_id") -> None:
    """Run one generation pass with a resumable checkpoint + progress bar."""
    prior = store.read_jsonl(f"{run_dir}/{filename}")
    done = {r[id_key] for r in prior}
    if done:
        console.print(f"{len(done)} records already present in {filename}; continuing.")
    with _progress(desc) as (prog, task):
        def write_checkpoint(new_records: list[dict]) -> None:
            lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in prior + new_records)
            store.write_text(f"{run_dir}/{filename}", lines + "\n")

        def tick(ev: dict) -> None:
            if ev["phase"] == "generate":
                prog.update(task, total=ev["total"], completed=ev["completed"])

        await gen(done, write_checkpoint, tick)


async def _score_and_summarize(store, run_dir, items, topical_items, client, model) -> None:
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
    run_dir = f"runs/{args.run_id}"
    manifest = store.read_json(f"{run_dir}/manifest.json")
    if not manifest:
        console.print(f"[red]No manifest for run {args.run_id}[/red]")
        return 2
    client = BibleClient(load_bible_api_config())
    items = _items_from_json(manifest.get("items", []))
    topical_items = _topical_items_from_json(manifest.get("topical_items", []))
    no_usage = SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0, calls=0))
    try:
        await _score_and_summarize(store, run_dir, items, topical_items, client, no_usage)
    finally:
        await client.aclose()
    return 0


def cmd_publish(args, published: bool) -> int:
    store = _store_from_args(args)
    run_dir = f"runs/{args.run_id}"
    manifest = store.read_json(f"{run_dir}/manifest.json")
    if not manifest:
        console.print(f"[red]No manifest for run {args.run_id}[/red]")
        return 2
    manifest["published"] = published
    store.write_json(f"{run_dir}/manifest.json", manifest)
    board = rebuild_leaderboard(store)
    console.print(f"[green]{'Published' if published else 'Unpublished'}[/green] {args.run_id}. "
                  f"Leaderboard now has {len(board['entries'])} run(s).")
    return 0


async def cmd_build_dataset(args) -> int:
    client = BibleClient(load_bible_api_config())
    try:
        with console.status("Sampling…"):
            items = await _sample_items(client, args.spec, args.seed, args.scale)
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


def _add_store_args(p) -> None:
    p.add_argument("--local-dir", help="Write results to a local directory (dev mode)")
    p.add_argument("--gcs-bucket", help="Write results to a GCS bucket (prod mode)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bible-bench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run the benchmark against a model")
    r.add_argument("--base-url", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--label")
    r.add_argument("--api-key-env", default="TARGET_API_KEY",
                   help="Env var holding the API key (default TARGET_API_KEY)")
    r.add_argument("--spec", default="dataset/spec-v1.json")
    r.add_argument("--topics", default="dataset/topics-v1.json")
    r.add_argument("--topical-languages", default="",
                   help="Comma-separated language tags to limit the topical track to "
                        "(e.g. 'eng'); default all languages in the topics file")
    r.add_argument("--goals", default="dataset/adversarial-goals-v1.json")
    r.add_argument("--tracks", default=DEFAULT_TRACKS,
                   help="Comma-separated tracks to run (default: simple,topical,adversarial)")
    r.add_argument("--seed", default="2026-pilot")
    r.add_argument("--scale", type=float, default=1.0,
                   help="Scale factor on per-tier counts (use <1 for quick pilots)")
    r.add_argument("--run-id")
    r.add_argument("--dummy", action="store_true", help="Echo mode; no API key needed")
    _add_store_args(r)

    s = sub.add_parser("score", help="Re-score an existing run")
    s.add_argument("run_id")
    _add_store_args(s)

    for name in ("publish", "unpublish"):
        p = sub.add_parser(name)
        p.add_argument("run_id")
        _add_store_args(p)

    b = sub.add_parser("build-dataset", help="Draw a fresh item set from the spec")
    b.add_argument("--spec", default="dataset/spec-v1.json")
    b.add_argument("--seed", default="2026-pilot")
    b.add_argument("--scale", type=float, default=1.0)
    b.add_argument("--out")
    _add_store_args(b)

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
    return 1


if __name__ == "__main__":
    sys.exit(main())
