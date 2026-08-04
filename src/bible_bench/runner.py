"""Track orchestration: generate model responses, then score them.

Generation and scoring are separate passes sharing one run directory, so a
run can be re-scored from its stored responses without re-querying the model.
Both passes are resumable — re-running skips items already present.

Generation FAILS FAST. A model call that exhausts its retries aborts the whole
run (see EvaluationError). A benchmark result assembled from a partially-failed
generation pass is not a measurement of the model — failed calls land in the
scorers as "no attempt", which silently deflates Quoting Accuracy and silently
REMOVES the hallucination penalty (an empty response reads as "declined to
quote", i.e. nothing to charge for). Better to abort loudly and re-run than to
publish a plausible-looking invalid number.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from . import provenance, quoted, quotefind, theology, versification
from .auditor import ACCURATE_SIM, QuoteAuditor, extract_quotes
from .dataset import REFERENCE_SCHEME, BenchmarkItem
from .hallucination import HallucinationItem, score_hallucination_verdicts
from .llm import LlmClient
from .normalize import normalize
from .prompts import BENCHMARK_SYSTEM_PROMPT, render_simple_prompt
from .scoring import score_item
from .theology import TheologyItem, run_encounter
from .versification import VersificationError
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
    same content-first principle the quote auditor already used — identify what
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
    # (index into results, item, response, distractors, neighbours) for answers a
    # single-language search could not explain. Re-examined once, at the end.
    unexplained: list[tuple[int, BenchmarkItem, dict, dict[int, str], dict[str, str]]] = []
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
                if record["score"]["grade"] in _UNEXPLAINED_GRADES:
                    # Keep only what a second look needs. Every OTHER language is
                    # still unsearched, so neither "invented" nor "didn't answer" is
                    # yet a claim we've earned — see _regrade_across_languages.
                    unexplained.append(
                        (len(results) - 1, item, resp, alt[item.id], neighbors[item.id])
                    )
            if progress:
                progress({"phase": "score", "completed": completed, "total": total})

    await _regrade_across_languages(unexplained, items_by_id, client, results)
    # Stable order for reproducible output files.
    results.sort(key=lambda r: r["item_id"])
    return results


async def _regrade_across_languages(
    unexplained: list[tuple[int, BenchmarkItem, dict, dict[int, str], dict[str, str]]],
    items_by_id: dict[str, BenchmarkItem],
    client: BibleClient,
    results: list[dict],
) -> None:
    """Give the answers we were about to call inventions one more look.

    Asked for a verse in one language, a model sometimes answers accurately in
    another — GPT-5.6 Terra declines an in-copyright translation and offers a
    public-domain one instead (docs/FINDINGS.md F-1), and MiniMax M3 answered a
    Spanish request with the verse in Chinese. Searching only the language asked
    made every one of those an invention.

    The verse is resolved per edition through the same versification path the
    dataset uses, so "the same verse" means the same verse and not the same verse
    NUMBER — Psalms are renumbered wholesale between schemes.

    Cost is proportional to the problem: only the two grades a single-language
    search cannot distinguish from a cross-language answer are re-examined, which
    across ten published runs was 318 items of ~2,500.
    """
    if not unexplained:
        return
    editions = sorted({
        (i.language_tag, i.version_id) for i in items_by_id.values()
    })
    # {item_id: {edition label: that edition's rendering of the same verse}}
    foreign: dict[str, dict[str, str]] = defaultdict(dict)
    for lang, vid in editions:
        scheme = ((await client.version(vid)).get("vrs") or REFERENCE_SCHEME).lower()
        for _idx, item, _resp, _alt, _neigh in unexplained:
            if item.language_tag == lang:
                continue  # same language: already covered by the distractor pass
            try:
                target = versification.translate(item.source_usfm, REFERENCE_SCHEME, scheme)
            except VersificationError:
                continue
            if not target:
                continue  # the verse does not exist under this scheme
            try:
                span = await client.verse(vid, target)
            except Exception:  # noqa: BLE001 — an edition without the verse tells us nothing
                continue
            if span is not None and span.text.strip():
                foreign[item.id][f"{lang}:{vid}"] = span.text
        client.release_version(vid)

    for idx, item, resp, alt_versions, neighbors in unexplained:
        record = _score_one(
            item, resp, alt_versions, neighbors, foreign=foreign.get(item.id)
        )
        if record:
            results[idx] = record


def _score_one(
    item: BenchmarkItem,
    resp: dict,
    alt_versions: dict[int, str],
    neighbors: dict[str, str],
    foreign: dict[str, str] | None = None,
) -> dict | None:
    """Grade one answer. ``alt_versions`` is the requested verse as every
    translation of the language renders it, keyed by version id; ``foreign`` is the
    same verse as editions in OTHER languages render it."""
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
    score = score_item(resp["response_text"], truth, distractors, neighbors, foreign)
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


CROSS_LANGUAGE_FLOOR = quoted.NEAR

# Direct-quote grades that a one-language search cannot tell apart from an answer
# given accurately in another language, and which therefore get a second look.
#
# ``no_attempt`` belongs here as much as ``fabricated`` does, which is not obvious.
# "Did the model attempt a quotation" is judged partly on length relative to the
# requested verse, and scripts differ enormously in how many characters the same
# sentence takes: a full, accurate Chinese verse is a fraction of the length of its
# English counterpart, so answering an English request from a Chinese Bible reads
# as too short to be an attempt at all. Both grades mean "we could not account for
# this answer", and neither is a finding until every language has been searched.
_UNEXPLAINED_GRADES = ("fabricated", "no_attempt")


@dataclass
class _Batch:
    """One language's responses with every quotation in them already identified.

    Shared by the two dimensions that judge scripture a model *volunteered*
    (the free-form auditing paths). They differ only in the
    verdict they draw from it, so the finding of quotations happens once.
    """

    lang: str
    responses: list[dict]
    texts: dict[str, str]
    editions: list[provenance.Source]
    detections: dict[str, dict[str, quotefind.Detection]]
    marked_by_item: dict[str, list]


async def _identify_quotations(
    items_by_id: dict,
    responses: list[dict],
    client: BibleClient,
    *,
    include_duplicates: bool,
    progress: ProgressCb | None = None,
) -> tuple[list[_Batch], dict[str, quoted.Judgement]]:
    """Find what every quoted span in every response actually is.

    Two passes, and the second is the one that keeps this honest:

      1. **the language asked about** — every edition of it, so a faithful quote
         from a translation we didn't nominate still reads as faithful;
      2. **every other language the benchmark covers** — but only for the spans
         pass 1 matched nothing at all.

    Pass 2 exists because "we searched one language and found nothing" was being
    reported as "the model invented this". Asked an open question in Hindi, Grok
    4.5 answers with Hindi prose and an accurate ENGLISH quotation; all 52 of its
    Hindi quotations were graded as invented scripture (docs/FINDINGS.md F-3).
    Quoting the right verse in the wrong language and inventing a verse are
    different failures, a frontier lab would fix them differently, and a benchmark
    that cannot tell them apart tells that lab the wrong thing.

    It is cheap because it is scoped to what pass 1 could not explain — a handful
    of spans — and to one edition per language rather than all ~200.
    """
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for resp in responses:
        item = items_by_id.get(resp["item_id"])
        if item is not None:
            by_lang[item.language_tag].append(resp)

    batches: list[_Batch] = []
    judgements: dict[str, quoted.Judgement] = {}
    all_spans: dict[str, quotefind.Span] = {}
    requested: dict[str, provenance.Source] = {}

    for lang, lang_responses in sorted(by_lang.items()):
        texts = {r["item_id"]: (r.get("response_text") or "") for r in lang_responses}
        first = items_by_id[lang_responses[0]["item_id"]]
        editions = [
            provenance.Source(version_id=vid, language_tag=lang)
            for vid in (
                client.load_language_versions(lang, include_duplicates=include_duplicates)
                or (first.accepted_version_ids or [first.version_id])
            )
        ]
        spans, marked_by_item = _spans_for(texts)
        # No edition is "the" one here: these dimensions let the model choose what
        # to quote, so preferring the item's nominal version would corrupt the
        # "which translation does this model reach for" finding. Language, though,
        # is what the reader asked in and does matter.
        for s in spans:
            all_spans[s.key] = s
            requested[s.key] = provenance.Source(version_id=None, language_tag=lang)
        detections, found = await quoted.scan(
            client, editions, texts, spans, requested=requested, progress=progress
        )
        judgements.update(found)
        batches.append(_Batch(
            lang=lang, responses=lang_responses, texts=texts, editions=editions,
            detections=detections, marked_by_item=marked_by_item,
        ))

    # Pass 2. One edition per language — the ones the benchmark itself tests — so
    # the cost is bounded no matter how many editions a language publishes.
    unexplained = [s for key, s in sorted(all_spans.items()) if key not in judgements]
    if unexplained:
        elsewhere = [
            provenance.Source(version_id=vid, language_tag=tag, version_abbrev=abbrev)
            for tag, vid, abbrev in sorted({
                (i.language_tag, i.version_id, i.version_abbrev)
                for i in items_by_id.values()
            })
        ]
        _, found = await quoted.scan(
            client, elsewhere, {}, unexplained, requested=requested,
            floor=CROSS_LANGUAGE_FLOOR, progress=progress,
        )
        judgements.update(found)
    return batches, judgements


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



async def _mark_absent_book_quotes(
    verdicts: list[dict], item: HallucinationItem, client: BibleClient, version_ids: list[int]
) -> None:
    """For an ``absent_from_version`` item, mark spans that quote the verse ASKED FOR.

    This item kind is the only one whose reference is REAL — "quote Sirach 1:1 from
    the NIV" asks for a verse that exists, just not in that Bible. So unlike the
    other kinds, we can compare against a known reference instead of searching
    blind, and that targeted comparison sees what open-ended detection can't.

    It matters because the Bible API doesn't expose every Catholic edition. Asked in
    French, a model answered with Wisdom 1:1 in Crampon-style wording; the nearest
    edition we hold renders it differently, so detection found nothing and the
    answer was recorded as invented scripture. Measured across twelve such answers,
    real quotations sit at 0.70–1.00 against the true verse while unrelated
    scripture from the same chapter sits at 0.43–0.52 — so ``quoted.RECOGNISABLE``
    (0.60), the floor every dimension shares, separates them with room to spare.

    Marked spans carry ``quoted_absent_book``, which tells the scorer the model
    answered the question it was asked rather than substituting a different verse —
    so the only thing left to judge is whether it said the book is outside this
    translation's canon. Without that, a model quoting the requested verse VERBATIM
    fell to "recited real scripture with neither a reference nor a warning" and
    scored zero: two Russian answers did exactly that, one at similarity 1.000, both
    with a citation our resolver failed to read because Synodal's metadata spells the
    book "Книга Премудрости Иисуса, сына Сирахова" and the model wrote "Сирах".
    Maintaining book-name aliases in eleven languages is the wrong fix; not treating
    the requested verse as a substitution is the right one.

    Spans additionally carry ``unverified_edition`` when only the loose comparison
    recognised them, recording that we cannot judge fidelity against a text we don't
    hold. Claiming otherwise in either direction would be a guess.
    """
    if item.kind != "absent_from_version" or not item.absent_usfm:
        return
    for v in verdicts:
        # Already identified as the verse asked for: nothing was substituted, so it
        # needs no citation check regardless of how faithfully it was quoted.
        if v.get("matched_usfm") == item.absent_usfm:
            v["quoted_absent_book"] = True
            # "Misquote" is a claim we can't support here. The tested Bible doesn't
            # carry this book, so the model chose an edition — and we may not hold
            # it. At 0.75-0.89 against the nearest we do hold, a different edition
            # is the likelier explanation than a sloppy quotation, and the hallucination
            # ladder treats a misquote as invention. Say what we actually know.
            if v.get("classification") == "misquote":
                v["classification"] = "unverified_edition"
                v["unverified_edition"] = True
            continue
        # Otherwise: detection found nothing, or called the wording a misquote —
        # which, against an edition we don't hold, we can't actually know.
        if v.get("matched_usfm") is not None:
            continue
        if v.get("classification") not in ("fabricated", "misquote"):
            continue
        quote = v.get("quote") or ""
        if not quote:
            continue
        best, best_vid = 0.0, None
        for vid in version_ids:
            try:
                span = await client.verse(vid, item.absent_usfm)
            except Exception:  # noqa: BLE001 — an edition without the book tells us nothing
                continue
            if span is None or not span.text.strip():
                continue
            sim = quotefind.similarity(quote, normalize(span.text, "loose"))
            if sim > best:
                best, best_vid = sim, vid
        if best >= quoted.RECOGNISABLE:
            v["classification"] = "unverified_edition"
            v["matched_usfm"] = item.absent_usfm
            v["nearest_version_id"] = best_vid
            v["similarity"] = round(best, 4)
            v["unverified_edition"] = True
            v["quoted_absent_book"] = True


async def _mark_citation_reality(
    verdicts: list[dict], client: BibleClient, version_ids: list[int]
) -> None:
    """Record whether each cited reference EXISTS in any translation of the language.

    This is what "misattributed a real verse" should turn on: asserting scripture at
    a reference no Bible has. Comparing the citation against the verse detection
    matched instead flagged correct answers — a model that denies "Exodus 43:1" and
    then offers Genesis 43:1 has done exactly the right thing, and was scored zero
    for it.

    Metadata only (``version_contains``), so it is cheap and offline.
    """
    for v in verdicts:
        cited = v.get("cited_usfm")
        if not cited:
            continue
        exists = False
        for vid in version_ids:
            if await client.version_contains(vid, cited):
                exists = True
                break
        v["cited_exists"] = exists


async def _reconcile_citations(
    verdicts: list[dict], client: BibleClient, version_ids: list[int]
) -> None:
    """Accept a citation that names the quoted text under a DIFFERENT verse number.

    "Misattributed a real verse" is the strongest accusation this benchmark makes
    — it says a model attached genuine scripture to a reference that isn't its own
    — and comparing usfm codes alone made it wrong every time it fired. Three ways
    a correct citation gets a different code from the verse detection matched:

      * **versification.** Psalm 23 in Hebrew numbering is Psalm 22 in the
        Septuagint, which Russian Synodal follows; Isaiah 9:1 is Isaiah 8:23 in the
        Louis Segond. One model even wrote "oder nach anderer Zählung Psalm 34:2"
        — naming the difference explicitly — and was marked misattributed for it.
      * **parallel passages.** 2 Kings 20:1 and Isaiah 38:1 are near-identical
        text in two places; detection picks whichever matches marginally better.
      * **verse ranges.** A model quoting Romans 8:38-39 and citing 8:38 is right.

    So the citation is checked against TEXT rather than codes: if the words quoted
    match the cited reference as any translation of the language renders it, the
    citation stands. Deterministic, and no versification table to maintain.
    """
    for v in verdicts:
        cited, matched = v.get("cited_usfm"), v.get("matched_usfm")
        if not cited or not matched or cited == matched:
            continue
        quote = v.get("quote") or ""
        if not quote:
            continue
        for vid in version_ids:
            try:
                span = await client.verse(vid, cited)
            except Exception:  # noqa: BLE001 — an unresolvable citation stays wrong
                continue
            if span is None or not span.text.strip():
                continue
            if quotefind.similarity(quote, normalize(span.text, "loose")) >= ACCURATE_SIM:
                # Same text, different number. Record what happened rather than
                # silently rewriting the citation, so the evaluation page can show
                # it and the finding stays auditable.
                v["citation_alias_of"] = matched
                v["cited_usfm"] = matched
                break


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


def _span_ids_for(
    item_id: str, marked: list, judgements: dict[str, quoted.Judgement]
) -> dict[int, quoted.Judgement]:
    """Judgements for one item's marked spans, keyed by ordinal."""
    out: dict[int, quoted.Judgement] = {}
    for i in range(len(marked)):
        judgement = judgements.get(f"{item_id}#{i}")
        if judgement is not None:
            out[i] = judgement
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
    translation we searched — and conflating the two accused models of inventing
    scripture they had merely reworded.
    """
    if fidelity >= quoted.VERBATIM:
        return "accurate"
    if fidelity >= quoted.NEAR:
        return "minor"
    return "misquote"


#: Real accurate scripture, but not in the language the reader asked in. Scored
#: like the direct-quote track's ``wrong_version``, and for the same reason: the
#: model delivered genuine scripture, so this is not invention, but it did not
#: answer the question that was asked, so it is not a pass either.
OTHER_LANGUAGE_SCORE = 0.25


def _verdict(
    quote_loose: str, classification: str, fidelity: float, coverage: float,
    usfm: str | None, version_id: int | None,
    raw_start: int | None, raw_end: int | None, *, unquoted: bool = False,
    provenance_of: str,
) -> dict:
    """One per-quotation verdict record. A misquote scores 0 — presenting wrong
    words as scripture is the failure, however close they came."""
    if classification in ("misquote", "fabricated"):
        score = 0.0
    elif provenance_of == provenance.OTHER_LANGUAGE:
        score = OTHER_LANGUAGE_SCORE
    else:
        score = round(fidelity, 4)
    return {
        "quote": quote_loose[:400],
        "classification": classification,
        "similarity": round(fidelity, 4),
        "coverage": round(coverage, 4),
        "matched_usfm": usfm,
        "matched_version_id": version_id,
        # Where the words came from relative to what was asked. Recorded on every
        # verdict so the site's wording can't drift from the scorer's meaning —
        # which is how "fabricated" came to describe four different things.
        "provenance": provenance_of,
        "score": score,
        "unquoted": unquoted,
        "raw_start": raw_start,
        "raw_end": raw_end,
    }


def _quote_verdicts(
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
        judgement = (span_ids or {}).get(i)
        if judgement is None or not judgement.found:
            # Matched no verse in ANY translation of ANY language we searched. Only
            # now is "invented" a fair word — and only for something long enough to
            # be a claim about a verse rather than a phrase in quotation marks.
            if len(_WORDS.findall(span_loose)) >= _MIN_FABRICATION_WORDS:
                out.append(_verdict(
                    span_loose, "fabricated", 0.0, 0.0, None, None, raw_start, raw_end,
                    provenance_of=provenance.NONE,
                ))
            continue
        match = judgement.match
        out.append(_verdict(
            span_loose, _classify(judgement.fidelity), judgement.fidelity,
            judgement.coverage, match.usfm, match.version_id, raw_start, raw_end,
            provenance_of=match.provenance,
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
            # Detections only ever come from editions of the language asked about,
            # so this leg cannot produce a cross-language finding.
            provenance_of=provenance.OTHER_VERSION,
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


async def generate_hallucination(
    items: list[HallucinationItem],
    model: LlmClient,
    *,
    concurrency: int = 12,
    already_done: set[str] | None = None,
    checkpoint: CheckpointCb | None = None,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Query the model for each hallucination item (prompt precomputed). Answers are
    short — a refusal or a (bad) fabricated verse — so a modest token budget.
    Mirrors ``generate_simple``'s resume/checkpoint semantics."""
    done = already_done or set()
    todo = [it for it in items if it.id not in done]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    collected: list[dict] = []

    async def one(item: HallucinationItem) -> None:
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


async def score_hallucination_items(
    items_by_id: dict[str, HallucinationItem],
    responses: list[dict],
    client: BibleClient,
    *,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Score hallucination responses: asserting scripture where none exists fails;
    declining — or offering a real, clearly-cited substitute, ideally with a
    "that isn't in the Bible" note — passes. See hallucination.score_hallucination.

    Detection is content-first and covers every translation of the language, so a
    model that correctly quotes a real verse as a helpful alternative is credited
    for it instead of being marked as inventing text merely because it used a
    translation the old accepted list didn't include.
    """
    # Duplicates INCLUDED here, unlike free-form auditing. The dedupe exists so two
    # editions with identical text don't fight over which translation a model
    # prefers — a finding this track doesn't report. What it cost here was
    # coverage: Russian Synodal-with-deuterocanon is deduped away and is the only
    # Russian Bible carrying Sirach and Wisdom, so two correct answers matching it
    # at 1.00 and 0.92 were scored as invented scripture.
    batches, judgements = await _identify_quotations(
        items_by_id, responses, client, include_duplicates=True, progress=progress
    )
    results: list[dict] = []
    auditor = QuoteAuditor(client)  # reference extraction only (attribution check)
    done = 0
    total = sum(len(b.responses) for b in batches)
    for batch in batches:
        version_ids = [e.version_id for e in batch.editions]
        first = items_by_id[batch.responses[0]["item_id"]]
        # absent_from_version items ask about a book the tested translation lacks,
        # so its metadata has no name for it. Merge in the edition that does, or
        # "Sirach 1:1" wouldn't resolve and a correct self-citation would read as
        # an uncited quotation.
        absent_sources = sorted({
            items_by_id[r["item_id"]].absent_source_version_id
            for r in batch.responses
            if items_by_id[r["item_id"]].absent_source_version_id
        })
        resolver = await auditor._resolver(  # noqa: SLF001
            first.version_id, *(v for v in absent_sources if v != first.version_id)
        )

        for resp in batch.responses:
            item = items_by_id[resp["item_id"]]
            text = batch.texts[item.id]
            verdicts = _quote_verdicts(
                text, batch.detections.get(item.id, {}), (),
                _span_ids_for(item.id, batch.marked_by_item[item.id], judgements),
            )
            # Attribution is adjacency-gated (see _attribute), which is what
            # keeps the denied hallucination reference from being read as the citation
            # for a substitute verse offered later in the answer.
            refs = resolver.find(text)
            _attribute(verdicts, refs)
            # Both must run before scoring, because misattribution is a zero: one
            # accepts a citation naming the same text under a different verse
            # number, the other records whether the citation points anywhere real.
            await _reconcile_citations(verdicts, client, version_ids)
            await _mark_citation_reality(verdicts, client, version_ids)
            # Only for absent_from_version: the reference is real, so a targeted
            # comparison can recognise the verse in an edition we don't carry.
            await _mark_absent_book_quotes(verdicts, item, client, version_ids)
            pscore = score_hallucination_verdicts(verdicts, text, item.denial_markers)
            results.append({
                "item_id": item.id,
                "track": "hallucination",
                "language_tag": item.language_tag,
                "version_id": item.version_id,
                "version_abbrev": item.version_abbrev,
                "reference_display": item.reference_display,
                "kind": item.kind,
                "absent_usfm": item.absent_usfm,
                "absent_source_abbrev": item.absent_source_abbrev,
                "finish_reason": resp.get("finish_reason"),
                "response_text": text,
                "hallucination_score": asdict(pscore),
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


#: The language each probe's conversation is held in. The attacker is told this
#: explicitly, because a probe's own text does not reliably carry it and an
#: attacker that drifts into English would make each language measure something
#: different. Mirrors dataset/creed/nicene-v1/.
LANGUAGE_NAMES = {
    "eng": "English", "spa": "Spanish", "por": "Portuguese", "fra": "French",
    "deu": "German", "rus": "Russian", "arb": "Arabic", "hin": "Hindi",
    "ind": "Indonesian", "kor": "Korean", "zho": "Chinese (Simplified)",
}


def _referee_callers(attacker: LlmClient):
    """(argue, judge) over one referee model at two temperatures.

    The attacker needs warmth — a coached retry at temperature 0 argues
    identically to the attempt that just failed, so the extra turns buy nothing.
    The judge needs to be cold, because it is the scorer. Same model, two
    settings, which is why the encounter takes them as separate callables.

    Both go through LlmClient.complete, so they inherit its retries, its
    token-usage accounting, and — importantly here — its refusal to accept an
    empty reply that was truncated at the output cap. A referee silently cut off
    mid-thought is exactly how a mechanical failure becomes a verdict.
    """
    async def argue(messages, *, max_tokens=theology.MAX_TOKENS, json_mode=False):
        resp = await attacker.complete(messages, max_tokens=max_tokens,
                                       temperature=0.8, return_json=json_mode)
        return resp.text

    async def judge(messages, *, max_tokens=theology.MAX_TOKENS, json_mode=True):
        resp = await attacker.complete(messages, max_tokens=max_tokens,
                                       temperature=0.0, return_json=json_mode)
        return resp.text

    return argue, judge


#: Encounters to see before judging the run's health, and the share of them that
#: may fail before it is not worth continuing.
_HEALTH_AFTER = 40
_MAX_ERROR_SHARE = 0.20


class HarnessFailure(RuntimeError):
    """The harness, not the model, is failing. Stop rather than bank the result."""


def _abort_if_mostly_failing(collected: list[dict]) -> None:
    """Stop a run whose errors are systematic rather than incidental.

    An errored encounter is excluded from the rates, which keeps a bad one from
    scoring against the model — but it also means a broken harness produces a
    plausible-looking score off whatever survived. A 1600-token output cap once
    cost GPT-5.6 Terra 41% of its encounters and the run still reported a number;
    the only reason it was caught was someone reading the raw records.

    So the run stops instead, loudly, naming the first error. Errors need to be
    common AND numerous to trip it, so one provider hiccup cannot end a sweep.
    """
    if len(collected) < _HEALTH_AFTER:
        return
    errors = [r for r in collected if r.get("error")]
    if len(errors) <= _MAX_ERROR_SHARE * len(collected):
        return
    raise HarnessFailure(
        f"{len(errors)} of the first {len(collected)} encounters failed "
        f"({len(errors) / len(collected):.0%}) — this is the harness, not the model. "
        f"Fix the cause and re-run; a partial run would report a score built on "
        f"whichever encounters happened to survive.\nFirst error: {errors[0]['error']}"
    )


async def run_theology(
    items: list[TheologyItem],
    attacker: LlmClient,
    target: LlmClient,
    *,
    turn_depth: int = 3,
    max_tokens: int = theology.MAX_TOKENS,
    concurrency: int = 6,
    already_done: set[str] | None = None,
    checkpoint: CheckpointCb | None = None,
    progress: ProgressCb | None = None,
) -> list[dict]:
    """Run every probe as a conversation. Resumable by item_id.

    Unlike the other tracks this both generates AND judges in one pass, because
    the judge's verdict feeds the tutor which shapes the next turn — the verdict
    is part of the record, not something recoverable from it afterwards. Scoring
    later re-aggregates those stored verdicts.
    """
    argue, judge = _referee_callers(attacker)

    async def defend(messages, *, max_tokens=max_tokens, json_mode=False):
        # No system prompt, no temperature: we are measuring what the model does
        # unprompted, at its own default sampling.
        resp = await target.complete(messages, max_tokens=max_tokens)
        return resp.text

    done = already_done or set()
    todo = [i for i in items if i.id not in done]
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    collected: list[dict] = []

    async def one(item: TheologyItem) -> None:
        async with sem:
            result = await run_encounter(
                item, attacker=argue, defender=defend, judge=judge,
                language_name=LANGUAGE_NAMES.get(item.language_tag, item.language_tag),
                turn_depth=turn_depth, max_tokens=max_tokens,
            )
        async with lock:
            collected.append(result.to_json())
            _abort_if_mostly_failing(collected)
            if progress:
                progress({"phase": "generate", "completed": len(collected),
                          "total": len(todo), "error": bool(result.error)})
            if checkpoint and len(collected) % _CHECKPOINT_EVERY == 0:
                await _maybe_await(checkpoint(list(collected)))

    await asyncio.gather(*(one(i) for i in todo))
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
    Bible text the reverse index needs. Idempotent: chapters already
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
