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


def test_parse_validates_syntax_not_canon():
    """v0.4 keystone: whether a book EXISTS is a property of a version, not of the
    reference. Gating parse() on a hard-coded canon made Orthodox books
    unparseable, so they could never be sampled and were invisible to quote
    detection — a model quoting 3 Maccabees correctly was scored as inventing it.
    """
    for usfm in ["3MA.2.1", "4MA.6.1", "PS2.1.1", "S3Y.1.5", "1ES.4.2",
                 "2ES.14.1", "MAN.1.1", "ESG.1.1", "DAG.3.1", "LJE.1.1"]:
        ref = VerseRef.parse(usfm)
        assert ref.usfm == usfm, f"{usfm} must round-trip"
        assert ref.english_reference(), f"{usfm} must render a human reference"


def test_parse_still_rejects_malformed_references():
    for bad in ["JHN.3", "JHN.3.16.2", "john 3:16", "TOOLONG.1.1", "J.1.1", ""]:
        with pytest.raises(UsfmError):
            VerseRef.parse(bad)


def test_english_reference_falls_back_to_the_code():
    """A book with no English name in the table must still render, not KeyError."""
    assert VerseRef.parse("XYZ.1.2").english_reference() == "XYZ 1:2"
