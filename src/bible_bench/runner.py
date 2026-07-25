"""Track orchestration: generate model responses, then score them.

Generation and scoring are separate passes sharing one run directory, so a
run can be re-scored under a new SCORING_VERSION without re-querying the model.
Both passes are resumable — re-running skips items already present.

Generation FAILS FAST. A model call that exhausts its retries aborts the whole
run (see EvaluationError). A benchmark result assembled from a partially-failed
generation pass is not a measurement of the model — failed calls land in the
scorers as "no attempt", which silently deflates the direct-quote and topical
scores and silently INFLATES hallucination resistance (an empty response reads
as "declined to quote", i.e. a pass). Better to abort loudly and re-run than to
publish a plausible-looking invalid number.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import asdict

from . import quotefind
from .adversarial.encounter import run_encounter
from .adversarial.goals import Goal
from .adversarial.judge import AdversarialJudge
from .auditor import ACCURATE_SIM, MINOR_SIM, QuoteAuditor, extract_quotes
from .dataset import BenchmarkItem
from .llm import LlmClient
from .normalize import normalize
from .phantom import PhantomItem, score_phantom_verdicts
from .prompts import BENCHMARK_SYSTEM_PROMPT, render_simple_prompt
from .scoring import score_item
from .topical import TopicalItem, score_topical_verdicts
from .yv_client import BibleClient

ProgressCb = Callable[[dict], None]
CheckpointCb = Callable[[list[dict]], Awaitable[None] | None]

_CHECKPOINT_EVERY = 25


class EvaluationError(RuntimeError):
    """A model call failed after all retries, so the run's data is incomplete.

    Raised to abort the run rather than record a hole in the results. Carries the
    item id and the underlying cause so the failure is diagnosable from the CLI
    output alone.
    """


def _messages(prompt: str) -> list[dict[str, str]]:
    """The system + user messages sent for one item (system prompt on every
    test, all tracks)."""
    return [
        {"role": "system", "content": BENCHMARK_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def _response_record(item_id: str, prompt: str, resp, error: str | None) -> dict:
    """One generation record: the reply text plus all captured response metadata
    (finish_reason, refusal, token/reasoning counts, served model, provider, and
    the full raw payload) so any oddity is drillable after the fact. ``resp`` is
    an LlmResponse, or None when the call raised (``error`` set)."""
    return {
        "item_id": item_id,
        "prompt": prompt,
        "response_text": resp.text if resp else "",
        "finish_reason": resp.finish_reason if resp else None,
        "refusal": resp.refusal if resp else None,
        "input_tokens": resp.prompt_tokens if resp else 0,
        "output_tokens": resp.completion_tokens if resp else 0,
        "reasoning_tokens": resp.reasoning_tokens if resp else None,
        "model_served": resp.model if resp else None,
        "response_id": resp.response_id if resp else None,
        "system_fingerprint": resp.system_fingerprint if resp else None,
        "provider": resp.provider if resp else None,
        "error": error,
        "raw": resp.raw if resp else None,
    }


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
            resp = None
            prompt = ""
            try:
                prompt = await render_simple_prompt(
                    client, item.version_id, item.usfm, item.template_id, item.language_tag
                )
                resp = await model.complete(_messages(prompt))
            except Exception as e:
                # Fail fast: retries are already exhausted inside the client, so
                # this item's data is unrecoverable and the run is invalid.
                raise EvaluationError(f"simple item {item.id}: {type(e).__name__}: {e}") from e
            rec = _response_record(item.id, prompt, resp, error)
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
    # Drop items whose ground-truth verse has no text (absent or blank in this
    # version) — there is nothing to score a quote against, same as a missing
    # verse. Prevents a blank truth from reaching qer(), which requires it.
    if truth_span is None or not truth_span.text.strip():
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
        resp = None
        async with sem:
            try:
                resp = await model.complete(_messages(item.prompt))
            except Exception as e:
                # Fail fast — see module docstring.
                raise EvaluationError(
                    f"{item.track} item {item.id}: {type(e).__name__}: {e}") from e
        rec = _response_record(item.id, item.prompt, resp, error)
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
    """Score topical responses by identifying quotations by CONTENT.

    Batched per language, translations in the outer loop: every quotation is
    identified against every translation the benchmark covers for that language
    (see quotefind), rather than against a short accepted list and whatever
    reference happened to sit next to it. A faithful quote of any real
    translation therefore counts as faithful, and which translation the model
    reached for is recorded rather than prescribed.
    """
    results: list[dict] = []
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for resp in responses:
        item = items_by_id.get(resp["item_id"])
        if item is not None:
            by_lang[item.language_tag].append(resp)

    done = 0
    total = sum(len(v) for v in by_lang.values())
    for lang, lang_responses in sorted(by_lang.items()):
        texts = {r["item_id"]: (r.get("response_text") or "") for r in lang_responses}
        sample = next((t for t in texts.values() if t), "")
        unspaced = quotefind.is_unspaced(sample)

        # Every translation of this language, recorded by prefetch. Falls back to
        # the item's accepted list if the manifest is missing.
        first = items_by_id[lang_responses[0]["item_id"]]
        version_ids = client.load_language_versions(lang) or (
            first.accepted_version_ids or [first.version_id]
        )
        detections = await quotefind.scan_responses(
            client, version_ids, texts, unspaced=unspaced
        )

        for resp in lang_responses:
            item = items_by_id[resp["item_id"]]
            text = texts[item.id]
            verdicts = _topical_verdicts(text, detections.get(item.id, {}))
            tscore = score_topical_verdicts(verdicts)
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
                "quotes": verdicts,
                "translations_searched": len(version_ids),
                "usage": {
                    "input_tokens": resp.get("input_tokens", 0),
                    "output_tokens": resp.get("output_tokens", 0),
                },
                "error": resp.get("error"),
            })
            done += 1
            if progress:
                progress({"phase": "score", "completed": done, "total": total})
    results.sort(key=lambda r: r["item_id"])
    return results


def _topical_verdicts(text: str, detections: dict) -> list[dict]:
    """Turn raw verse detections into per-quotation verdicts.

    A detection counts as a quotation when the model either marked it as one
    (quote glyphs / blockquote) or reproduced a verse closely enough that it is
    verbatim rather than paraphrase. Unmarked text below that bar is left alone,
    so ordinary prose about a passage is never scored as a misquote.
    """
    loose = normalize(text, "loose")
    quoted_ranges: list[tuple[int, int]] = []
    for span in extract_quotes(text):
        # Map the quoted span into loose-normalized offsets by locating its own
        # normalized text; exact offsets aren't needed, only overlap.
        q = normalize(span.text, "loose")
        at = loose.find(q[:60]) if q else -1
        if at >= 0:
            quoted_ranges.append((at, at + len(q)))

    out: list[dict] = []
    for usfm, det in sorted(detections.items(), key=lambda kv: kv[1].start):
        marked = any(det.start < e and s < det.end for s, e in quoted_ranges)
        if not marked and det.similarity < MINOR_SIM:
            continue  # unmarked and not verbatim → paraphrase, not a quotation
        if det.similarity >= ACCURATE_SIM:
            classification, score = "accurate", 1.0
        elif det.similarity >= MINOR_SIM:
            classification, score = "minor", round(det.similarity, 4)
        else:
            classification, score = "misquote", 0.0
        out.append({
            "quote": loose[det.start:det.end][:400],
            "classification": classification,
            "similarity": round(det.similarity, 4),
            "matched_usfm": usfm,
            "matched_version_id": det.version_id,
            "score": score,
            "unquoted": not marked,
        })
    return out


async def generate_phantom(
    items: list[PhantomItem],
    model: LlmClient,
    *,
    concurrency: int = 12,
    already_done: set[str] | None = None,
    checkpoint: CheckpointCb | None = None,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Query the model for each phantom item (prompt precomputed). Answers are
    short — a refusal or a (bad) fabricated verse — so a modest token budget.
    Mirrors ``generate_topical``'s resume/checkpoint semantics."""
    done = already_done or set()
    todo = [it for it in items if it.id not in done]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    collected: list[dict] = []

    async def one(item: PhantomItem) -> None:
        error = None
        resp = None
        async with sem:
            try:
                resp = await model.complete(_messages(item.prompt))
            except Exception as e:
                # Fail fast — see module docstring.
                raise EvaluationError(
                    f"{item.track} item {item.id}: {type(e).__name__}: {e}") from e
        rec = _response_record(item.id, item.prompt, resp, error)
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


async def score_phantom_items(
    items_by_id: dict[str, PhantomItem],
    responses: list[dict],
    client: BibleClient,
    *,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Score phantom responses: asserting scripture where none exists fails;
    declining — or offering a real, clearly-cited substitute, ideally with a
    "that isn't in the Bible" note — passes. See phantom.score_phantom.

    Detection is content-first and covers every translation of the language, so a
    model that correctly quotes a real verse as a helpful alternative is credited
    for it instead of being marked as inventing text merely because it used a
    translation the old accepted list didn't include.
    """
    results: list[dict] = []
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for resp in responses:
        item = items_by_id.get(resp["item_id"])
        if item is not None:
            by_lang[item.language_tag].append(resp)

    auditor = QuoteAuditor(client)  # reference extraction only (attribution check)
    done = 0
    total = sum(len(v) for v in by_lang.values())
    for lang, lang_responses in sorted(by_lang.items()):
        texts = {r["item_id"]: (r.get("response_text") or "") for r in lang_responses}
        sample = next((t for t in texts.values() if t), "")
        first = items_by_id[lang_responses[0]["item_id"]]
        version_ids = client.load_language_versions(lang) or (
            first.accepted_version_ids or [first.version_id]
        )
        detections = await quotefind.scan_responses(
            client, version_ids, texts, unspaced=quotefind.is_unspaced(sample)
        )
        resolver = await auditor._resolver(first.version_id)  # noqa: SLF001

        for resp in lang_responses:
            item = items_by_id[resp["item_id"]]
            text = texts[item.id]
            verdicts = _topical_verdicts(text, detections.get(item.id, {}))
            # Attribution: did the model print the reference for what it quoted?
            cited = [r.usfm for r in resolver.find(text)]
            for v in verdicts:
                v["cited_usfm"] = v["matched_usfm"] if v["matched_usfm"] in cited else (
                    cited[0] if cited else None
                )
            pscore = score_phantom_verdicts(verdicts, text, item.denial_markers)
            results.append({
                "item_id": item.id,
                "track": "phantom",
                "language_tag": item.language_tag,
                "version_id": item.version_id,
                "version_abbrev": item.version_abbrev,
                "reference_display": item.reference_display,
                "kind": item.kind,
                "response_text": text,
                "phantom_score": asdict(pscore),
                "quotes": verdicts,
                "cited_refs": cited,
                "translations_searched": len(version_ids),
                "usage": {
                    "input_tokens": resp.get("input_tokens", 0),
                    "output_tokens": resp.get("output_tokens", 0),
                },
                "error": resp.get("error"),
            })
            done += 1
            if progress:
                progress({"phase": "score", "completed": done, "total": total})
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


async def prefetch_versions(
    client: BibleClient,
    version_ids: list[int],
    *,
    concurrency: int = 8,
    progress: ProgressCb | None = None,
) -> dict:
    """Fetch every chapter of each version into the client's (disk) cache.

    This is the run-independent, shared-across-runs work — chiefly the whole-
    Bible text the topical reverse index needs. Idempotent: chapters already
    on disk are loaded, not re-fetched, so it resumes cleanly. Returns simple
    stats. Requires the client to have been constructed with a cache_dir."""
    # Enumerate all (version, chapter) pairs first (needs version.json each).
    pairs: list[tuple[int, str]] = []
    per_version: dict[int, int] = {}
    for vid in version_ids:
        try:
            chapters = await client.chapter_usfms(vid)
        except Exception:  # noqa: BLE001 — skip a version that won't resolve
            per_version[vid] = 0
            continue
        per_version[vid] = len(chapters)
        pairs.extend((vid, cu) for cu in chapters)

    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    done = 0

    async def one(vid: int, cu: str) -> None:
        nonlocal done
        async with sem:
            await client.chapter(vid, cu)  # read-through/write-through cache
        async with lock:
            done += 1
            if progress:
                progress({"phase": "prefetch", "completed": done, "total": len(pairs)})

    await asyncio.gather(*(one(v, c) for v, c in pairs))
    return {"versions": len(version_ids), "chapters": len(pairs), "per_version": per_version}


async def _maybe_await(maybe) -> None:
    if asyncio.iscoroutine(maybe):
        await maybe
