"""Where did the text a model produced actually come from?

Every dimension asks this same question and used to answer it separately, with
near-duplicate notions of "wrong version" and "fabricated" that drifted apart:

* Direct Quotation compared against other editions of the SAME language and
  called anything else `fabricated`.
* Scripture in Answers searched the language's editions and called a miss
  `fabricated`.
* Hallucination had its own ladder.

The drift produced false accusations. Grok 4.5 answers a Hindi question with an
accurate English NIV quotation; that matched no Hindi edition, so all 52 Hindi
quotations were labelled "invented a verse" — of a model that had invented
nothing (docs/FINDINGS.md F-3). "Quoted the right verse from the wrong Bible" and
"made it up" are different failures that a frontier lab would fix differently,
and a benchmark that conflates them tells that lab the wrong thing.

So provenance is defined once, here, and every dimension classifies against it:

    REQUESTED       the edition that was asked for
    OTHER_VERSION   a real verse, another edition of the same language
    OTHER_LANGUAGE  a real verse, an edition in a different language
    NONE            matches no edition we carry — the only case worth the word
                    "fabricated"

Ordering is deliberate: each step is a weaker claim about the model than the one
before, so `classify` returns the strongest provenance that fits and callers can
compare with `>=`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Strongest to weakest. A dimension may score these differently — quoting another
# edition is near-worthless when a translation was named and perfectly acceptable
# when none was — but they always MEAN the same thing.
REQUESTED = "requested"
OTHER_VERSION = "other_version"
OTHER_LANGUAGE = "other_language"
NONE = "none"

ORDER = (REQUESTED, OTHER_VERSION, OTHER_LANGUAGE, NONE)

#: Human-facing labels. The site imports these so its wording can't drift from
#: the scorer's meaning.
LABELS = {
    REQUESTED: "the translation asked for",
    OTHER_VERSION: "another translation of the same language",
    OTHER_LANGUAGE: "a translation in a different language",
    NONE: "no translation we searched",
}


def rank(provenance: str) -> int:
    """Position in ORDER — lower is a stronger match. Unknown values sort last."""
    try:
        return ORDER.index(provenance)
    except ValueError:
        return len(ORDER)


@dataclass(frozen=True)
class Source:
    """One edition — either the one a question asked for, or one a span matched.

    ``version_id`` is None when the question named a language but no particular
    edition. Scripture in Answers works that way on purpose: the model chooses
    what to quote, so no edition can be "the" one, and preferring the item's
    nominal version would corrupt the "which translation does this model reach
    for" finding. With no edition requested, every edition of the language ranks
    equally as OTHER_VERSION and fidelity decides between them.
    """

    version_id: int | None
    language_tag: str
    version_abbrev: str = ""


@dataclass(frozen=True)
class Match:
    """The best account of where a span of text came from."""

    provenance: str = NONE
    similarity: float = 0.0
    usfm: str | None = None
    version_id: int | None = None
    language_tag: str | None = None
    version_abbrev: str = ""
    #: Every candidate considered, best first — kept so a run can be audited
    #: without re-deriving the search.
    considered: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_real_scripture(self) -> bool:
        """Did the model quote a genuine verse, whatever edition it came from?

        The distinction the old vocabulary could not express, and the one that
        separates a translation mismatch from an invention.
        """
        return self.provenance != NONE


def classify(
    *,
    requested: Source,
    matched_version_id: int | None,
    matched_language_tag: str | None,
    similarity: float = 0.0,
    usfm: str | None = None,
    version_abbrev: str = "",
    considered: tuple[str, ...] = (),
) -> Match:
    """Turn "which edition did this text match" into a provenance.

    Deliberately dumb: it takes an already-resolved match and names it. The
    searching lives in quotefind, which knows how to look text up; this knows
    what a hit MEANS. Keeping those apart is what stops three dimensions from
    each inventing their own vocabulary again.
    """
    if matched_version_id is None:
        return Match(provenance=NONE, considered=considered)
    if matched_version_id == requested.version_id:
        provenance = REQUESTED
    elif matched_language_tag == requested.language_tag or matched_language_tag is None:
        provenance = OTHER_VERSION
    else:
        provenance = OTHER_LANGUAGE
    return Match(
        provenance=provenance,
        similarity=similarity,
        usfm=usfm,
        version_id=matched_version_id,
        language_tag=matched_language_tag,
        version_abbrev=version_abbrev,
        considered=considered,
    )


def best(matches: list[Match]) -> Match:
    """The strongest provenance among several, ties broken by similarity."""
    if not matches:
        return Match()
    return min(matches, key=lambda m: (rank(m.provenance), -m.similarity))
