"""Content-first scripture detection: identify what verse a span of text IS.

The earlier auditor decided which verse a quotation was by looking at the
reference printed next to it, then compared the two. That conflates two
different questions and fails at both:

  * a nearby reference can belong to a *different* quotation, so a faithful
    quote gets marked as a mismatch (the adjacency window picks up the previous
    sentence's citation); and
  * a faithful quote from a translation outside a small hand-picked list looks
    like a misquote, because it was never compared against the translation the
    model actually used.

Here the order is inverted. A span is identified by its **content**, against
**every** translation the benchmark covers for that language, with no reference
consulted. Whether the model's own citation agrees with what it actually quoted
becomes a separate, secondary judgement.

Identification is two-stage, both stages deterministic:

  1. **Propose** — an inverted n-gram index over one translation's whole text
     nominates verses sharing enough n-grams with the text. Word 4-grams for
     spaced scripts; character 8-grams for unspaced ones (CJK, Thai, Khmer, Lao,
     Myanmar), where word tokens don't exist. Thresholds were tuned for full
     recall at ~0.3% of verses proposed.
  2. **Confirm** — character-level similarity against the proposed verses, using
     best-window alignment so a faithful *partial* quotation still matches.

Scale note: a language can have ~90 translations, and one index is ~100MB, so
``identify_all`` iterates translations in the OUTER loop — each is loaded,
indexed, matched against every span, then dropped. Peak memory stays at one
index regardless of how many translations are covered.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import regex

from .normalize import normalize

# Tuned on real model output: full recall of known quotations while proposing
# ~0.3% of a translation's verses. Word n-grams break on substituted words, so
# the shared-gram bar is deliberately low — precision comes from stage 2.
NGRAM_WORDS = 4
MIN_SHARED_WORDS = 2
NGRAM_CHARS = 8
MIN_SHARED_CHARS = 8

# Below this we make no claim about which verse a span is.
IDENTIFY_FLOOR = 0.75

# A short verse must be matched almost in full to count (see VersionIndex.present).
# Same bar the auditor uses for "accurate", kept here to avoid a circular import.
SHORT_VERSE_WHOLE_FLOOR = 0.98

_WORD = re.compile(r"\w+", re.UNICODE)
_UNSPACED = regex.compile(
    r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Thai}\p{Khmer}\p{Lao}\p{Myanmar}]"
)


def is_unspaced(text: str) -> bool:
    """True for scripts written without word spaces, which need char n-grams."""
    sample = text[:400]
    if not sample:
        return False
    return len(_UNSPACED.findall(sample)) / len(sample) > 0.3


def ngrams(loose_text: str, *, unspaced: bool) -> set[str]:
    """N-gram set used for candidate proposal. Input must be loose-normalized."""
    if unspaced:
        s = loose_text.replace(" ", "")
        n = NGRAM_CHARS
        return {s[i : i + n] for i in range(max(0, len(s) - n + 1))}
    w = _WORD.findall(loose_text)
    n = NGRAM_WORDS
    return {" ".join(w[i : i + n]) for i in range(max(0, len(w) - n + 1))}


def similarity(quote_loose: str, verse_loose: str) -> float:
    """How well a span matches a verse, tolerant of partial quotation.

    The better of two readings, because either can be the fairer one:

      * whole-string similarity, right when the span and the verse are the same
        stretch of text (small wording differences shouldn't be amplified); and
      * best-window similarity, right when the span is a faithful *fragment* of
        the verse, or runs past its end — quoting half a verse correctly is a
        correct quotation of that half, not a half-wrong quotation.

    Taking the max avoids penalising a near-equal-length quote just because
    window alignment happened to find a worse framing than the whole comparison.
    """
    from rapidfuzz import fuzz

    if not quote_loose or not verse_loose:
        return 0.0
    if quote_loose == verse_loose:
        return 1.0
    return max(
        fuzz.ratio(quote_loose, verse_loose),
        fuzz.partial_ratio(quote_loose, verse_loose),
    ) / 100.0


@dataclass(frozen=True)
class Span:
    """A stretch of one response that might be scripture."""

    key: str          # unique across the batch: f"{item_id}#{n}"
    item_id: str
    text: str
    quoted: bool      # inside quote marks / a blockquote (vs. found unmarked)


@dataclass
class Identification:
    """The best verse identification for one span, across all translations.

    Span-driven: the span's own words are matched against the index, so nothing
    depends on guessing where in a response the quotation sits. That guess is what
    made a short fragment of a long verse undetectable inside a long answer —
    "and wine to gladden the heart of man" is Psalm 104:15 verbatim in the ESV, and
    was recorded as invented scripture.
    """

    usfm: str
    version_id: int
    similarity: float
    verse_loose: str = ""

    def classification(self, *, accurate: float, minor: float) -> str:
        if self.similarity >= accurate:
            return "accurate"
        if self.similarity >= minor:
            return "minor"
        return "partial"

    def fidelity_and_coverage(self, span_loose: str) -> tuple[float, float]:
        """(fidelity, coverage) of the span against the verse it was identified as.
        Same meaning as ``Detection.fidelity_and_coverage``."""
        if not span_loose or not self.verse_loose:
            return 0.0, 0.0
        return similarity(span_loose, self.verse_loose), min(
            1.0, len(span_loose) / len(self.verse_loose)
        )


class VersionIndex:
    """Inverted n-gram index over the whole text of ONE translation."""

    def __init__(self, version_id: int, verses: dict[str, str], *, unspaced: bool):
        self.version_id = version_id
        self.unspaced = unspaced
        self.verses: dict[str, str] = {u: normalize(t, "loose") for u, t in verses.items()}
        self._index: dict[str, list[str]] = defaultdict(list)
        for usfm, loose in self.verses.items():
            for g in ngrams(loose, unspaced=unspaced):
                self._index[g].append(usfm)

    def propose(self, loose_text: str) -> list[str]:
        """Verses sharing enough n-grams with the text to be worth confirming.

        A short span can't meet the usual shared-gram bar — "You shall not murder"
        is four words, so it yields exactly one word 4-gram and could never reach
        two. That made every verse under five words *unfindable*, and Exodus 20:13
        quoted perfectly was recorded as invented scripture. The bar therefore
        drops to what the span can actually offer. Precision is not lost: a span
        this short is only credited if it matches nearly the whole verse (see
        ``present``), so a stock phrase that happens to sit inside a long verse
        still fails confirmation.
        """
        grams = ngrams(loose_text, unspaced=self.unspaced)
        hits: dict[str, int] = defaultdict(int)
        for g in grams:
            for usfm in self._index.get(g, ()):
                hits[usfm] += 1
        floor = MIN_SHARED_CHARS if self.unspaced else MIN_SHARED_WORDS
        floor = max(1, min(floor, len(grams)))
        return [u for u, n in hits.items() if n >= floor]

    def _is_short(self, loose_text: str) -> bool:
        """True when the span is too short to clear the normal shared-gram bar, so
        its match must be confirmed against the whole verse rather than a window."""
        return len(ngrams(loose_text, unspaced=self.unspaced)) < (
            MIN_SHARED_CHARS if self.unspaced else MIN_SHARED_WORDS
        )

    def best(self, loose_text: str) -> tuple[str | None, float]:
        """Best (usfm, similarity) for a span within this translation."""
        best_usfm, best_sim = None, 0.0
        for usfm in self.propose(loose_text):
            sim = similarity(loose_text, self.verses[usfm])
            if sim > best_sim:
                best_usfm, best_sim = usfm, sim
        return best_usfm, best_sim

    def present(self, loose_response: str) -> dict[str, tuple[float, int, int, float]]:
        """Verses of this translation that appear anywhere in a whole response.

        Verse-driven rather than window-driven, so an unmarked quotation is found
        without guessing where it starts. Returns {usfm: (similarity, start, end)}
        with offsets into the loose-normalized response, so the caller can tell
        whether a detection sits inside a span the model explicitly quoted.
        """
        from rapidfuzz import fuzz

        out: dict[str, tuple[float, int, int, float]] = {}
        for usfm in self.propose(loose_response):
            vloose = self.verses[usfm]
            aln = fuzz.partial_ratio_alignment(vloose, loose_response)
            if aln is None:
                continue
            start, end = aln.dest_start, aln.dest_end
            window = loose_response[start:end]
            sim = max(similarity(vloose, window), similarity(vloose, loose_response))
            whole = fuzz.ratio(vloose, window) / 100.0
            if self._is_short(vloose) and whole < SHORT_VERSE_WHOLE_FLOOR:
                # The VERSE is short, so a window match proves little: "the fear of
                # the LORD" aligns perfectly inside dozens of verses. Only a
                # near-complete match counts. This is what keeps the lowered
                # proposal bar above from turning stock phrases into quotations.
                continue
            if sim >= IDENTIFY_FLOOR:
                out[usfm] = (sim, start, end, whole)
        return out


async def load_verses(client, version_id: int) -> dict[str, str]:
    """{usfm: text} for a translation's whole text, from the cache.

    Every book the edition carries. Restricting this to a fixed canon made
    deuterocanonical and Orthodox books invisible to detection, so quoting them
    accurately looked like invention.
    """
    meta = await client.version(version_id)
    out: dict[str, str] = {}
    for b in meta.get("books", []):
        for c in b.get("chapters", []):
            cu = c.get("usfm", "")
            if not c.get("canonical", True) or "." not in cu or "INTRO" in cu:
                continue
            try:
                out.update(await client.chapter_verses(version_id, cu))
            except Exception:  # noqa: BLE001 — a missing chapter shouldn't sink the run
                continue
    return out


@dataclass
class Detection:
    """A verse found in a response, with where it sits in the response.

    ``similarity`` is verse-as-needle: how much of the VERSE is present in the
    response. That conflates two things a scorer needs to keep apart — whether
    the quoted words are faithful, and how much of the verse was delivered — so
    ``verse_loose`` is carried along, letting the caller measure fidelity against
    the model's own quoted span and scale it by coverage.
    """

    usfm: str
    version_id: int
    similarity: float
    start: int
    end: int
    verse_loose: str = ""
    # Whole-string similarity of the verse to the matched window, with NO
    # best-window allowance. Required for spans whose boundaries we inferred
    # rather than read off quotation marks: partial_ratio returns 1.0 whenever the
    # window is merely a substring of the verse, so a common phrase ("there is no
    # …") that happens to sit inside a verse would otherwise look verbatim.
    whole_ratio: float = 0.0

    def fidelity_and_coverage(self, span_loose: str) -> tuple[float, float]:
        """(fidelity, coverage) of a marked quotation against this verse.

        fidelity — are the quoted words right? Best alignment of the span inside
        the verse, so a faithful fragment reads as faithful (1.0), not as a
        partly-wrong whole verse.
        coverage — how much of the verse was actually delivered. Capped at 1.0, so
        quoting across a verse boundary isn't credited above a full verse.
        """
        if not span_loose or not self.verse_loose:
            return 0.0, 0.0
        fidelity = similarity(span_loose, self.verse_loose)
        coverage = min(1.0, len(span_loose) / len(self.verse_loose))
        return fidelity, coverage


async def scan_responses(
    client,
    version_ids: list[int],
    texts: dict[str, str],
    *,
    unspaced: bool = False,
    progress=None,
) -> dict[str, dict[str, Detection]]:
    """Every verse detectable in each response, across every translation.

    One pass covers quoted and unquoted scripture alike, because detection is
    verse-driven. Translations are the outer loop so peak memory is one index.

    Returns {response_key: {usfm: best Detection}} — best meaning the translation
    the text most closely matches, which is how the model's preferred translation
    is observed rather than assumed.
    """
    loose = {k: normalize(t, "loose") for k, t in texts.items()}
    out: dict[str, dict[str, Detection]] = {k: {} for k in texts}
    for n, vid in enumerate(version_ids, 1):
        verses = await load_verses(client, vid)
        if not verses:
            continue
        index = VersionIndex(vid, verses, unspaced=unspaced)
        for key, text in loose.items():
            if not text:
                continue
            for usfm, (sim, start, end, whole) in index.present(text).items():
                cur = out[key].get(usfm)
                if cur is None or sim > cur.similarity:
                    out[key][usfm] = Detection(
                        usfm, vid, sim, start, end,
                        verse_loose=index.verses[usfm], whole_ratio=whole,
                    )
        del index, verses
        if progress:
            progress({"phase": "identify", "completed": n, "total": len(version_ids)})
    return out


async def scan_and_identify(
    client,
    version_ids: list[int],
    texts: dict[str, str],
    spans: list[Span],
    *,
    unspaced: bool = False,
    progress=None,
) -> tuple[dict[str, dict[str, Detection]], dict[str, Identification]]:
    """Both passes over one set of indexes: verse-driven and span-driven.

    They answer different questions and each is wrong for the other's job:

      * **verse-driven** (``scan_responses``) asks "does this verse appear anywhere
        in the answer", which is the only way to find scripture the model never
        marked as a quotation;
      * **span-driven** (``identify_all``) asks "what verse is *this* stretch of
        text", which is the right question whenever the model told us the
        boundaries by putting them in quotation marks.

    Running them separately would build every translation's index twice — around
    90 indexes for English — so they share one pass here.
    """
    loose_texts = {k: normalize(t, "loose") for k, t in texts.items()}
    loose_spans = {s.key: normalize(s.text, "loose") for s in spans}
    detections: dict[str, dict[str, Detection]] = {k: {} for k in texts}
    best: dict[str, Identification] = {}

    for n, vid in enumerate(version_ids, 1):
        verses = await load_verses(client, vid)
        if not verses:
            continue
        index = VersionIndex(vid, verses, unspaced=unspaced)
        for key, text in loose_texts.items():
            if not text:
                continue
            for usfm, (sim, start, end, whole) in index.present(text).items():
                cur = detections[key].get(usfm)
                if cur is None or sim > cur.similarity:
                    detections[key][usfm] = Detection(
                        usfm, vid, sim, start, end,
                        verse_loose=index.verses[usfm], whole_ratio=whole,
                    )
        for s in spans:
            usfm, sim = index.best(loose_spans[s.key])
            if usfm and sim >= IDENTIFY_FLOOR:
                cur = best.get(s.key)
                if cur is None or sim > cur.similarity:
                    best[s.key] = Identification(
                        usfm=usfm, version_id=vid, similarity=sim,
                        verse_loose=index.verses[usfm],
                    )
        del index, verses
        if progress:
            progress({"phase": "identify", "completed": n, "total": len(version_ids)})
    return detections, best


async def identify_all(
    client,
    version_ids: list[int],
    spans: list[Span],
    *,
    unspaced: bool = False,
    progress=None,
) -> dict[str, Identification]:
    """Identify every span against every translation, one index at a time.

    Translations are the outer loop on purpose: each is loaded, indexed, matched
    against all spans, then released, so peak memory is one index no matter how
    many translations a language has.
    """
    loose = {s.key: normalize(s.text, "loose") for s in spans}
    best: dict[str, Identification] = {}
    for n, vid in enumerate(version_ids, 1):
        verses = await load_verses(client, vid)
        if not verses:
            continue
        index = VersionIndex(vid, verses, unspaced=unspaced)
        for s in spans:
            usfm, sim = index.best(loose[s.key])
            if usfm and sim >= IDENTIFY_FLOOR:
                cur = best.get(s.key)
                if cur is None or sim > cur.similarity:
                    best[s.key] = Identification(usfm=usfm, version_id=vid, similarity=sim)
        del index, verses
        if progress:
            progress({"phase": "identify", "completed": n, "total": len(version_ids)})
    return best
