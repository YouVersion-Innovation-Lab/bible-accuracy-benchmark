"""USFM reference types and canonical book tables (Protestant 66-book canon
plus the deuterocanonical books carried by Catholic and some other canons).

USFM verse references look like ``JHN.3.16`` (book.chapter.verse). Chapter
references are ``JHN.3``. Some printed editions merge verses; the Bible API
reports those spans with ``+``-joined identifiers like ``PSA.136.4+PSA.136.5``
— such verses are excluded from the benchmark at sampling time.
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
}

# The extra books beyond the Protestant 66 that appear in Catholic (and some
# other) canons. Sampled only from versions whose metadata actually lists them.
DEUTEROCANON: list[str] = ["TOB", "JDT", "WIS", "SIR", "BAR", "1MA", "2MA"]

# Book codes the benchmark recognizes. Order is not significant (used only for
# membership); it includes the deuterocanonical books so their references parse
# and resolve for the versions that contain them.
CANON_ORDER: list[str] = [
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA",
    "1KI", "2KI", "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO",
    "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL", "AMO",
    "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL", "MAT",
    "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP",
    "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE",
    "2PE", "1JN", "2JN", "3JN", "JUD", "REV",
    *DEUTEROCANON,
]

_CANON_SET = frozenset(CANON_ORDER)

# First (canonical) English name per USFM code; Psalm/Psalms etc. resolve to
# the first (plural/long) form.
_USFM_TO_BOOK_NAME: dict[str, str] = {}
for _name, _code in BOOK_NAME_TO_USFM.items():
    _USFM_TO_BOOK_NAME.setdefault(_code, _name)

# Books with a single chapter (references like "Jude 4" mean Jude 1:4).
SINGLE_CHAPTER_BOOKS = frozenset({"OBA", "PHM", "2JN", "3JN", "JUD"})

_VERSE_USFM_RE = re.compile(r"^([1-3]?[A-Z]{2,3})\.(\d{1,3})\.(\d{1,3})$")


class UsfmError(ValueError):
    pass


def is_standard_verse_usfm(usfm: str) -> bool:
    """True for clean BOOK.CH.V references. Some editions emit split-chapter or
    subdivided anchors (e.g. 'PSA.106_1.1') the benchmark doesn't sample."""
    m = _VERSE_USFM_RE.match(usfm.strip().upper())
    return bool(m) and m.group(1) in _CANON_SET


@dataclass(frozen=True, order=True)
class VerseRef:
    """A single-verse USFM reference like JHN.3.16."""

    book: str
    chapter: int
    verse: int

    @classmethod
    def parse(cls, usfm: str) -> VerseRef:
        m = _VERSE_USFM_RE.match(usfm.strip().upper())
        if not m:
            raise UsfmError(f"Not a single-verse USFM reference: {usfm!r}")
        book, chapter, verse = m.group(1), int(m.group(2)), int(m.group(3))
        if book not in _CANON_SET:
            raise UsfmError(f"Unknown USFM book code: {book!r}")
        return cls(book=book, chapter=chapter, verse=verse)

    @property
    def usfm(self) -> str:
        return f"{self.book}.{self.chapter}.{self.verse}"

    @property
    def chapter_usfm(self) -> str:
        return f"{self.book}.{self.chapter}"

    def english_reference(self) -> str:
        """English human-readable form, e.g. 'John 3:16'. For localized forms
        use the version's own book names via the Bible API client."""
        name = _USFM_TO_BOOK_NAME[self.book]
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
