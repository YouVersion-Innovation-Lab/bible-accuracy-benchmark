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
import re
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
    """Score generated responses against ground truth from the local cache.

    The requested verse is looked up in EVERY translation of the language, not in
    a handful of configured distractors. Without that, a model quoting the right
    verse faithfully from an edition we didn't ask for looked like it had invented
    the text: asked for Judges 11:11 in the NABRE, one model returned the verse
    verbatim in another translation and scored zero as "fabricated". This is the
    same content-first principle the topical track already used — identify what
    the text actually IS before judging it.

    Translations iterate in the outer loop and are released after use, so peak
    memory is one translation's worth of chapters rather than 87.
    """
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for resp in responses:
        item = items_by_id.get(resp["item_id"])
        if item is not None:
            by_lang[item.language_tag].append(resp)

    results: list[dict] = []
    completed = 0
    total = sum(len(v) for v in by_lang.values())
    for lang, lang_responses in sorted(by_lang.items()):
        items = [items_by_id[r["item_id"]] for r in lang_responses]
        # Every translation of the language, plus the ones the items name (a
        # version tested but somehow absent from the cached language list must
        # still supply its own ground truth).
        candidates = client.load_language_versions(lang, include_duplicates=True)
        version_ids = sorted({*candidates, *(i.version_id for i in items)})

        # item_id -> {version_id: text of the requested verse in that translation}
        alt: dict[str, dict[int, str]] = {i.id: {} for i in items}
        # item_id -> same-chapter neighbours, from the version actually asked for
        neighbors: dict[str, dict[str, str]] = {i.id: {} for i in items}
        for vid in version_ids:
            for item in items:
                span = await client.verse(vid, item.usfm)
                if span is not None and span.text.strip():
                    alt[item.id][vid] = span.text
                if vid == item.version_id:
                    chapter = item.usfm.rsplit(".", 1)[0]
                    neighbors[item.id] = {
                        u: t
                        for u, t in (await client.chapter_verses(vid, chapter)).items()
                        if u != item.usfm
                    }
            client.release_version(vid)

        # Grading is now pure CPU — every candidate text was gathered above — so a
        # plain loop beats a semaphore and a gather.
        for resp in lang_responses:
            item = items_by_id[resp["item_id"]]
            record = _score_one(item, resp, alt[item.id], neighbors[item.id])
            completed += 1
            if record:
                results.append(record)
            if progress:
                progress({"phase": "score", "completed": completed, "total": total})
    # Stable order for reproducible output files.
    results.sort(key=lambda r: r["item_id"])
    return results


def _score_one(
    item: BenchmarkItem,
    resp: dict,
    alt_versions: dict[int, str],
    neighbors: dict[str, str],
) -> dict | None:
    """Grade one answer. ``alt_versions`` is the requested verse as every
    translation of the language renders it, keyed by version id."""
    truth = alt_versions.get(item.version_id, "")
    # Drop items whose ground-truth verse has no text (absent or blank in this
    # version) — there is nothing to score a quote against, same as a missing
    # verse. Prevents a blank truth from reaching qer(), which requires it.
    if not truth.strip():
        return None
    # Every OTHER translation's rendering of the same verse is a wrong-version
    # candidate. Keyed by version id so the report can name which edition the
    # model actually quoted.
    distractors = {str(vid): t for vid, t in alt_versions.items() if vid != item.version_id}
    score = score_item(resp["response_text"], truth, distractors, neighbors)
    truth_digest = hashlib.sha256(normalize(truth, "loose").encode()).hexdigest()
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
        "expected_text": truth,
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
        spans, marked_by_item = _spans_for(texts)
        detections, identified = await quotefind.scan_and_identify(
            client, version_ids, texts, spans, unspaced=unspaced
        )
        # References are a claim signal ("these words are that verse") and are
        # resolved from the language's own localized book names.
        resolver = await QuoteAuditor(client)._resolver(first.version_id)  # noqa: SLF001

        for resp in lang_responses:
            item = items_by_id[resp["item_id"]]
            text = texts[item.id]
            refs = resolver.find(text)
            verdicts = _topical_verdicts(
                text, detections.get(item.id, {}), refs,
                _span_ids_for(item.id, marked_by_item[item.id], identified),
            )
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

# Shortest quoted span that can be called invented scripture. Below this it's a
# phrase in quotation marks, not a claim about a verse — and any real verse this
# short is now findable by content, so nothing genuine is lost by ignoring them.
_MIN_FABRICATION_WORDS = 6
_WORDS = re.compile(r"\w+", re.UNICODE)



def _spans_for(texts: dict[str, str]) -> tuple[list, dict[str, list]]:
    """Marked quotations across a batch, as quotefind Spans plus the per-item list.

    Span keys are "{item_id}#{ordinal}", and the ordinal is the index into
    ``marked_spans_of`` — the same order the verdict builder uses to look results
    up, so the two can never drift apart.
    """
    spans: list = []
    per_item: dict[str, list] = {}
    for item_id, text in texts.items():
        marked = marked_spans_of(text)
        per_item[item_id] = marked
        for i, m in enumerate(marked):
            spans.append(quotefind.Span(
                key=f"{item_id}#{i}", item_id=item_id, text=m[4], quoted=True,
            ))
    return spans, per_item


def _span_ids_for(item_id: str, marked: list, identified: dict) -> dict[int, object]:
    """Identifications for one item's marked spans, keyed by ordinal."""
    out: dict[int, object] = {}
    for i in range(len(marked)):
        ident = identified.get(f"{item_id}#{i}")
        if ident is not None:
            out[i] = ident
    return out



def marked_spans_of(text: str) -> list[tuple[int, int, int, int, str]]:
    """Quotations the model delimited itself, as
    (loose_start, loose_end, raw_start, raw_end, loose_text).

    One source of truth, because two callers must agree on the ORDER: the scorer
    identifies each span by its ordinal here, and the verdict builder looks the
    results up by the same ordinal. Raw offsets ride along so attribution can be
    adjacency-gated against references extracted from the raw text.
    """
    loose = normalize(text, "loose")
    out: list[tuple[int, int, int, int, str]] = []
    for span in extract_quotes(text):
        q = normalize(span.text, "loose")
        at = loose.find(q[:60]) if q else -1
        if at >= 0:
            out.append((at, at + len(q), span.start, span.end, q))
    return out


def _classify(fidelity: float) -> str:
    """What a quotation IS, given how well its words match the verse it was
    identified as.

    Note what is absent: "fabricated". Reaching this function means a real verse
    was identified, so the only question left is how faithfully it was quoted.
    Invention is a separate finding — text that matches no verse in any
    translation — and conflating the two accused models of inventing scripture
    they had merely reworded.
    """
    if fidelity >= ACCURATE_SIM:
        return "accurate"
    if fidelity >= MINOR_SIM:
        return "minor"
    return "misquote"


def _verdict(
    quote_loose: str, classification: str, fidelity: float, coverage: float,
    usfm: str | None, version_id: int | None,
    raw_start: int | None, raw_end: int | None, *, unquoted: bool = False,
) -> dict:
    """One per-quotation verdict record. A misquote scores 0 — presenting wrong
    words as scripture is the failure, however close they came."""
    score = 0.0 if classification in ("misquote", "fabricated") else round(fidelity, 4)
    return {
        "quote": quote_loose[:400],
        "classification": classification,
        "similarity": round(fidelity, 4),
        "coverage": round(coverage, 4),
        "matched_usfm": usfm,
        "matched_version_id": version_id,
        "score": score,
        "unquoted": unquoted,
        "raw_start": raw_start,
        "raw_end": raw_end,
    }


def _topical_verdicts(
    text: str, detections: dict, refs=(), span_ids: dict[int, object] | None = None
) -> list[dict]:
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
    marked_spans = marked_spans_of(text)

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

    # Marked quotations are judged on their OWN words, by span-driven
    # identification (quotefind.scan_and_identify). Nothing here depends on
    # guessing where in the answer a quotation sits, which is what made a short
    # fragment of a long verse undetectable in a long answer.
    out: list[dict] = []
    for i, (_lo, _hi, raw_start, raw_end, span_loose) in enumerate(marked_spans):
        ident = (span_ids or {}).get(i)
        if ident is None:
            # Matched no verse in any translation of the language. Only now is
            # "invented" a fair word — and only for something long enough to be a
            # claim about a verse rather than a phrase in quotation marks.
            if len(_WORDS.findall(span_loose)) >= _MIN_FABRICATION_WORDS:
                out.append(_verdict(
                    span_loose, "fabricated", 0.0, 0.0, None, None, raw_start, raw_end,
                ))
            continue
        fidelity, coverage = ident.fidelity_and_coverage(span_loose)
        out.append(_verdict(
            span_loose, _classify(fidelity), fidelity, coverage,
            ident.usfm, ident.version_id, raw_start, raw_end,
        ))

    # Unmarked text is the other half, and needs the verse-driven pass: with no
    # quotation marks there are no boundaries to identify a span from. Only text
    # the model labelled with a reference is examined — that reference IS the claim
    # — and anything overlapping a marked quotation is already judged above.
    scored: list[tuple[float, int, int, dict]] = []
    for usfm, det in sorted(detections.items(), key=lambda kv: kv[1].start):
        if any(det.start < m[1] and m[0] < det.end for m in marked_spans):
            continue
        if not any(det.start < e and s < det.end for s, e in claim_regions):
            continue
        # Boundaries are inferred, so demand a confident whole-string match.
        # whole_ratio has no best-window allowance: a stock phrase that happens to
        # sit inside a verse scores low here even though partial alignment would
        # call it perfect.
        if det.whole_ratio < _INFERRED_FLOOR:
            continue
        fidelity = det.whole_ratio
        verdict = _verdict(
            loose[det.start:det.end], _classify(fidelity), fidelity, 1.0,
            usfm, det.version_id, None, None, unquoted=True,
        )
        scored.append((verdict["score"], det.start, det.end, verdict))

    # Best-first among the inferred ones, keeping a verdict only if its text
    # doesn't overlap one already kept: several verses can match the same words
    # (Luke 4:18 quotes Isaiah 61:1), and emitting a verdict for each would let the
    # runners-up drag the mean down for a quotation the model got right.
    taken: list[tuple[int, int]] = []
    for _score, lo, hi, verdict in sorted(scored, key=lambda t: -t[0]):
        if any(lo < e and s < hi for s, e in taken):
            continue
        taken.append((lo, hi))
        out.append(verdict)

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
        spans, marked_by_item = _spans_for(texts)
        detections, identified = await quotefind.scan_and_identify(
            client, version_ids, texts, spans, unspaced=quotefind.is_unspaced(sample)
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
            verdicts = _topical_verdicts(
                text, detections.get(item.id, {}), (),
                _span_ids_for(item.id, marked_by_item[item.id], identified),
            )
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
