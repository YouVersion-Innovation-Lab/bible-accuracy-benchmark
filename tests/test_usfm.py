import pytest

from bible_bench.usfm import (
    CANON_ORDER,
    DEUTEROCANON,
    UsfmError,
    VerseRef,
    book_name_to_usfm,
)


def test_parse_verse_ref():
    ref = VerseRef.parse("JHN.3.16")
    assert (ref.book, ref.chapter, ref.verse) == ("JHN", 3, 16)
    assert ref.usfm == "JHN.3.16"
    assert ref.chapter_usfm == "JHN.3"


def test_english_reference():
    assert VerseRef.parse("JHN.3.16").english_reference() == "John 3:16"
    assert VerseRef.parse("PSA.23.1").english_reference() == "Psalms 23:1"
    # Single-chapter books drop the chapter number.
    assert VerseRef.parse("JUD.1.4").english_reference() == "Jude 4"


def test_invalid_refs_raise():
    for bad in ["JHN.3", "NOPE.1.1", "JHN.3.16.2", "john 3:16"]:
        with pytest.raises(UsfmError):
            VerseRef.parse(bad)


def test_canon_has_66_protestant_books_plus_deuterocanon():
    protestant = [b for b in CANON_ORDER if b not in set(DEUTEROCANON)]
    assert len(protestant) == 66
    assert protestant[0] == "GEN" and protestant[-1] == "REV"
    assert len(DEUTEROCANON) == 7
    # Deuterocanonical references must parse (they're in the recognized set).
    assert VerseRef.parse("TOB.3.4").book == "TOB"


def test_book_name_lookup():
    assert book_name_to_usfm("Psalm") == "PSA"
    assert book_name_to_usfm("Song of Songs") == "SNG"
    with pytest.raises(UsfmError):
        book_name_to_usfm("Gospel of Thomas")
