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
from .usfm import CANON_ORDER

# Tuned on real model output: full recall of known quotations while proposing
# ~0.3% of a translation's verses. Word n-grams break on substituted words, so
# the shared-gram bar is deliberately low — precision comes from stage 2.
NGRAM_WORDS = 4
MIN_SHARED_WORDS = 2
NGRAM_CHARS = 8
MIN_SHARED_CHARS = 8

# Below this we make no claim about which verse a span is.
IDENTIFY_FLOOR = 0.75

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
    """The best verse identification for one span, across all translations."""

    usfm: str
    version_id: int
    similarity: float

    def classification(self, *, accurate: float, minor: float) -> str:
        if self.similarity >= accurate:
            return "accurate"
        if self.similarity >= minor:
            return "minor"
        return "partial"


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
        """Verses sharing enough n-grams with the text to be worth confirming."""
        hits: dict[str, int] = defaultdict(int)
        for g in ngrams(loose_text, unspaced=self.unspaced):
            for usfm in self._index.get(g, ()):
                hits[usfm] += 1
        floor = MIN_SHARED_CHARS if self.unspaced else MIN_SHARED_WORDS
        return [u for u, n in hits.items() if n >= floor]

    def best(self, loose_text: str) -> tuple[str | None, float]:
        """Best (usfm, similarity) for a span within this translation."""
        best_usfm, best_sim = None, 0.0
        for usfm in self.propose(loose_text):
            sim = similarity(loose_text, self.verses[usfm])
            if sim > best_sim:
                best_usfm, best_sim = usfm, sim
        return best_usfm, best_sim

    def present(self, loose_response: str) -> dict[str, float]:
        """Verses of this translation that appear anywhere in a whole response.

        Verse-driven rather than window-driven, so an unmarked quotation is found
        without guessing where it starts. Returns {usfm: similarity}.
        """
        out: dict[str, float] = {}
        for usfm in self.propose(loose_response):
            vloose = self.verses[usfm]
            sim = similarity(vloose, loose_response)
            if sim >= IDENTIFY_FLOOR:
                out[usfm] = sim
        return out


async def load_verses(client, version_id: int) -> dict[str, str]:
    """{usfm: text} for a translation's whole canonical text, from the cache."""
    meta = await client.version(version_id)
    out: dict[str, str] = {}
    for b in meta.get("books", []):
        if b.get("usfm") not in CANON_ORDER:
            continue
        for c in b.get("chapters", []):
            cu = c.get("usfm", "")
            if not c.get("canonical", True) or "." not in cu or "INTRO" in cu:
                continue
            try:
                out.update(await client.chapter_verses(version_id, cu))
            except Exception:  # noqa: BLE001 — a missing chapter shouldn't sink the run
                continue
    return out


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
