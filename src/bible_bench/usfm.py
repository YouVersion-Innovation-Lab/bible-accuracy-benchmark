"""USFM reference types and book *name* tables.

USFM verse references look like ``JHN.3.16`` (book.chapter.verse). Chapter
references are ``JHN.3``. Some printed editions merge verses; the Bible API
reports those spans with ``+``-joined identifiers like ``PSA.136.4+PSA.136.5``
— such verses are excluded from the benchmark at sampling time.

Nothing here decides whether a book *exists*. Which books a Bible contains is a
property of that Bible: the NIV has no Tobit, the NABRE does, Russian Synodal
carries 3 Maccabees. Ask ``BibleClient.version_books`` /
``version_contains``. The canon tables below are a **reporting label** — they
group a book into the shared 66, the Catholic deuterocanon, or the wider Eastern
canons so results can be sliced by canon. No sampling, detection or scoring
logic gates on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BOOK_NAME_TO_USFM: dict[str, str] = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM",
    "Deuteronomy": "DEU", "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT",
    "1 Samuel": "1SA", "2 Samuel": "2SA", "1 Kings": "1KI", "2 Kings": "2KI",
    "1 Chronicles": "1CH", "2 Chronicles": "2CH", "Ezra": "EZR",
    "Nehemiah": "NEH", "Esther": "EST", "Job": "JOB", "Psalms": "PSA",
    "Psalm": "PSA", "Proverbs": "PRO", "Ecclesiastes": "ECC",
    "Song of Solomon": "SNG", "Song of Songs": "SNG", "Isaiah": "ISA",
    "Jeremiah": "JER", "Lamentations": "LAM", "Ezekiel": "EZK", "Daniel": "DAN",
    "Hosea": "HOS", "Joel": "JOL", "Amos": "AMO", "Obadiah": "OBA",
    "Jonah": "JON", "Micah": "MIC", "Nahum": "NAM", "Habakkuk": "HAB",
    "Zephaniah": "ZEP", "Haggai": "HAG", "Zechariah": "ZEC", "Malachi": "MAL",
    "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN",
    "Acts": "ACT", "Romans": "ROM", "1 Corinthians": "1CO",
    "2 Corinthians": "2CO", "Galatians": "GAL", "Ephesians": "EPH",
    "Philippians": "PHP", "Colossians": "COL", "1 Thessalonians": "1TH",
    "2 Thessalonians": "2TH", "1 Timothy": "1TI", "2 Timothy": "2TI",
    "Titus": "TIT", "Philemon": "PHM", "Hebrews": "HEB", "James": "JAS",
    "1 Peter": "1PE", "2 Peter": "2PE", "1 John": "1JN", "2 John": "2JN",
    "3 John": "3JN", "Jude": "JUD", "Revelation": "REV",
    # Deuterocanonical / apocryphal books (present in Catholic and some other
    # canons, e.g. NABRE). Only versions that carry them are tested on them.
    "Tobit": "TOB", "Judith": "JDT", "Wisdom": "WIS", "Wisdom of Solomon": "WIS",
    "Sirach": "SIR", "Ecclesiasticus": "SIR", "Ben Sira": "SIR", "Baruch": "BAR",
    "1 Maccabees": "1MA", "2 Maccabees": "2MA",
    # Books in Orthodox canons beyond the Catholic seven. Listed here so their
    # references parse and render; whether any given version contains them is
    # answered by that version's metadata, not by this table.
    "1 Esdras": "1ES", "2 Esdras": "2ES", "Prayer of Manasseh": "MAN",
    "Psalm 151": "PS2", "3 Maccabees": "3MA", "4 Maccabees": "4MA",
    "Odes": "ODA", "Psalms of Solomon": "PSS", "Letter of Jeremiah": "LJE",
    "Prayer of Azariah": "S3Y", "Susanna": "SUS", "Bel and the Dragon": "BEL",
    "Greek Esther": "ESG", "Greek Daniel": "DAG",
}

# ── Canon labels (reporting only) ────────────────────────────────────────────
# These group books for the by-canon breakdown. Membership here NEVER decides
# whether a book can be sampled, detected or scored — the version's own metadata
# does that. Keeping the two apart is what lets a model be credited for correctly
# quoting 3 Maccabees instead of accused of inventing it.

# The 66 books every version in the benchmark shares. Cross-language comparison
# (the headline score) is computed over these, because which *other* books are
# testable depends on which editions the Bible API happens to expose — German has
# no Catholic edition available, English has several — and a headline that varied
# with catalogue coverage wouldn't be comparable at all.
PROTESTANT_66: frozenset[str] = frozenset({
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA",
    "1KI", "2KI", "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO",
    "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL", "AMO",
    "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL", "MAT",
    "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP",
    "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE",
    "2PE", "1JN", "2JN", "3JN", "JUD", "REV",
})

# Books of the Catholic canon beyond the 66. Includes the longer Greek forms of
# Esther and Daniel (ESG/DAG), which Catholic Bibles print in place of the
# shorter Hebrew ones, and the Daniel/Jeremiah additions that some editions
# publish as separate books rather than as chapters (LJE = Baruch 6; S3Y, SUS,
# BEL sit inside Catholic Daniel).
CATHOLIC_DEUTERO: frozenset[str] = frozenset({
    "TOB", "JDT", "WIS", "SIR", "BAR", "1MA", "2MA",
    "ESG", "DAG", "LJE", "S3Y", "SUS", "BEL",
})

# Books in Eastern canons (or their liturgical appendices) beyond the Catholic
# set. Grouped as one slice: the Greek, Slavonic and Georgian canons differ from
# each other, and the benchmark isn't fine-grained enough to speak for each.
ORTHODOX_EXTRA: frozenset[str] = frozenset({
    "1ES", "2ES", "3MA", "4MA", "MAN", "PS2", "ODA", "PSS",
})

# Canon slice names, widest-first, as used in reports and on the website.
CANONS: tuple[str, ...] = ("protestant", "catholic", "orthodox", "other")


def canon_of(book: str) -> str:
    """Which canon slice a USFM book code is reported under.

    A label, not a gate: an unrecognized code is reported as ``other`` rather
    than rejected, so a translation carrying a book we've never seen still shows
    up in the results instead of vanishing.
    """
    code = book.strip().upper()
    if code in PROTESTANT_66:
        return "protestant"
    if code in CATHOLIC_DEUTERO:
        return "catholic"
    if code in ORTHODOX_EXTRA:
        return "orthodox"
    return "other"

# First (canonical) English name per USFM code; Psalm/Psalms etc. resolve to
# the first (plural/long) form.
_USFM_TO_BOOK_NAME: dict[str, str] = {}
for _name, _code in BOOK_NAME_TO_USFM.items():
    _USFM_TO_BOOK_NAME.setdefault(_code, _name)

# Books with a single chapter (references like "Jude 4" mean Jude 1:4).
SINGLE_CHAPTER_BOOKS = frozenset({"OBA", "PHM", "2JN", "3JN", "JUD"})

# USFM book codes are exactly three characters and may carry a digit in any
# position: GEN, 1SA, PS2 (Psalm 151), 4MA, S3Y (Prayer of Azariah).
_VERSE_USFM_RE = re.compile(r"^([0-9A-Z]{3})\.(\d{1,3})\.(\d{1,3})$")
_CHAPTER_USFM_RE = re.compile(r"^([0-9A-Z]{3})\.(\d{1,3})$")


class UsfmError(ValueError):
    pass


def is_standard_verse_usfm(usfm: str) -> bool:
    """True for clean BOOK.CH.V references. Some editions emit split-chapter or
    subdivided anchors (e.g. 'PSA.106_1.1') the benchmark doesn't sample."""
    return bool(_VERSE_USFM_RE.match(usfm.strip().upper()))


def is_standard_chapter_usfm(usfm: str) -> bool:
    """True for clean BOOK.CH references.

    The chapter counterpart of ``is_standard_verse_usfm``, needed for the same
    reason: several editions subdivide a chapter and anchor the parts as
    'SIR.1_1', which is a real chapter identifier but not one a verse reference
    can be built from.
    """
    return bool(_CHAPTER_USFM_RE.match(usfm.strip().upper()))


@dataclass(frozen=True, order=True)
class VerseRef:
    """A single-verse USFM reference like JHN.3.16."""

    book: str
    chapter: int
    verse: int

    @classmethod
    def parse(cls, usfm: str) -> VerseRef:
        """Parse a reference. Validates SYNTAX only, deliberately.

        Whether a book exists is a property of a *version*, not of the reference:
        the NIV has no Tobit, NABRE does, and Russian Synodal has 3 Maccabees.
        Ask the client (``version_contains``) for that. Gating here on a
        hard-coded canon made Orthodox books unparseable, so they could never be
        sampled and were invisible to quote detection — a model quoting
        3 Maccabees correctly was scored as having invented it.
        """
        m = _VERSE_USFM_RE.match(usfm.strip().upper())
        if not m:
            raise UsfmError(f"Not a single-verse USFM reference: {usfm!r}")
        return cls(book=m.group(1), chapter=int(m.group(2)), verse=int(m.group(3)))

    @property
    def usfm(self) -> str:
        return f"{self.book}.{self.chapter}.{self.verse}"

    @property
    def chapter_usfm(self) -> str:
        return f"{self.book}.{self.chapter}"

    def english_reference(self) -> str:
        """English human-readable form, e.g. 'John 3:16'. For localized forms
        use the version's own book names via the Bible API client."""
        name = _USFM_TO_BOOK_NAME.get(self.book, self.book)
        if self.book in SINGLE_CHAPTER_BOOKS:
            return f"{name} {self.verse}"
        return f"{name} {self.chapter}:{self.verse}"


def book_name_to_usfm(name: str) -> str:
    usfm = BOOK_NAME_TO_USFM.get(name.strip())
    if usfm is None:
        raise UsfmError(f"Unknown book name: {name!r}")
    return usfm


def usfm_to_book_name(code: str) -> str:
    name = _USFM_TO_BOOK_NAME.get(code.strip().upper())
    if name is None:
        raise UsfmError(f"Unknown USFM book code: {code!r}")
    return name
