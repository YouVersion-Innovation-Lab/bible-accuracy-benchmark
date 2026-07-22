"""Track orchestration: generate model responses, then score them.

Generation and scoring are separate passes sharing one run directory, so a
run can be re-scored under a new SCORING_VERSION without re-querying the model.
Both passes are resumable — re-running skips items already present.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict

from .adversarial.encounter import run_encounter
from .adversarial.goals import Goal
from .adversarial.judge import AdversarialJudge
from .auditor import QuoteAuditor
from .dataset import BenchmarkItem
from .llm import LlmClient
from .normalize import normalize
from .prompts import render_simple_prompt
from .scoring import score_item
from .topical import TopicalItem, score_topical
from .yv_client import BibleClient

ProgressCb = Callable[[dict], None]
CheckpointCb = Callable[[list[dict]], Awaitable[None] | None]

_CHECKPOINT_EVERY = 25


async def generate_simple(
    items: list[BenchmarkItem],
    client: BibleClient,
    model: LlmClient,
    *,
    concurrency: int = 12,
    already_done: set[str] | None = None,
    checkpoint: CheckpointCb | None = None,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Query the model for each not-yet-done item.

    Returns the new response records. ``checkpoint`` (if given) is called under
    a lock with the full list-so-far every few completions and once at the end,
    so the caller can persist for resume without racing on the output file.
    """
    done = already_done or set()
    todo = [it for it in items if it.id not in done]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    collected: list[dict] = []

    async def one(item: BenchmarkItem) -> None:
        async with sem:
            error = None
            text = ""
            in_tok = out_tok = 0
            try:
                prompt = await render_simple_prompt(
                    client, item.version_id, item.usfm, item.template_id, item.language_tag
                )
                async with lock:
                    before_in = model.usage.input_tokens
                    before_out = model.usage.output_tokens
                text = await model.complete([{"role": "user", "content": prompt}], max_tokens=512)
                async with lock:
                    in_tok = model.usage.input_tokens - before_in
                    out_tok = model.usage.output_tokens - before_out
            except Exception as e:  # noqa: BLE001 — record per-item failures, don't abort the run
                error = f"{type(e).__name__}: {e}"
                prompt = ""
            rec = {
                "item_id": item.id,
                "prompt": prompt,
                "response_text": text,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "error": error,
            }
            async with lock:
                collected.append(rec)
                if progress:
                    progress({"phase": "generate", "completed": len(collected),
                              "total": len(todo), "error": bool(error)})
                if checkpoint and len(collected) % _CHECKPOINT_EVERY == 0:
                    await _maybe_await(checkpoint(list(collected)))

    await asyncio.gather(*(one(it) for it in todo))
    if checkpoint:
        await _maybe_await(checkpoint(list(collected)))
    return collected


async def score_simple(
    items_by_id: dict[str, BenchmarkItem],
    responses: list[dict],
    client: BibleClient,
    *,
    concurrency: int = 12,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Score generated responses against ground truth fetched live."""
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    lock = asyncio.Lock()
    completed = 0

    async def one(resp: dict) -> None:
        nonlocal completed
        async with sem:
            record = await _score_one(items_by_id.get(resp["item_id"]), resp, client)
        async with lock:
            completed += 1
            if record:
                results.append(record)
            if progress:
                progress({"phase": "score", "completed": completed, "total": len(responses)})

    await asyncio.gather(*(one(r) for r in responses))
    # Stable order for reproducible output files.
    results.sort(key=lambda r: r["item_id"])
    return results


async def _score_one(item: BenchmarkItem | None, resp: dict, client: BibleClient) -> dict | None:
    if item is None:
        return None
    truth_span = await client.verse(item.version_id, item.usfm)
    if truth_span is None:
        return None
    distractors: dict[str, str] = {}
    for vid in item.distractor_version_ids:
        span = await client.verse(vid, item.usfm)
        if span is not None:
            distractors[str(vid)] = span.text
    chapter_usfm = item.usfm.rsplit(".", 1)[0]
    neighbors = {
        u: t
        for u, t in (await client.chapter_verses(item.version_id, chapter_usfm)).items()
        if u != item.usfm
    }
    score = score_item(resp["response_text"], truth_span.text, distractors, neighbors)
    truth_digest = hashlib.sha256(normalize(truth_span.text, "loose").encode()).hexdigest()
    return {
        "item_id": item.id,
        "track": item.track,
        "language_tag": item.language_tag,
        "language_name": item.language_name,
        "version_id": item.version_id,
        "version_abbrev": item.version_abbrev,
        "usfm": item.usfm,
        "tier": item.tier,
        "response_text": resp["response_text"],
        "expected_text": truth_span.text,
        "score": asdict(score),
        "ground_truth_drift": bool(item.truth_sha256) and truth_digest != item.truth_sha256,
        "usage": {
            "input_tokens": resp.get("input_tokens", 0),
            "output_tokens": resp.get("output_tokens", 0),
        },
        "error": resp.get("error"),
    }


async def generate_topical(
    items: list[TopicalItem],
    model: LlmClient,
    *,
    concurrency: int = 12,
    already_done: set[str] | None = None,
    checkpoint: CheckpointCb | None = None,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Query the model for each topical item (prompt is precomputed on the item).

    Topical answers are long-form, so a larger token budget than the simple
    track. Mirrors ``generate_simple``'s resume/checkpoint semantics."""
    done = already_done or set()
    todo = [it for it in items if it.id not in done]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    collected: list[dict] = []

    async def one(item: TopicalItem) -> None:
        error = None
        text = ""
        in_tok = out_tok = 0
        async with sem:
            try:
                async with lock:
                    before_in = model.usage.input_tokens
                    before_out = model.usage.output_tokens
                text = await model.complete(
                    [{"role": "user", "content": item.prompt}], max_tokens=1024
                )
                async with lock:
                    in_tok = model.usage.input_tokens - before_in
                    out_tok = model.usage.output_tokens - before_out
            except Exception as e:  # noqa: BLE001
                error = f"{type(e).__name__}: {e}"
        rec = {
            "item_id": item.id,
            "prompt": item.prompt,
            "response_text": text,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "error": error,
        }
        async with lock:
            collected.append(rec)
            if progress:
                progress({"phase": "generate", "completed": len(collected),
                          "total": len(todo), "error": bool(error)})
            if checkpoint and len(collected) % _CHECKPOINT_EVERY == 0:
                await _maybe_await(checkpoint(list(collected)))

    await asyncio.gather(*(one(it) for it in todo))
    if checkpoint:
        await _maybe_await(checkpoint(list(collected)))
    return collected


async def score_topical_items(
    items_by_id: dict[str, TopicalItem],
    responses: list[dict],
    client: BibleClient,
    *,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Audit each topical response deterministically and apply A×E scoring.

    Serialized per item because the auditor builds per-version reverse indexes
    lazily; the BibleClient's own concurrency ceiling still parallelizes the
    underlying verse fetches."""
    auditor = QuoteAuditor(client)
    results: list[dict] = []
    for i, resp in enumerate(responses, 1):
        item = items_by_id.get(resp["item_id"])
        if item is None:
            continue
        text = resp.get("response_text") or ""
        audit = await auditor.audit(
            text,
            item.version_id,
            candidate_version_ids=item.accepted_version_ids or [item.version_id],
            use_reverse_index=True,
        )
        tscore = score_topical(audit)
        results.append({
            "item_id": item.id,
            "track": "topical",
            "language_tag": item.language_tag,
            "version_id": item.version_id,
            "version_abbrev": item.version_abbrev,
            "topic_id": item.topic_id,
            "topic_name": item.topic_name,
            "elicitation_level": item.elicitation_level,
            "sensitive": item.sensitive,
            "response_text": text,
            "topical_score": asdict(tscore),
            "quotes": [asdict(v) for v in audit.verdicts],
            "cited_refs": audit.cited_refs,
            "fabricated_refs": audit.fabricated_refs,
            "usage": {
                "input_tokens": resp.get("input_tokens", 0),
                "output_tokens": resp.get("output_tokens", 0),
            },
            "error": resp.get("error"),
        })
        if progress:
            progress({"phase": "score", "completed": i, "total": len(responses)})
    results.sort(key=lambda r: r["item_id"])
    return results


async def run_adversarial(
    goals: list[Goal],
    attacker: LlmClient,
    target: LlmClient,
    client: BibleClient,
    version_id: int,
    accepted: list[int],
    *,
    turn_depth: int = 3,
    concurrency: int = 6,
    already_done: set[str] | None = None,
    checkpoint: CheckpointCb | None = None,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Run each goal as an encounter (attacker vs. target, deterministic judge).

    Encounters are independent and resumable by goal_id. One shared auditor
    caches per-version resolvers/indexes across goals."""
    judge = AdversarialJudge(QuoteAuditor(client), version_id, accepted)
    done = already_done or set()
    todo = [g for g in goals if g.id not in done]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    collected: list[dict] = []

    async def one(goal: Goal) -> None:
        async with sem:
            result = await run_encounter(
                goal, attacker, target, judge, turn_depth=turn_depth
            )
        async with lock:
            collected.append(result.to_json())
            if progress:
                progress({"phase": "generate", "completed": len(collected),
                          "total": len(todo), "error": result.errored})
            if checkpoint and len(collected) % 10 == 0:
                await _maybe_await(checkpoint(list(collected)))

    await asyncio.gather(*(one(g) for g in todo))
    if checkpoint:
        await _maybe_await(checkpoint(list(collected)))
    return collected


async def _maybe_await(maybe) -> None:
    if asyncio.iscoroutine(maybe):
        await maybe
