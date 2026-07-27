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
        "canon": item.canon,
        # Why generation stopped. Needed to tell a model declining from a provider
        # blocking its own output (Google's RECITATION filter on verbatim
        # scripture): both yield an empty reply scoring 0, for opposite reasons.
        "finish_reason": resp.get("finish_reason"),
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
        # References are a claim signal ("these words are that verse") and are
        # resolved from the language's own localized book names.
        resolver = await QuoteAuditor(client)._resolver(first.version_id)  # noqa: SLF001

        for resp in lang_responses:
            item = items_by_id[resp["item_id"]]
            text = texts[item.id]
            refs = resolver.find(text)
            verdicts = _topical_verdicts(text, detections.get(item.id, {}), refs)
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
                "finish_reason": resp.get("finish_reason"),
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


# The system prompt asks for the reference immediately AFTER the quotation, so a
# following reference is the expected form and gets a generous window. A
# PRECEDING reference only counts when it's tight against the quote ("Psalm 23:1:
# ...") — widen this and a denial like "Psalm 153:1 does not exist … you may mean:
# '<verse>'" would wrongly read the denied reference as the quote's attribution.
_ATTRIBUTION_AFTER = 120
_ATTRIBUTION_BEFORE = 30


def _attribute(verdicts: list[dict], refs) -> None:
    """Attach the reference the model gave for each quotation, or None.

    Adjacency-gated on purpose: only a reference actually next to the quoted span
    is a claim about it. A reference elsewhere in the answer leaves the quotation
    unattributed rather than borrowing someone else's citation — the bug that
    turned correct answers into "misattributed", including the ideal
    hallucination-track answer (deny the reference, then offer a real verse).
    """
    for v in verdicts:
        v["cited_usfm"] = None
        start, end = v.get("raw_start"), v.get("raw_end")
        if start is None or end is None:
            continue  # unmarked quotation: no span to anchor a reference to
        near = [r for r in refs if end <= r.start <= end + _ATTRIBUTION_AFTER]
        if not near:
            near = [r for r in refs if start - _ATTRIBUTION_BEFORE <= r.end <= start]
        if near:
            v["cited_usfm"] = min(
                near, key=lambda r: min(abs(r.start - end), abs(start - r.end))
            ).usfm


# A span whose boundaries we INFERRED (from a nearby reference) rather than read
# off quotation marks needs a whole-string floor: we're guessing what the model
# meant to quote, so only a confident match should be judged. Marked spans need
# no floor — the model delimited them, so a poor match is a real misquote.
_INFERRED_FLOOR = 0.90
_CLAIM_WINDOW = 160  # chars either side of a reference that it plausibly labels


def _topical_verdicts(text: str, detections: dict, refs=()) -> list[dict]:
    """Verdicts for text the model PRESENTED as scripture.

    Presentation is the trigger, not resemblance. Using biblical-sounding words is
    not a claim, and judging it as a quotation would be a category error — so a
    span is examined only when the model actually claimed it:

      1. quotation marks or a blockquote — exact boundaries, no floor needed;
      2. a Bible reference next to it — a claim that the neighbouring words are
         that verse. Boundaries are inferred, so ``_INFERRED_FLOOR`` applies.

    Everything else is left alone, however scriptural it sounds. (A third signal —
    "the Bible says…" phrases — is deliberately not implemented yet: it would need
    maintaining in 11 languages, and legs 1 and 2 are language-independent. Worth
    measuring what they miss before taking that on.)
    """
    """Turn raw verse detections into per-quotation verdicts.

    A detection counts as a quotation when the model either marked it as one
    (quote glyphs / blockquote) or reproduced a verse closely enough that it is
    verbatim rather than paraphrase. Unmarked text below that bar is left alone,
    so ordinary prose about a passage is never scored as a misquote.
    """
    loose = normalize(text, "loose")
    # (loose_start, loose_end, raw_start, raw_end, loose_span_text) per marked
    # quotation. Raw offsets ride along so attribution can be adjacency-gated
    # against references extracted from the raw text.
    marked_spans: list[tuple[int, int, int, int, str]] = []
    for span in extract_quotes(text):
        q = normalize(span.text, "loose")
        at = loose.find(q[:60]) if q else -1
        if at >= 0:
            marked_spans.append((at, at + len(q), span.start, span.end, q))

    # Score every candidate first, then keep the best one per stretch of text.
    # One quotation is one verdict: several verses can match the same words (Luke
    # 4:18 quotes Isaiah 61:1, and translations of a psalm echo each other), and
    # emitting a verdict for each would let the runners-up drag the mean down for
    # a quotation the model got right.
    # Leg 2: regions the model labelled with a reference. Reference offsets are in
    # the RAW text, so scale to loose offsets — approximate is fine, the window is
    # deliberately loose.
    scale = (len(loose) / len(text)) if text else 1.0
    claim_regions = [
        (max(0, int(r.start * scale) - _CLAIM_WINDOW), int(r.end * scale) + _CLAIM_WINDOW)
        for r in refs
    ]

    scored: list[tuple[float, int, int, dict]] = []
    for usfm, det in sorted(detections.items(), key=lambda kv: kv[1].start):
        hit = next(
            (m for m in marked_spans if det.start < m[1] and m[0] < det.end), None
        )
        if hit is not None:
            # The model marked this as a quotation, so judge the words it actually
            # put in quotes: fidelity says whether they're right, coverage says how
            # much of the verse it delivered. A verbatim fragment is faithful (not
            # a misquote) but earns credit in proportion to what it quoted.
            span_loose = hit[4]
            fidelity, coverage = det.fidelity_and_coverage(span_loose)
            quote_text, raw_start, raw_end = span_loose, hit[2], hit[3]
        else:
            # No quotation marks: only examine this at all if the model put a
            # reference beside it, which is the claim "these words are that verse".
            claimed = any(det.start < e and s < det.end for s, e in claim_regions)
            if not claimed:
                continue
            # Boundaries are inferred, so demand a confident whole-string match.
            # whole_ratio has no best-window allowance: a stock phrase that happens
            # to sit inside a verse scores low here even though partial alignment
            # would call it perfect.
            if det.whole_ratio < _INFERRED_FLOOR:
                continue
            fidelity, coverage = det.whole_ratio, 1.0
            quote_text, raw_start, raw_end = loose[det.start:det.end], None, None

        if fidelity >= ACCURATE_SIM:
            classification = "accurate"
        elif fidelity >= MINOR_SIM:
            classification = "minor"
        else:
            classification = "misquote"
        score = 0.0 if classification == "misquote" else round(fidelity * coverage, 4)

        lo, hi = (hit[0], hit[1]) if hit is not None else (det.start, det.end)
        scored.append((score, lo, hi, {
            "quote": quote_text[:400],
            "classification": classification,
            "similarity": round(fidelity, 4),
            "coverage": round(coverage, 4),
            "matched_usfm": usfm,
            "matched_version_id": det.version_id,
            "score": score,
            "unquoted": hit is None,
            "raw_start": raw_start,
            "raw_end": raw_end,
        }))

    # Best-first, keeping a verdict only if its text doesn't overlap one already
    # kept — so each quotation is attributed to the verse it matches best.
    out: list[dict] = []
    taken: list[tuple[int, int]] = []
    for _score, lo, hi, verdict in sorted(scored, key=lambda t: -t[0]):
        if any(lo < e and s < hi for s, e in taken):
            continue
        taken.append((lo, hi))
        out.append(verdict)

    # Anything the model explicitly presented as a quotation but which matches no
    # verse in any translation is invented scripture, and must be scored as such.
    # Content-first detection only yields verdicts for text that MATCHES, so
    # without this a fabricated quote would produce no verdict at all — reading as
    # "quoted nothing", which is a pass on the hallucination track and free
    # omission from the topical average.
    claimed = {(v["raw_start"], v["raw_end"]) for v in out if v["raw_start"] is not None}
    for _lo, _hi, raw_start, raw_end, span_loose in marked_spans:
        if (raw_start, raw_end) in claimed:
            continue
        out.append({
            "quote": span_loose[:400],
            "classification": "fabricated",
            "similarity": 0.0,
            "coverage": 0.0,
            "matched_usfm": None,
            "matched_version_id": None,
            "score": 0.0,
            "unquoted": False,
            "raw_start": raw_start,
            "raw_end": raw_end,
        })
    out.sort(key=lambda v: (v["raw_start"] if v["raw_start"] is not None else 1 << 30))
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
        # absent_from_version items ask about a book the tested translation lacks,
        # so its metadata has no name for it. Merge in the edition that does, or
        # "Sirach 1:1" wouldn't resolve and a correct self-citation would read as
        # an uncited quotation.
        absent_sources = sorted({
            items_by_id[r["item_id"]].absent_source_version_id
            for r in lang_responses
            if items_by_id[r["item_id"]].absent_source_version_id
        })
        resolver = await auditor._resolver(  # noqa: SLF001
            first.version_id, *(v for v in absent_sources if v != first.version_id)
        )

        for resp in lang_responses:
            item = items_by_id[resp["item_id"]]
            text = texts[item.id]
            verdicts = _topical_verdicts(text, detections.get(item.id, {}))
            # Attribution is adjacency-gated (see _attribute), which is what
            # keeps the denied phantom reference from being read as the citation
            # for a substitute verse offered later in the answer.
            refs = resolver.find(text)
            _attribute(verdicts, refs)
            pscore = score_phantom_verdicts(verdicts, text, item.denial_markers)
            results.append({
                "item_id": item.id,
                "track": "phantom",
                "language_tag": item.language_tag,
                "version_id": item.version_id,
                "version_abbrev": item.version_abbrev,
                "reference_display": item.reference_display,
                "kind": item.kind,
                "absent_usfm": item.absent_usfm,
                "absent_source_abbrev": item.absent_source_abbrev,
                "finish_reason": resp.get("finish_reason"),
                "response_text": text,
                "phantom_score": asdict(pscore),
                "quotes": verdicts,
                "cited_refs": [r.usfm for r in refs],
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
