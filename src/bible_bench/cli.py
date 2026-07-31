"""bible-bench command-line runner.

    bible-bench run       run the benchmark against a model, write + score results
    bible-bench score     re-score an existing run under the current SCORING_VERSION
    bible-bench resummarize  rebuild summary.json from scored items (report-only changes)
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
from .prompts import BENCHMARK_SYSTEM_PROMPT, simple_quote_templates
from .report import (
    build_summary,
    summarize_phantom,
    summarize_simple,
    summarize_slices,
    summarize_topical,
)
from .results_store import (
    GcsResultsStore,
    LocalResultsStore,
    ResultsStore,
    rebuild_leaderboard,
)
from .runner import (
    EvaluationError,
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

# A fast pass is a separate generation with the same questions — see cmd_run.
FAST_SUFFIX = "-fast"
FAST_SCALE = 0.1
# Both are "current": re-summarizing either applies today's reporting rules to
# results today's code produced, which is the case --allow-older exists to block.
_CURRENT_VERSIONS = (BENCHMARK_VERSION, BENCHMARK_VERSION + FAST_SUFFIX)

console = Console()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _thin_per_language(items: list, scale: float) -> list:
    """Keep ``scale`` of the items WITHIN EACH language.

    A global prefix would not do: the item lists are built language by language,
    so items[:10%] covers the first language or two and nothing else. Track scores
    are macro-averages over languages, so that would produce a "benchmark" scored
    on English and Spanish while reporting it as eleven languages. Thinning inside
    each language keeps a fast run the same SHAPE as a full one, just smaller.
    """
    if scale >= 1.0:
        return items
    by_lang: dict[str, list] = {}
    for it in items:
        by_lang.setdefault(it.language_tag, []).append(it)
    out: list = []
    for group in by_lang.values():
        out.extend(group[: max(1, round(len(group) * scale))])
    return out


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
    # How long a model may take is a property of the MODEL, not the harness. The
    # default suits most; a large reasoning model answering an open question with
    # an 8k output budget can exceed it, and a timeout there aborts the whole run
    # (correctly — a partially generated pass can't be scored). Raise it per model
    # rather than making every run wait longer.
    model = LlmClient(model_cfg, dummy=args.dummy, timeout=args.timeout)

    only = {x.strip() for x in args.only_tracks.split(",") if x.strip()}
    if only - set(ALL_TRACKS):
        console.print(f"[red]Unknown track(s):[/red] {sorted(only - set(ALL_TRACKS))}. "
                      f"Choose from {list(ALL_TRACKS)}.")
        return 2
    tracks = only or set(ALL_TRACKS)
    # A fast run is its own generation on the board (v0.5-fast), so it never mixes
    # with full results — but it is SEEDED by the plain version, so its questions
    # are a strict subset of the full run's rather than a different draw. A fast
    # score and a full score therefore disagree only by coverage, not by sample.
    run_version = BENCHMARK_VERSION + FAST_SUFFIX if args.fast else BENCHMARK_VERSION
    sample_seed = BENCHMARK_VERSION
    if args.fast and args.scale == 1.0:
        args.scale = FAST_SCALE
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
        #
        # --only-tracks patches one dimension into an existing run instead. A
        # dimension's design can change without invalidating the others:
        # reworking Hallucination Resistance to name a translation made its items
        # obsolete and left Direct Quotation's 2,585 and Scripture in Answers'
        # 1,188 untouched. Re-running all 3,956 to replace 325 would spend tokens
        # reproducing answers already on disk.
        if only:
            if not store.read_json(f"{run_dir}/manifest.json"):
                console.print(f"[red]No existing run at {run_key} to patch.[/red] "
                              "Drop --only-tracks to run the whole benchmark.")
                return 2
            console.print(f"[yellow]Patching[/yellow] {sorted(only)} into the existing run; "
                          "other dimensions keep their stored records.")
        else:
            store.clear(run_dir)
        items = []
        topical_items = []
        if "simple" in tracks:
            with console.status("Sampling simple-track items from spec…"):
                items = await _sample_items(client, args.spec, sample_seed, args.scale)
            console.print(f"Sampled [bold]{len(items)}[/bold] simple items across "
                          f"{len({i.language_tag for i in items})} languages.")
        if "topical" in tracks:
            cfg = load_topics(args.topics)
            topical_langs = (
                [x.strip() for x in args.topical_languages.split(",") if x.strip()]
                if args.topical_languages else None
            )
            topical_items = _thin_per_language(
                build_topical_items(cfg, languages=topical_langs), args.scale)
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
            # Same translations as Direct Quotation, from the same spec, and the
            # same per-language wording — so the two dimensions differ only in
            # whether the reference exists.
            spec_langs = load_spec(args.spec).get("languages", {})
            phantom_versions = {
                lang: cfg_l.get("versions") or [cfg_l["primary"]]
                for lang, cfg_l in spec_langs.items()
            }
            phantom_items = await build_phantom_items(
                client, pcfg, languages=phantom_langs,
                versions_by_language=phantom_versions,
                template_by_language=simple_quote_templates(),
            )
            phantom_items = _thin_per_language(phantom_items, args.scale)
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
        if only:
            # Patching: carry forward everything about the run this invocation
            # isn't touching — the untouched dimensions' item lists, and the
            # original start time, which is what dates the run.
            prior = store.read_json(f"{run_dir}/manifest.json") or {}
            for key, track in (("items", "simple"), ("topical_items", "topical"),
                               ("phantom_items", "phantom")):
                if track not in only:
                    manifest[key] = prior.get(key, [])
            manifest["tracks"] = sorted(set(prior.get("tracks", [])) | only)
            manifest["started_at"] = prior.get("started_at") or manifest["started_at"]
            manifest["published"] = prior.get("published", False)
            manifest["patched_tracks"] = sorted(
                set(prior.get("patched_tracks", [])) | only
            )
        store.write_json(f"{run_dir}/manifest.json", manifest)

        # 2. Generation passes (fresh — the run dir was cleared above).
        if items:
            await _generate_track(
                store, run_dir, "responses.jsonl", "Querying model (simple)",
                lambda done, cp, tick: generate_simple(
                    items, client, model, already_done=done, checkpoint=cp, progress=tick,
                    concurrency=args.concurrency),
            )
        if topical_items:
            await _generate_track(
                store, run_dir, "responses_topical.jsonl", "Querying model (topical)",
                lambda done, cp, tick: generate_topical(
                    topical_items, model, already_done=done, checkpoint=cp, progress=tick,
                    concurrency=args.concurrency),
            )
        if phantom_items:
            await _generate_track(
                store, run_dir, "responses_phantom.jsonl", "Querying model (phantom)",
                lambda done, cp, tick: generate_phantom(
                    phantom_items, model, already_done=done, checkpoint=cp, progress=tick,
                    concurrency=args.concurrency),
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
    except EvaluationError as e:
        # A model call ran out of retries. The run is aborted UNSCORED and
        # UNFINISHED on purpose: a partial generation pass yields a wrong score,
        # not a missing one (failed calls read as "no attempt", deflating the
        # quote tracks and inflating hallucination resistance).
        console.print()
        console.print("[bold red]EVALUATION FAILED — run aborted, nothing scored.[/bold red]")
        console.print(f"[red]{e}[/red]")
        console.print(
            "[yellow]The model call exhausted its retries, so this run cannot produce a "
            "valid result. Fix the cause (credits/quota, rate limits, endpoint) and "
            f"re-run; the partial output in {run_dir} is kept for diagnosis only.[/yellow]"
        )
        return 1
    finally:
        await client.aclose()

    console.print(f"[green]Done.[/green] Results in [bold]{run_dir}[/bold]. "
                  f"Publish with: bible-bench publish --model {model_cfg.model}")
    return 0


async def _generate_track(store, run_dir, filename, desc, gen, *, id_key="item_id") -> None:
    """Run one generation pass, checkpointing progress to the run dir.

    Aborts the whole run if any item's model call fails after its retries — a
    partially-generated pass cannot produce a valid score (see runner's
    EvaluationError). Whatever was checkpointed stays on disk for diagnosis, but
    the run is left unfinished and unscored so it can never be published.
    """
    with _progress(desc) as (prog, task):
        def write_checkpoint(new_records: list[dict]) -> None:
            lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in new_records)
            store.write_text(f"{run_dir}/{filename}", lines + "\n")

        def tick(ev: dict) -> None:
            if ev["phase"] == "generate":
                prog.update(task, total=ev["total"], completed=ev["completed"])

        try:
            await gen(set(), write_checkpoint, tick)
        except EvaluationError as e:
            raise EvaluationError(f"{desc}: {e}") from e


async def _score_and_summarize(
    store, run_dir, items, topical_items, phantom_items, client, model
) -> None:
    track_summaries: dict[str, dict] = {}
    # Kept alongside the summaries so the per-translation slices can be built
    # from the same scored records, in the same pass.
    scored_by_track: dict[str, list[dict]] = {}

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
            scored_by_track["simple"] = scored

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
            scored_by_track["topical"] = scored_t

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
            scored_by_track["phantom"] = scored_p

    # Patching one dimension must not shrink the run's summary to that dimension.
    # The others' scored records are already on disk; read them back and
    # aggregate them unchanged, so the headline still covers everything.
    for track, fname, summarize in (
        ("simple", "items.jsonl", summarize_simple),
        ("topical", "items_topical.jsonl", summarize_topical),
        ("phantom", "items_phantom.jsonl", summarize_phantom),
    ):
        if track in track_summaries:
            continue
        rows = store.read_jsonl(f"{run_dir}/{fname}")
        if rows:
            track_summaries[track] = summarize(rows)
            scored_by_track[track] = rows
            console.print(f"  kept stored {track}: {len(rows)} items "
                          f"-> {track_summaries[track]['track_score']}")

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
        slices=summarize_slices(scored_by_track),
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


def cmd_resummarize(args) -> int:
    """Rebuild summary.json from the already-scored items. No model calls, no
    Bible text, no re-scoring.

    Aggregation (report.py) is a pure function of the scored item records, so a
    change that only adds a reported metric shouldn't cost a full re-score — that
    re-runs quote detection over every translation of every language and takes
    tens of minutes per run. This makes report-only changes a seconds-long step,
    which is the difference between adding a metric and not bothering.

    Per-item scores are untouched, so this can never change a score. If the
    SCORING_VERSION changed, use `score` instead.
    """
    store = _store_from_args(args)
    run_key = _run_key(args.run_version, args.model)
    run_dir = f"runs/{run_key}"
    manifest = store.read_json(f"{run_dir}/manifest.json")
    if not manifest:
        console.print(f"[red]No run found for {run_key}.[/red]")
        return 2
    # Applying today's aggregation to an older generation's items silently
    # rewrites history: reporting rules change between versions (v0.4 moved the
    # deuterocanon out of the headline, which shifts every v0.3 simple score).
    # Older results are meant to stay frozen at the version that produced them.
    if args.run_version not in _CURRENT_VERSIONS and not args.allow_older:
        console.print(
            f"[red]{run_key} was scored at {args.run_version}, but this codebase is "
            f"{BENCHMARK_VERSION}.[/red] Re-summarizing would apply {BENCHMARK_VERSION} "
            f"reporting rules to {args.run_version} results and change its published "
            f"numbers. Pass [bold]--allow-older[/bold] if that is genuinely what you want."
        )
        return 2

    tracks: dict[str, dict] = {}
    summarizers = {
        "simple": ("items.jsonl", "responses.jsonl", summarize_simple),
        "topical": ("items_topical.jsonl", "responses_topical.jsonl", summarize_topical),
        "phantom": ("items_phantom.jsonl", "responses_phantom.jsonl", summarize_phantom),
    }
    rows_by_track: dict[str, list[dict]] = {}
    for track, (items_file, resp_file, summarize) in summarizers.items():
        rows = store.read_jsonl(f"{run_dir}/{items_file}")
        if not rows:
            continue
        rows_by_track[track] = rows
        # Runs scored before finish_reason was recorded on items still have it on
        # the generation record, so join it in — it's what separates a provider
        # blocking its own output from the model declining.
        reasons = {
            r.get("item_id"): r.get("finish_reason")
            for r in store.read_jsonl(f"{run_dir}/{resp_file}")
        }
        for r in rows:
            r.setdefault("finish_reason", reasons.get(r.get("item_id")))
        tracks[track] = summarize(rows)
        console.print(f"  {track}: {len(rows)} items -> {tracks[track]['track_score']}")
    if not tracks:
        console.print(f"[red]{run_key} has no scored items to summarize.[/red]")
        return 2

    summary = build_summary(
        tracks, _usage_from_run(store, run_dir), slices=summarize_slices(rows_by_track)
    )
    store.write_json(f"{run_dir}/summary.json", summary)
    console.print(f"[green]Re-summarized[/green] {run_key}: "
                  f"headline [bold]{summary['headline_score']}[/bold]")
    if manifest.get("published"):
        rebuild_leaderboard(store)
        console.print("  Leaderboard rebuilt (this run is published).")
    return 0


def _usage_from_run(store, run_dir: str) -> dict:
    """Token/call totals recomputed from the generation records, so a
    re-summarize doesn't blank out usage that the original run reported."""
    totals = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    for f in ("responses.jsonl", "responses_topical.jsonl", "responses_phantom.jsonl"):
        for r in store.read_jsonl(f"{run_dir}/{f}"):
            totals["input_tokens"] += r.get("input_tokens") or 0
            totals["output_tokens"] += r.get("output_tokens") or 0
            totals["calls"] += 1
    return totals


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


async def _all_language_versions(client, languages: list[str]) -> dict[str, list[int]]:
    """Every translation the API offers for each benchmark language.

    Quotations are identified against a language's whole set of translations, so
    the set has to be enumerated (and cached) rather than hand-picked — that's
    what stops a faithful quote of an unanticipated translation from being scored
    as a misquote.
    """
    out: dict[str, list[int]] = {}
    for lang in languages:
        try:
            out[lang] = sorted({v.id for v in await client.versions(lang)})
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]  {lang}: version list failed ({e}); skipped[/yellow]")
    return out


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
    client = _bible_client(args)
    try:
        # Full coverage: every translation of every benchmark language, recorded
        # to the cache so offline scoring can enumerate them.
        langs = sorted(load_spec(args.spec).get("languages", {}))
        console.print(f"Resolving all translations for {len(langs)} languages…")
        by_lang = await _all_language_versions(client, langs)
        client.save_language_versions(by_lang)
        extra = sorted({v for ids in by_lang.values() for v in ids})
        console.print(
            "  " + ", ".join(f"{lg}:{len(ids)}" for lg, ids in sorted(by_lang.items()))
        )
        version_ids = sorted(set(version_ids) | set(extra))
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Could not enumerate all translations ({e}); "
                      f"prefetching the configured set only.[/yellow]")
    console.print(f"Prefetching [bold]{len(version_ids)}[/bold] versions "
                  f"({', '.join(sorted(tracks))}) into [cyan]{cache}[/cyan]")
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
    # Indent only what the headline is actually made of. Listing every track
    # beneath it reads as a breakdown, which would claim the extended dimensions
    # are inside a number they're deliberately outside of.
    by_track = summary.get("by_track", {})
    ranked = summary.get("headline_tracks") or list(by_track)
    for track in ranked:
        if track in by_track:
            t.add_row(f"  {track} track", f"{100 * by_track[track]:.1f}")
    if summary.get("extended_score") is not None:
        t.add_row("Extended score (not ranked)", f"{summary['extended_score']}")
        for track in summary.get("extended_tracks", []):
            if track in by_track:
                t.add_row(f"  {track} track", f"{100 * by_track[track]:.1f}")
    simple = summary.get("tracks", {}).get("simple")
    if simple:
        t.add_row("Verbatim rate", f"{100 * simple['verbatim_rate']:.1f}%")
        t.add_row("Fabrication rate", f"{100 * simple['fabrication_rate']:.1f}%")
        t.add_row("Refusal rate", f"{100 * simple['refusal_rate']:.1f}%")
        t.add_row("Wrong-version rate", f"{100 * simple['wrong_version_rate']:.1f}%")
        t.add_row("Wrong-language rate", f"{100 * simple.get('other_language_rate', 0):.1f}%")
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
        t.add_row("Declined (no quote)", f"{100 * phantom.get('refusal_rate', 0):.1f}%")
        t.add_row("Offered real substitute", f"{100 * phantom.get('substitute_rate', 0):.1f}%")
        t.add_row("Fabricated a verse", f"{100 * phantom.get('hallucination_rate', 0):.1f}%")
        t.add_row("Misattributed a real verse",
                  f"{100 * phantom.get('misattribution_rate', 0):.1f}%")
        t.add_row("Quoted real verse, uncited", f"{100 * phantom.get('unreferenced_rate', 0):.1f}%")
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
    r.add_argument("--only-tracks", default="",
                   help="Comma-separated dimensions to (re)generate, patched into an "
                        "EXISTING run — the others keep their stored responses and "
                        "scores, and the summary still covers the whole run. Use when "
                        "one dimension's design changes: 'phantom' re-asks 325 items "
                        "instead of re-running all 3,956. Default: the whole benchmark, "
                        "replacing the run.")
    r.add_argument("--timeout", type=float, default=120.0,
                   help="Seconds to allow one model call before retrying (default 120). "
                        "Raise it for large reasoning models — Kimi K3 and Tencent Hy3 "
                        "both exceeded 120s on open-question prompts, and a call that "
                        "exhausts its retries aborts the run.")
    r.add_argument("--fast", action="store_true",
                   help=f"Run a fast pass: about {int(FAST_SCALE * 100)}%% of the items, "
                        f"thinned within every language so the result keeps the same shape. "
                        f"Recorded as its own generation ('{BENCHMARK_VERSION}{FAST_SUFFIX}') "
                        f"so it never mixes with full results, but seeded by "
                        f"{BENCHMARK_VERSION} so its questions are a subset of the full "
                        f"run's. Publishable like any other run.")
    r.add_argument("--scale", type=float, default=1.0,
                   help="Scale factor on per-tier counts (use <1 for quick pilots). "
                        "Overrides the scale --fast would pick.")
    r.add_argument("--concurrency", type=int, default=12,
                   help="Max concurrent model requests per track (lower it — e.g. 3-4 — "
                        "to stay under a provider's rate limit; e.g. OpenRouter models)")
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

    rs = sub.add_parser("resummarize",
                        help="Rebuild summary.json from already-scored items "
                             "(report-only changes; no model calls, no re-scoring)")
    rs.add_argument("--run-version", default=BENCHMARK_VERSION,
                    help="Benchmark version of the run (default: current codebase)")
    rs.add_argument("--model", required=True, help="Model id used for the run")
    rs.add_argument("--allow-older", action="store_true",
                    help="Permit re-summarizing a run from an older benchmark version, "
                         "even though today's reporting rules will change its numbers")
    _add_store_args(rs)

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
    if args.cmd == "resummarize":
        return cmd_resummarize(args)
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
