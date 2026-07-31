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

  1. **Propose** — an inverted character-n-gram index over one translation's whole
     text nominates verses sharing enough n-grams with the text to be worth a
     proper comparison. Recall is what matters here; see ``VersionIndex``.
  2. **Confirm** — character-level similarity against the proposed verses, using
     best-window alignment so a faithful *partial* quotation still matches.

This module is the **mechanics** of searching: index one edition, find the best
verse in it. What a hit MEANS — which edition it came from relative to the one
asked for, and whether the words were faithful — belongs to :mod:`provenance` and
:mod:`quoted`, which every dimension shares. Keeping the search separate from the
judgement is what stops three dimensions from inventing three vocabularies again.

Scale note: a language can have ~90 translations, so callers iterate translations
in the OUTER loop — each is loaded, indexed, matched against every span, then
dropped. Peak memory stays at one index regardless of how many are covered.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .normalize import normalize

# Stage 1 is a SPEED optimization, not a judgement — and that distinction is the
# whole design. Every verse it declines to propose is silently decided "not this
# verse", with no similarity ever computed, so its bar must be set for recall and
# precision must come entirely from stage 2.
#
# It was previously set as though it were a judgement, and the cost was large.
# Word 4-grams needing 2 shared grams means a verse must share FIVE consecutive
# identical words to be considered at all, so two scattered one-character
# differences destroy four grams each and disqualify a verse that is otherwise
# word-for-word. Real examples, both graded "invented scripture":
#
#   * Russian 1 Peter 5:7 — the edition writes "возложи́те" with a stress mark and
#     "печется" without the diaeresis; the model wrote both plainly. Similarity
#     0.972, shared 4-grams 1, and so never considered.
#   * Korean 1 Peter 5:7 — agglutination ("맡기라" vs "맡겨 버리라") changes whole
#     tokens. Similarity 0.806, shared 4-grams 1.
#
# Character n-grams are the fix, and they are also a simplification: one
# tokenisation for every script instead of a spaced/unspaced fork that had to
# guess which kind of text it was looking at. A one-character difference costs at
# most N grams rather than N whole words, morphology no longer wipes out a token,
# and CJK needs no special case because it never had word tokens to begin with.
NGRAM_CHARS = 6

# How much of the SHORTER side's n-grams must be shared. Relative, not absolute,
# because the two questions asked of this index have query lengths that differ by
# a factor of ~25 and one absolute floor cannot serve both:
#
#   * "what verse is this span" — query and verse are the same length, so a real
#     match shares most of both sides' grams;
#   * "does this verse appear anywhere in this answer" — the verse is a small
#     fraction of the query, so a real match shares nearly all of the VERSE's
#     grams and only a few percent of the query's.
#
# Taking the shorter side adapts to both, which is why one rule now replaces the
# previous pair of absolute constants.
#
# Measured against brute force over every verse of every edition, on the spans ten
# published runs had graded "invented": the old word-4-gram rule found the verse
# 13% of the time, this finds it 81%, while still proposing only ~3% of a
# translation's verses for a whole answer. The remaining 19% are quotations
# reworded far enough that they share little text with any verse — no n-gram
# proposal can reach those, and they land as "misquote" rather than "invented",
# which is the smaller error of the two.
MIN_SHARED_FRACTION = 0.10

# A short verse must be matched almost in full to count (see VersionIndex.present).
# This is quoted.VERBATIM, written out because quoted imports this module and the
# reverse would be a cycle — the one place the ladder is duplicated. A test pins
# the two together (test_quoted.py) so they cannot drift apart silently.
SHORT_VERSE_WHOLE_FLOOR = 0.98
# Verses below this length are the ones that rule applies to: "the fear of the
# LORD" aligns perfectly inside dozens of longer verses, so a window match proves
# nothing about it.
SHORT_VERSE_CHARS = 40


def ngrams(loose_text: str) -> set[str]:
    """N-gram set used for candidate proposal. Input must be loose-normalized.

    Character n-grams, for every script. Word n-grams were a worse fit even for
    the scripts that have words: a single differing character costs N whole
    tokens rather than N grams, so a stress mark on one Russian word or a Korean
    verb ending disqualified verses that were otherwise word-for-word. Dropping
    the spaced/unspaced fork also removes a guess about what kind of text we are
    looking at — CJK needed the character path anyway, and now it is not a
    special case.
    """
    s = loose_text.replace(" ", "")
    n = NGRAM_CHARS
    return {s[i : i + n] for i in range(max(0, len(s) - n + 1))}


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


def fidelity_and_coverage(span_loose: str, verse_loose: str) -> tuple[float, float]:
    """How faithful the quoted words are, and how much of the verse arrived.

    Two numbers because they answer different questions and a scorer needs both:

    fidelity — are the words right? Best alignment of the span within the verse,
    so a faithful *fragment* reads as faithful (1.0) rather than as a partly wrong
    whole verse. Quoting half a verse correctly is a correct quotation of that
    half.

    coverage — how much of the verse was actually delivered, capped at 1.0 so
    quoting across a verse boundary is not credited above a full verse.

    Defined here, next to the similarity it is built from, and re-exported by
    :mod:`quoted` so every dimension measures fidelity the same way.
    """
    if not span_loose or not verse_loose:
        return 0.0, 0.0
    return similarity(span_loose, verse_loose), min(
        1.0, len(span_loose) / len(verse_loose)
    )


@dataclass(frozen=True)
class Span:
    """A stretch of one response that might be scripture."""

    key: str          # unique across the batch: f"{item_id}#{n}"
    item_id: str
    text: str
    quoted: bool      # inside quote marks / a blockquote (vs. found unmarked)


class VersionIndex:
    """Inverted n-gram index over the whole text of ONE translation.

    Stage 1 of identification, and only stage 1: it nominates verses worth
    comparing properly. It is a speed optimization, so its bar is set for recall
    — a verse it declines to nominate is silently judged "not this verse", with
    no similarity ever computed, and that silence is indistinguishable from a
    model having invented the text. Precision belongs to stage 2.
    """

    def __init__(self, version_id: int, verses: dict[str, str]):
        self.version_id = version_id
        self.verses: dict[str, str] = {u: normalize(t, "loose") for u, t in verses.items()}
        self._index: dict[str, list[str]] = defaultdict(list)
        #: n-grams per verse, so the proposal floor can scale to the shorter side.
        self._sizes: dict[str, int] = {}
        for usfm, loose in self.verses.items():
            grams = ngrams(loose)
            self._sizes[usfm] = len(grams)
            for g in grams:
                self._index[g].append(usfm)

    def propose(self, loose_text: str) -> list[str]:
        """Verses sharing enough n-grams with the text to be worth confirming.

        The bar is a fraction of the SHORTER side's grams, which is what lets one
        rule serve both a short span and a whole answer (see
        ``MIN_SHARED_FRACTION``). It also handles a very short quotation without a
        special case: "You shall not murder" offers few grams, so few are
        demanded, and Exodus 20:13 quoted perfectly is findable. Precision is not
        lost there — a match against a short verse must additionally be
        near-complete (see ``present``), so a stock phrase sitting inside a long
        verse still fails confirmation.
        """
        grams = ngrams(loose_text)
        if not grams:
            return []
        hits: dict[str, int] = defaultdict(int)
        for g in grams:
            for usfm in self._index.get(g, ()):
                hits[usfm] += 1
        return [
            u
            for u, n in hits.items()
            if n >= max(1, MIN_SHARED_FRACTION * min(len(grams), self._sizes[u]))
        ]

    def _is_short(self, loose_text: str) -> bool:
        """True when a window match against this text proves little, so it must be
        confirmed against the whole string instead."""
        return len(loose_text) < SHORT_VERSE_CHARS

    def best(self, loose_text: str) -> tuple[str | None, float]:
        """Best (usfm, similarity) for a span within this translation."""
        best_usfm, best_sim = None, 0.0
        for usfm in self.propose(loose_text):
            sim = similarity(loose_text, self.verses[usfm])
            if sim > best_sim:
                best_usfm, best_sim = usfm, sim
        return best_usfm, best_sim

    def present(
        self, loose_response: str, *, floor: float
    ) -> dict[str, tuple[float, int, int, float]]:
        """Verses of this translation that appear anywhere in a whole response.

        Verse-driven rather than window-driven, so an unmarked quotation is found
        without guessing where it starts. Returns {usfm: (similarity, start, end,
        whole_ratio)} with offsets into the loose-normalized response, so the
        caller can tell whether a detection sits inside a span the model
        explicitly quoted.

        ``floor`` is the caller's: how similar counts as "this verse is here" is a
        judgement, and every dimension takes it from the same place
        (``quoted.RECOGNISABLE``) rather than each keeping its own number.
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
                # near-complete match counts. This is what keeps the recall-first
                # proposal bar above from turning stock phrases into quotations.
                continue
            if sim >= floor:
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


async def scan_editions(
    client,
    editions,
    texts: dict[str, str],
    spans: list[Span],
    *,
    floor: float,
    on_edition,
    progress=None,
) -> dict[str, dict[str, Detection]]:
    """Walk every edition once, feeding both passes from the same index.

    Two questions are asked of each index, and each is wrong for the other's job:

      * **verse-driven** (``present``) — "does this verse appear anywhere in the
        answer", the only way to find scripture the model never marked as a
        quotation;
      * **span-driven** (``best``) — "what verse is *this* stretch of text", the
        right question whenever the model gave us the boundaries with quote marks.

    Asking them in separate passes would build every index twice — around 90 of
    them for English — so they share one walk here. Editions are the OUTER loop
    and each index is released before the next is built, so peak memory is one
    index however many editions are covered.

    The span answers go to ``on_edition(edition, index)``, a callback, because
    choosing between competing editions needs to know what a match MEANS — which
    is provenance's job, not this module's (see :mod:`quoted`). The verse-driven
    detections are returned directly since they are per-verse, not per-span.
    """
    loose_texts = {k: normalize(t, "loose") for k, t in texts.items()}
    detections: dict[str, dict[str, Detection]] = {k: {} for k in texts}

    for n, edition in enumerate(editions, 1):
        vid = edition.version_id
        verses = await load_verses(client, vid)
        if not verses:
            continue
        index = VersionIndex(vid, verses)
        for key, text in loose_texts.items():
            if not text:
                continue
            for usfm, (sim, start, end, whole) in index.present(text, floor=floor).items():
                cur = detections[key].get(usfm)
                if cur is None or sim > cur.similarity:
                    detections[key][usfm] = Detection(
                        usfm, vid, sim, start, end,
                        verse_loose=index.verses[usfm], whole_ratio=whole,
                    )
        if spans:
            on_edition(edition, index)
        del index, verses
        if progress:
            progress({"phase": "identify", "completed": n, "total": len(editions)})
    return detections
