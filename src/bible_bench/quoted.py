"""One way to judge a string a model presented as scripture.

Every dimension of this benchmark ends up holding a stretch of text and asking
the same two questions about it:

  1. **Which verse, in which edition, is this?** — answered by searching
     (:mod:`quotefind`) and named by :mod:`provenance`.
  2. **How faithful are the words?** — answered by one similarity measure, banded
     on one ladder.

Each dimension used to answer both questions its own way, and the three answers
drifted apart. Direct Quotation compared against a hand-picked distractor list;
Scripture in Answers searched a single language and called any miss
"fabricated"; Hallucination Resistance had a third notion again. Every false
accusation this benchmark has made came out of that drift, so the answers live
here, once, and every dimension calls the same code.

The bottom rung of the ladder is the one that matters most. Below
``RECOGNISABLE`` we do not claim to know which verse a string is — and the only
honest thing to say then is **"we did not find it"**, which is a different claim
from **"the model invented it"**. A search is not evidence of absence unless it
was exhaustive. So :class:`Judgement` reports ``found``, and the word
"fabricated" belongs to callers that have searched everything they can; three
separate false-accusation bugs came from treating a failed search as a verdict:

  * the proposal stage silently dropped verses 97% identical to the span
    (:func:`quotefind.VersionIndex.propose`);
  * the identification floor sat at 0.75, so a recognisable-but-poor quotation
    became an invention rather than a misquote;
  * only the language asked about was searched, so accurate scripture in another
    language was an invention too (docs/FINDINGS.md F-3).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import provenance, quotefind
from .normalize import normalize
from .quotefind import Span, fidelity_and_coverage, similarity

__all__ = [
    "BANDS",
    "NEAR",
    "NOT_FOUND",
    "RECOGNISABLE",
    "VERBATIM",
    "Candidate",
    "Judgement",
    "Span",
    "band",
    "fidelity_and_coverage",
    "judge",
    "scan",
    "similarity",
]

# ---------------------------------------------------------------------------
# The one fidelity ladder.
#
# These grade how faithful a quotation is, NOT whether it was the verse asked
# for — that is provenance's job, and keeping the two apart is the whole point of
# this module. Direct Quotation additionally splits the top of this range more
# finely (see scoring.py): "did you reproduce the verse I named" needs to tell
# perfect from near-perfect, while "is the scripture you volunteered accurate"
# does not. Different questions, deliberately different resolution — but they
# share the floor below, because they share the claim it licenses.
# ---------------------------------------------------------------------------

#: Word-for-word, allowing only normalization-level difference.
VERBATIM = 0.98
#: Recognisably the verse, wording slightly off.
NEAR = 0.90
#: The floor of all claims. Above it we are willing to say which verse a string
#: is; below it we say only that we did not find it. Calibrated, not guessed:
#: measured across real answers, genuine quotations of a verse we hold in a
#: slightly different edition sit at 0.70–1.00, while a *different* verse from
#: the same chapter sits at 0.43–0.52 (see runner._mark_absent_book_quotes).
#: 0.60 separates those with room on both sides, and is the same number the
#: direct-quote track already uses for the same judgement.
RECOGNISABLE = 0.60

#: Band for a string no edition matched. Named rather than empty so callers
#: can't confuse "we found nothing" with "we found something at fidelity 0".
NOT_FOUND = "not_found"

#: What real, accurately-quoted scripture from a Bible other than the one asked
#: for is worth. Every dimension uses this one number, because it answers one
#: question: the model delivered genuine scripture, so this is not invention and
#: cannot score zero; it did not deliver what was asked, so it cannot score full.
#: Applies to a different translation and to a different language alike.
WRONG_BIBLE_SCORE = 0.25

BANDS = ("verbatim", "near", "recognisable", NOT_FOUND)


def band(fidelity: float) -> str:
    """Which rung of the ladder a fidelity falls on."""
    if fidelity >= VERBATIM:
        return "verbatim"
    if fidelity >= NEAR:
        return "near"
    if fidelity >= RECOGNISABLE:
        return "recognisable"
    return NOT_FOUND


@dataclass(frozen=True)
class Candidate:
    """One edition's best answer to "which verse is this string?".

    Produced by searching (see :func:`quotefind.VersionIndex.best`); consumed by
    :func:`judge`, which decides what it means.
    """

    source: provenance.Source
    usfm: str
    verse_loose: str


@dataclass(frozen=True)
class Judgement:
    """What a string a model presented as scripture turned out to be."""

    match: provenance.Match
    fidelity: float = 0.0
    coverage: float = 0.0

    @property
    def found(self) -> bool:
        """Did we identify this string as a real verse in some edition?

        False means the search came up empty. Whether that licenses the word
        "invented" depends entirely on how exhaustive the search was, which is
        the caller's knowledge, not ours.
        """
        return self.match.is_real_scripture

    @property
    def band(self) -> str:
        return band(self.fidelity) if self.found else NOT_FOUND


def judge(
    span_loose: str,
    candidates: list[Candidate],
    *,
    requested: provenance.Source,
    floor: float = RECOGNISABLE,
) -> Judgement:
    """Decide what a string is, given what each edition's search turned up.

    Provenance outranks fidelity: a perfect match in the wrong Bible must not
    beat a good match in the right one, or a model gets credit for answering a
    question it wasn't asked. Within one provenance, fidelity decides.
    """
    scored: list[tuple[provenance.Match, float]] = []
    for c in candidates:
        fidelity, coverage = fidelity_and_coverage(span_loose, c.verse_loose)
        if fidelity < floor:
            continue
        scored.append((
            provenance.classify(
                requested=requested,
                matched_version_id=c.source.version_id,
                matched_language_tag=c.source.language_tag,
                similarity=fidelity,
                usfm=c.usfm,
                version_abbrev=c.source.version_abbrev,
            ),
            coverage,
        ))
    if not scored:
        return Judgement(match=provenance.Match())
    winner = provenance.best([m for m, _ in scored])
    # `best` returns one of the objects it was given, so identity finds its row.
    coverage = next(cov for m, cov in scored if m is winner)
    return Judgement(match=winner, fidelity=winner.similarity, coverage=coverage)


async def scan(
    client,
    editions: list[provenance.Source],
    texts: dict[str, str],
    spans: list[Span],
    *,
    requested: dict[str, provenance.Source],
    floor: float = RECOGNISABLE,
    progress=None,
) -> tuple[dict[str, dict[str, quotefind.Detection]], dict[str, Judgement]]:
    """Identify every span against every edition, and judge what it found.

    This is the one place competing editions are compared, so it is the one place
    that has to know a perfect match in the wrong Bible loses to a good match in
    the right one. Ranking by similarity alone — which is what the code here used
    to do — silently answered a different question than the one the item asked.

    ``editions`` may span languages, and that is the point: pass one language's
    editions and a quotation from another language reads as an invention; pass
    several and it reads as what it is. The caller decides how wide to search and
    therefore how strong a claim it is entitled to make.

    Memory is bounded to one index at a time regardless of how many editions are
    passed (see :func:`quotefind.scan_editions`), which is why the best-so-far is
    accumulated here rather than every candidate being kept.
    """
    loose = {s.key: normalize(s.text, "loose") for s in spans}
    winners: dict[str, tuple[provenance.Match, float]] = {}
    default = provenance.Source(version_id=None, language_tag="")

    def on_edition(edition: provenance.Source, index: quotefind.VersionIndex) -> None:
        for s in spans:
            usfm, _sim = index.best(loose[s.key])
            if not usfm:
                continue
            fidelity, coverage = fidelity_and_coverage(loose[s.key], index.verses[usfm])
            if fidelity < floor:
                continue
            match = provenance.classify(
                requested=requested.get(s.key, default),
                matched_version_id=edition.version_id,
                matched_language_tag=edition.language_tag,
                similarity=fidelity,
                usfm=usfm,
                version_abbrev=edition.version_abbrev,
            )
            current = winners.get(s.key)
            # Incumbent first, so an exact tie keeps it and the result cannot
            # depend on the order editions happen to be walked in.
            if current is None or provenance.best([current[0], match]) is match:
                winners[s.key] = (match, coverage)

    detections = await quotefind.scan_editions(
        client, editions, texts, spans, floor=floor,
        on_edition=on_edition, progress=progress,
    )
    return detections, {
        key: Judgement(match=m, fidelity=m.similarity, coverage=cov)
        for key, (m, cov) in winners.items()
    }
