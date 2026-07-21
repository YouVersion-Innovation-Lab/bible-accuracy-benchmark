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

from .config import ConfigError, LlmEndpointConfig, load_bible_api_config
from .dataset import BenchmarkItem, DatasetSampler, load_spec
from .llm import LlmClient
from .report import build_summary, summarize_simple
from .results_store import (
    GcsResultsStore,
    LocalResultsStore,
    ResultsStore,
    rebuild_leaderboard,
)
from .runner import generate_simple, score_simple
from .scoring import SCORING_VERSION
from .yv_client import BibleClient

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

    run_id = args.run_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{_slug(model_cfg.label)}"
    run_dir = f"runs/{run_id}"
    console.print(f"[bold]Run:[/bold] {run_id}  ·  model [cyan]{model_cfg.label}[/cyan]  ·  "
                  f"seed [cyan]{args.seed}[/cyan]")

    try:
        # 1. Fix the item set once: reuse it on resume, else sample and persist
        #    the manifest immediately (so an interrupted run resumes the same set).
        manifest = store.read_json(f"{run_dir}/manifest.json")
        if manifest and manifest.get("items"):
            items = _items_from_json(manifest["items"])
            console.print(f"Resuming with {len(items)} items from existing manifest.")
        else:
            with console.status("Sampling benchmark items from spec…"):
                items = await _sample_items(client, args.spec, args.seed, args.scale)
            console.print(f"Sampled [bold]{len(items)}[/bold] items across "
                          f"{len({i.language_tag for i in items})} languages.")
            manifest = {
                "run_id": run_id,
                "dataset_spec": args.spec,
                "seed": args.seed,
                "scale": args.scale,
                "scoring_version": SCORING_VERSION,
                "model": {
                    "label": model_cfg.label,
                    "model": model_cfg.model,
                    "base_url_host": urlparse(model_cfg.base_url).hostname or "",
                },
                "started_at": _now(),
                "finished_at": None,
                "published": False,
                "items": [i.to_json() for i in items],
            }
            store.write_json(f"{run_dir}/manifest.json", manifest)

        # 2. Generation pass (resumable via already-written responses).
        prior = store.read_jsonl(f"{run_dir}/responses.jsonl")
        done = {r["item_id"] for r in prior}
        if done:
            console.print(f"{len(done)} responses already present; continuing.")

        with _progress("Querying model") as (prog, task):
            prog.update(task, total=len([i for i in items if i.id not in done]))

            def write_checkpoint(new_records: list[dict]) -> None:
                lines = "\n".join(
                    json.dumps(r, ensure_ascii=False) for r in prior + new_records
                )
                store.write_text(f"{run_dir}/responses.jsonl", lines + "\n")

            def tick(ev: dict) -> None:
                if ev["phase"] == "generate":
                    prog.update(task, completed=ev["completed"])

            await generate_simple(items, client, model, already_done=done,
                                  checkpoint=write_checkpoint, progress=tick)

        manifest["finished_at"] = _now()
        store.write_json(f"{run_dir}/manifest.json", manifest)

        # 3. Scoring pass.
        await _score_and_summarize(store, run_dir, items, client, model)
    finally:
        await client.aclose()

    console.print(f"[green]Done.[/green] Results in [bold]{run_dir}[/bold]. "
                  f"Publish with: bible-bench publish {run_id}")
    return 0


async def _score_and_summarize(store, run_dir, items, client, model) -> None:
    items_by_id = {i.id: i for i in items}
    responses = store.read_jsonl(f"{run_dir}/responses.jsonl")
    with _progress("Scoring") as (prog, task):
        prog.update(task, total=len(responses))

        def tick(ev: dict) -> None:
            if ev["phase"] == "score":
                prog.update(task, completed=ev["completed"])

        scored = await score_simple(items_by_id, responses, client, progress=tick)
    store.write_text(
        f"{run_dir}/items.jsonl",
        "\n".join(json.dumps(r, ensure_ascii=False) for r in scored) + "\n",
    )
    simple = [r for r in scored if r["track"] == "simple"]
    summary = build_summary(
        {"simple": summarize_simple(simple)} if simple else {},
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
    items = _items_from_json(manifest["items"])
    no_usage = SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0, calls=0))
    try:
        await _score_and_summarize(store, run_dir, items, client, no_usage)
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
