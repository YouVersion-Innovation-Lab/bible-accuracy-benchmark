"""Deterministic quote auditor — shared by the topical track and the
adversarial judge.

Given a free-form model response, find every span the model presents as a
scripture quotation and decide, WITHOUT any LLM, whether it is faithful:

1. Extract quoted spans (paired quote glyphs / markdown blockquotes) long
   enough to be a real quote.
2. Extract Bible references, using the response language's own localized book
   names (built from version.json) plus English names.
3. Verify each quote:
   - against an adjacent/same-sentence reference (fetch that verse, compare);
   - else against any reference cited elsewhere in the response;
   - else against an in-memory reverse index of the candidate version's whole
     text (built lazily, in memory only — the Bible API has no search endpoint).
   A quote matching a real verse (loose similarity >= ACCURATE_SIM) is
   accurate; a quote presented as scripture that matches nothing is fabricated;
   a cited reference that doesn't resolve is a fabricated reference.

Ported and generalized from genesis-phase-2 strand_4 flagger.py /
reference_extractor.py (English-only, BibleLookup-backed) onto the async
BibleClient and multi-language book-name resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

import regex

from .normalize import normalize
from .usfm import BOOK_NAME_TO_USFM, CANON_ORDER

ACCURATE_SIM = 0.98      # loose-normalized similarity to count a quote accurate
MINOR_SIM = 0.90         # accurate-with-minor-errors band
LOCATE_SIM = 0.60        # reverse index located the verse, wording may differ
_MIN_QUOTE_WORDS = 4     # for spaced scripts
_MIN_QUOTE_CHARS = 12    # for unspaced scripts
_ADJ_CHARS = 250

_UNSPACED = regex.compile(r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Thai}\p{Khmer}\p{Lao}\p{Myanmar}]")
_QUOTE_PAIRS = [('"', '"'), ("“", "”"), ("«", "»"), ("「", "」"), ("『", "』")]
_CLOSING_QUOTES = "\"'“”‘’»」』"
_SENTENCE_BREAK_RE = re.compile(
    r"[.!?။።۔][" + _CLOSING_QUOTES + r"]?(?:\s*\n|\s+)|\n\s*\n"
)


class VerseProvider(Protocol):
    async def verse(self, version_id: int, usfm: str): ...
    async def chapter_verses(self, version_id: int, chapter_usfm: str) -> dict[str, str]: ...
    async def version(self, version_id: int) -> dict: ...


@dataclass
class QuoteSpan:
    text: str
    start: int
    end: int


@dataclass
class RefSpan:
    usfm: str          # resolved single-verse or first-verse USFM
    start: int
    end: int
    resolved: bool


@dataclass
class QuoteVerdict:
    quote: str
    classification: str      # accurate | minor | mismatch | misattributed |
    #                          fabricated_ref | fabricated | unverifiable
    similarity: float
    matched_usfm: str | None
    cited_usfm: str | None
    score: float             # 1.0 accurate, graded for minor, else 0.0
    matched_version_id: int | None = None  # which version the quote matched
    unquoted: bool = False   # detected without quotation marks (near-verbatim)


@dataclass
class AuditResult:
    verdicts: list[QuoteVerdict] = field(default_factory=list)
    cited_refs: list[str] = field(default_factory=list)
    fabricated_refs: list[str] = field(default_factory=list)

    @property
    def verifiable(self) -> list[QuoteVerdict]:
        return [v for v in self.verdicts if v.classification != "unverifiable"]


def _qsim(a: str, b: str) -> float:
    """Loose-normalized similarity; a quote that is a substring of the verse
    (partial quotation) counts as a full match."""
    from rapidfuzz.distance import Levenshtein

    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return max(0.0, 1.0 - Levenshtein.distance(a, b) / max(len(a), len(b)))


def _is_unspaced(text: str) -> bool:
    sample = text[:200]
    return bool(sample) and len(_UNSPACED.findall(sample)) / len(sample) > 0.3


def _long_enough(inner: str) -> bool:
    if _is_unspaced(inner):
        return len(inner.strip()) >= _MIN_QUOTE_CHARS
    return len(inner.split()) >= _MIN_QUOTE_WORDS


def _in_block_quote_line(text: str, pos: int) -> bool:
    line_start = text.rfind("\n", 0, pos) + 1
    return text[line_start:pos].lstrip().startswith(">")


def extract_quotes(text: str) -> list[QuoteSpan]:
    """Paired-delimiter quote spans, plus markdown blockquote paragraphs.

    Blockquotes count as presented quotations too (a model rendering a verse
    as `> …` is claiming it as scripture)."""
    out: list[QuoteSpan] = []
    for open_q, close_q in _QUOTE_PAIRS:
        idx = 0
        while idx < len(text):
            i = text.find(open_q, idx)
            if i == -1:
                break
            j = text.find(close_q, i + 1)
            if j == -1:
                break
            inner = text[i + 1 : j]
            if "\n" not in inner and _long_enough(inner) and not _in_block_quote_line(text, i):
                out.append(QuoteSpan(inner, i, j + 1))
            idx = j + 1
    # Markdown blockquote lines → one span per contiguous block.
    for m in re.finditer(r"(?:^[ \t]*>[^\n]*\n?)+", text, re.MULTILINE):
        block = re.sub(r"(?m)^[ \t]*>[ \t]?", "", m.group(0)).strip()
        block = re.sub(r"\s+", " ", block)
        if _long_enough(block):
            out.append(QuoteSpan(block, m.start(), m.end()))
    out.sort(key=lambda q: q.start)
    deduped, last_end = [], -1
    for q in out:
        if q.start >= last_end:
            deduped.append(q)
            last_end = q.end
    return deduped


def _sentence_spans(text: str) -> list[QuoteSpan]:
    """Split text into sentence spans long enough to be a verse. Used to catch
    scripture a model recited WITHOUT quotation marks."""
    out: list[QuoteSpan] = []
    start = 0
    pieces: list[tuple[int, int]] = []
    for m in _SENTENCE_BREAK_RE.finditer(text):
        pieces.append((start, m.start()))
        start = m.end()
    pieces.append((start, len(text)))
    for lo, hi in pieces:
        seg = text[lo:hi]
        inner = seg.strip()
        if inner and _long_enough(inner):
            lead = len(seg) - len(seg.lstrip())
            out.append(QuoteSpan(inner, lo + lead, lo + lead + len(inner)))
    return out


class BookNameResolver:
    """Maps book names (localized + English) to USFM for one version.

    Built from version.json so references written in the response's language
    ("Juan 3:16", "यूहन्ना 3:16") resolve, not just English ones."""

    def __init__(self, names_to_usfm: dict[str, str]):
        self._map = names_to_usfm
        # Longest names first so "Song of Songs" wins over "Song".
        alternation = "|".join(
            re.escape(n) for n in sorted(names_to_usfm, key=len, reverse=True)
        )
        # <book> <chapter><sep><verse>[range]; sep ':' or '.' (some locales).
        self._pattern = regex.compile(
            r"(?<![\p{L}\p{N}])(" + alternation + r")[\s ]*"
            r"(\d{1,3})[:.∶](\d{1,3})(?:\s*[‒-―\-]\s*\d{1,3})?",
            regex.UNICODE,
        )

    @classmethod
    async def build(cls, provider: VerseProvider, version_id: int) -> BookNameResolver:
        names = dict(BOOK_NAME_TO_USFM)  # English always available
        try:
            meta = await provider.version(version_id)
        except Exception:  # noqa: BLE001
            meta = {}
        for b in meta.get("books", []):
            usfm = b.get("usfm")
            if usfm not in CANON_ORDER:
                continue
            for key in ("human", "human_long", "abbreviation"):
                name = (b.get(key) or "").strip()
                if len(name) >= 2:
                    names[name] = usfm
                    names[name.title()] = usfm
        return cls(names)

    def find(self, text: str) -> list[RefSpan]:
        out: list[RefSpan] = []
        for m in self._pattern.finditer(text):
            book = self._map.get(m.group(1)) or self._map.get(m.group(1).title())
            if not book:
                continue
            usfm = f"{book}.{int(m.group(2))}.{int(m.group(3))}"
            out.append(RefSpan(usfm=usfm, start=m.start(), end=m.end(), resolved=True))
        return out


class ReverseIndex:
    """In-memory whole-version verse index for reverse phrase lookup.

    Built lazily (only when an uncited quote needs it) and cached per version
    for the life of the process. Fetches every chapter of the version into
    memory; nothing is written to disk. The Bible API exposes no search
    endpoint, so this is how uncited quotes are verified deterministically.
    """

    def __init__(self, entries: list[tuple[str, str]]):
        # (loose_normalized_text, usfm)
        self._entries = entries

    @classmethod
    async def build(cls, provider: VerseProvider, version_id: int) -> ReverseIndex:
        meta = await provider.version(version_id)
        chapter_usfms: list[str] = []
        for b in meta.get("books", []):
            if b.get("usfm") not in CANON_ORDER:
                continue
            for c in b.get("chapters", []):
                cu = c.get("usfm", "")
                if c.get("canonical", True) and "." in cu and "INTRO" not in cu:
                    chapter_usfms.append(cu)
        entries: list[tuple[str, str]] = []
        for cu in chapter_usfms:
            try:
                verses = await provider.chapter_verses(version_id, cu)
            except Exception:  # noqa: BLE001
                continue
            for usfm, txt in verses.items():
                entries.append((normalize(txt, "loose"), usfm))
        return cls(entries)

    def lookup(self, quote_loose: str) -> tuple[str | None, float]:
        """Best (usfm, similarity) for a quote against the whole version.

        A quote that is a substring of a verse (model quoted part of a verse)
        counts as a full match; otherwise the best character-similarity verse
        is returned."""
        if not quote_loose:
            return None, 0.0
        from rapidfuzz import fuzz

        best_usfm, best_sim = None, 0.0
        for verse_loose, usfm in self._entries:
            if not verse_loose:
                continue
            if quote_loose in verse_loose:
                return usfm, 1.0
            # cheap length gate before the expensive ratio
            if abs(len(verse_loose) - len(quote_loose)) > max(len(quote_loose), 20):
                continue
            sim = fuzz.ratio(quote_loose, verse_loose) / 100.0
            if sim > best_sim:
                best_usfm, best_sim = usfm, sim
        return best_usfm, best_sim


def _sentence_refs(text: str, quote: QuoteSpan, refs: list[RefSpan]) -> list[RefSpan]:
    """Refs within the quote's sentence or a short adjacency window."""
    lo = max(0, quote.start - _ADJ_CHARS)
    hi = min(len(text), quote.end + _ADJ_CHARS)
    # Sentence bounds around the quote.
    back = text[:quote.start]
    s_start = 0
    for bm in _SENTENCE_BREAK_RE.finditer(back):
        s_start = bm.end()
    fm = _SENTENCE_BREAK_RE.search(text[quote.end:])
    s_end = quote.end + (fm.start() if fm else len(text) - quote.end)
    out = []
    for r in refs:
        in_sentence = r.start >= s_start and r.end <= s_end
        in_window = lo <= r.start <= hi
        if in_sentence or in_window:
            out.append(r)
    return out


class QuoteAuditor:
    def __init__(self, provider: VerseProvider):
        self._provider = provider
        self._resolvers: dict[int, BookNameResolver] = {}
        self._indexes: dict[int, ReverseIndex] = {}

    async def _resolver(self, version_id: int) -> BookNameResolver:
        if version_id not in self._resolvers:
            self._resolvers[version_id] = await BookNameResolver.build(
                self._provider, version_id
            )
        return self._resolvers[version_id]

    async def _index(self, version_id: int) -> ReverseIndex:
        if version_id not in self._indexes:
            self._indexes[version_id] = await ReverseIndex.build(self._provider, version_id)
        return self._indexes[version_id]

    async def _verse_loose(self, version_id: int, usfm: str) -> str | None:
        try:
            span = await self._provider.verse(version_id, usfm)
        except Exception:  # noqa: BLE001
            return None
        return normalize(span.text, "loose") if span else None

    async def _best_across_versions(
        self, qloose: str, usfm: str, version_ids: list[int], max_span: int = 4
    ) -> tuple[float, int | None]:
        """Best (similarity, winning version_id) of the quote to the cited
        reference across accepted versions AND short verse ranges from it.

        Two independent sources of legitimate variation, neither a misquote:
        (1) no version was requested, so any faithful translation counts; and
        (2) models routinely quote a 2-4 verse passage but cite only its first
        verse ("2 Corinthians 1:3" for a 1:3-4 quotation). We compare against
        cumulative windows [v, v..v+1, ...] in each accepted version. The
        winning version_id lets callers report which translation was quoted."""
        try:
            from .usfm import VerseRef

            ref = VerseRef.parse(usfm)
        except Exception:  # noqa: BLE001
            # Non-standard anchor: fall back to single-verse comparison.
            best, best_vid = 0.0, None
            for vid in version_ids:
                vloose = await self._verse_loose(vid, usfm)
                if vloose:
                    sim = _qsim(qloose, vloose)
                    if sim > best:
                        best, best_vid = sim, vid
            return best, best_vid

        best, best_vid = 0.0, None
        for vid in version_ids:
            verses = await self._chapter(vid, ref.chapter_usfm)
            window = ""
            for n in range(ref.verse, ref.verse + max_span):
                piece = verses.get(f"{ref.book}.{ref.chapter}.{n}")
                if not piece:
                    break
                window = f"{window} {normalize(piece, 'loose')}".strip()
                sim = _qsim(qloose, window)
                if sim > best:
                    best, best_vid = sim, vid
                if best >= ACCURATE_SIM:
                    return best, best_vid
        return best, best_vid

    async def _chapter(self, version_id: int, chapter_usfm: str) -> dict[str, str]:
        try:
            return await self._provider.chapter_verses(version_id, chapter_usfm)
        except Exception:  # noqa: BLE001
            return {}

    async def audit(
        self,
        text: str,
        version_id: int,
        *,
        candidate_version_ids: list[int] | None = None,
        use_reverse_index: bool = True,
    ) -> AuditResult:
        versions = candidate_version_ids or [version_id]
        resolver = await self._resolver(version_id)
        refs = resolver.find(text)
        quotes = extract_quotes(text)
        result = AuditResult(cited_refs=[r.usfm for r in refs])

        # A cited reference is fabricated only if it resolves in NO version.
        for r in refs:
            resolved = [await self._verse_loose(v, r.usfm) for v in versions]
            if not any(resolved):
                result.fabricated_refs.append(r.usfm)

        for q in quotes:
            qloose = normalize(q.text, "loose")
            if not qloose:
                continue
            verdict = await self._verify_quote(
                text, q, qloose, refs, version_id, versions, use_reverse_index
            )
            result.verdicts.append(verdict)

        # Also catch scripture the model presented WITHOUT quotation marks. Scan
        # the sentences outside the quoted spans and keep ONLY confident
        # near-verbatim matches (>= MINOR_SIM). Text below that bar yields no
        # verdict, so a paraphrase or allusion is never turned into a misquote —
        # putting words in quotes remains the signal that earns full scrutiny.
        if use_reverse_index:
            covered = [(q.start, q.end) for q in quotes]
            seen = {v.matched_usfm for v in result.verdicts if v.matched_usfm}
            for span in _sentence_spans(text):
                if any(span.start < e and s < span.end for s, e in covered):
                    continue
                qloose = normalize(span.text, "loose")
                if not qloose:
                    continue
                verdict = await self._verify_quote(
                    text, span, qloose, refs, version_id, versions, True
                )
                if (
                    verdict.classification in ("accurate", "minor", "misattributed")
                    and verdict.similarity >= MINOR_SIM
                    and verdict.matched_usfm not in seen
                ):
                    verdict.unquoted = True
                    result.verdicts.append(verdict)
                    seen.add(verdict.matched_usfm)
        return result

    async def _verify_quote(
        self, text, q, qloose, refs, version_id, versions, use_reverse_index,
    ) -> QuoteVerdict:
        # 1. Adjacent/same-sentence reference — check across accepted versions.
        adjacent = _sentence_refs(text, q, refs)
        best_adj = 0.0
        for r in adjacent:
            sim, vid = await self._best_across_versions(qloose, r.usfm, versions)
            best_adj = max(best_adj, sim)
            if sim >= MINOR_SIM:
                return QuoteVerdict(
                    q.text, "accurate" if sim >= ACCURATE_SIM else "minor",
                    sim, r.usfm, r.usfm, 1.0 if sim >= ACCURATE_SIM else sim,
                    matched_version_id=vid,
                )
        if adjacent:
            # Quote doesn't match its adjacent ref. Is it correct scripture
            # attached to the wrong reference (misattributed) or just wrong?
            other_usfm, other_sim, other_vid = await self._best_cited(
                qloose, refs, adjacent, versions
            )
            if other_sim >= ACCURATE_SIM:
                return QuoteVerdict(q.text, "misattributed", other_sim, other_usfm,
                                    adjacent[0].usfm, 0.0, matched_version_id=other_vid)
            if use_reverse_index:
                idx_usfm, idx_sim, idx_vid = await self._reverse_lookup(
                    qloose, version_id, versions
                )
                if idx_sim >= ACCURATE_SIM:
                    return QuoteVerdict(q.text, "misattributed", idx_sim, idx_usfm,
                                        adjacent[0].usfm, 0.0, matched_version_id=idx_vid)
            return QuoteVerdict(q.text, "mismatch", best_adj, None, adjacent[0].usfm, 0.0)

        # 2. No adjacent ref — check other cited refs in the response.
        other_usfm, other_sim, other_vid = await self._best_cited(qloose, refs, [], versions)
        if other_sim >= MINOR_SIM:
            return QuoteVerdict(q.text, "accurate" if other_sim >= ACCURATE_SIM else "minor",
                                other_sim, other_usfm, None,
                                1.0 if other_sim >= ACCURATE_SIM else other_sim,
                                matched_version_id=other_vid)

        # 3. Truly uncited — reverse index over the whole version.
        if use_reverse_index:
            idx_usfm, idx_sim, idx_vid = await self._reverse_lookup(qloose, version_id, versions)
            if idx_sim >= ACCURATE_SIM:
                return QuoteVerdict(q.text, "accurate", idx_sim, idx_usfm, None, 1.0,
                                    matched_version_id=idx_vid)
            if idx_sim >= MINOR_SIM:
                return QuoteVerdict(q.text, "minor", idx_sim, idx_usfm, None, idx_sim,
                                    matched_version_id=idx_vid)
            return QuoteVerdict(q.text, "fabricated", idx_sim, None, None, 0.0)
        return QuoteVerdict(q.text, "unverifiable", 0.0, None, None, 0.0)

    async def _reverse_lookup(
        self, qloose: str, version_id: int, versions: list[int]
    ) -> tuple[str | None, float, int | None]:
        """Locate an uncited quote via the primary-version reverse index, then
        confirm across accepted versions if the located verse is a near-miss
        (i.e. the model likely quoted the same verse in another translation).
        Returns (usfm, similarity, matched_version_id)."""
        idx_usfm, idx_sim = (await self._index(version_id)).lookup(qloose)
        if idx_usfm is None:
            return None, idx_sim, None
        if idx_sim >= ACCURATE_SIM:
            return idx_usfm, idx_sim, version_id
        if idx_sim >= LOCATE_SIM and len(versions) > 1:
            cross, cross_vid = await self._best_across_versions(qloose, idx_usfm, versions)
            if cross > idx_sim:
                return idx_usfm, cross, cross_vid
        return idx_usfm, idx_sim, version_id

    async def _best_cited(
        self, qloose, refs, exclude, versions
    ) -> tuple[str | None, float, int | None]:
        exclude_usfms = {r.usfm for r in exclude}
        best_usfm, best, best_vid = None, 0.0, None
        for r in refs:
            if r.usfm in exclude_usfms:
                continue
            sim, vid = await self._best_across_versions(qloose, r.usfm, versions)
            if sim > best:
                best_usfm, best, best_vid = r.usfm, sim, vid
        return best_usfm, best, best_vid
