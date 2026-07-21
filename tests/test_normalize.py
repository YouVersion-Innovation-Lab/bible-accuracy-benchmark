from fake_bible import ARABIC_PLAIN, ARABIC_POINTED, PERSIAN_NO_ZWNJ, PERSIAN_ZWNJ

from bible_bench.normalize import normalize


def test_strict_folds_quote_glyphs():
    assert normalize("“Hello” — it’s «fine»", "strict") == "\"Hello\" - it's \"fine\""


def test_strict_preserves_case_and_punctuation():
    assert normalize("The quick Fox; it jumped!", "strict") == "The quick Fox; it jumped!"


def test_strict_folds_smallcaps_divine_name():
    # Print editions render \nd markers as small caps ("LORD"); the API's HTML
    # extraction yields "Lord". Both forms must strict-match; lowercase must not.
    assert normalize("The LORD is my shepherd", "strict") == normalize(
        "The Lord is my shepherd", "strict"
    )
    assert normalize("the lord is my shepherd", "strict") != normalize(
        "The Lord is my shepherd", "strict"
    )
    assert normalize("el SEÑOR es mi pastor", "strict") == normalize(
        "el Señor es mi pastor", "strict"
    )


def test_strict_collapses_whitespace_and_invisibles():
    assert normalize("a b‎  c\n\td", "strict") == "a b c d"


def test_loose_casefolds_and_strips_punctuation():
    assert normalize("The LORD is my shepherd; I lack nothing.", "loose") == (
        "the lord is my shepherd i lack nothing"
    )


def test_loose_folds_arabic_vowel_points():
    assert normalize(ARABIC_POINTED, "loose") == normalize(ARABIC_PLAIN, "loose")


def test_loose_folds_persian_zwnj():
    assert normalize(PERSIAN_ZWNJ, "loose") == normalize(PERSIAN_NO_ZWNJ, "loose")


def test_strict_keeps_arabic_points():
    assert normalize(ARABIC_POINTED, "strict") != normalize(ARABIC_PLAIN, "strict")


def test_deterministic():
    s = "“Mixed” text — with everything…"
    assert normalize(s, "loose") == normalize(s, "loose")
