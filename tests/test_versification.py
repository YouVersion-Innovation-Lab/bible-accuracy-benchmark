"""Versification translation, pinned against the differences that actually bite.

These run offline against the vendored Paratext tables. The cases are chosen
because each one, left uncorrected, would have scored a model against the wrong
verse.
"""

from __future__ import annotations

import pytest

from bible_bench.versification import (
    SCHEMES,
    VersificationError,
    chapter_count,
    from_org,
    max_verses,
    scheme_has,
    to_org,
    translate,
)


def test_the_psalms_are_renumbered_wholesale_not_shifted():
    """The one that matters most. In lxx/rso, Psalm 23 is eng/org's Psalm 24 —
    a different psalm, not a different verse of the same one. Three of the
    eighteen tested translations use those schemes, so an uncorrected PSA.23.1
    asked of AVM, SYNO or Synod returns the wrong passage entirely."""
    assert translate("PSA.23.1", "eng", "lxx") == "PSA.22.1"
    assert translate("PSA.23.1", "eng", "rso") == "PSA.22.1"
    # ...and the reverse direction agrees.
    assert translate("PSA.22.1", "lxx", "eng") == "PSA.23.1"
    # eng and org agree about Psalm 23, so nothing moves.
    assert translate("PSA.23.1", "eng", "org") == "PSA.23.1"


def test_the_offset_only_covers_the_psalms_it_should():
    """The lxx offset runs through the middle of the Psalter and stops. Psalm 1
    and Psalm 150 are common to both numberings."""
    assert translate("PSA.1.1", "eng", "lxx") == "PSA.1.1"
    assert translate("PSA.150.1", "eng", "lxx") == "PSA.150.1"


def test_identity_when_the_schemes_agree():
    """The tables carry only differences, so most references pass straight
    through — including all of the New Testament's common ground."""
    for usfm in ("GEN.1.1", "JHN.3.16", "ROM.8.28", "REV.22.21"):
        for target in SCHEMES:
            assert translate(usfm, "eng", target) == usfm, (usfm, target)


def test_same_scheme_is_a_no_op_even_for_mapped_verses():
    assert translate("PSA.23.1", "lxx", "lxx") == "PSA.23.1"


def test_org_is_the_pivot_and_round_trips():
    for usfm in ("PSA.23.1", "PSA.51.1", "GEN.1.1"):
        for scheme in ("eng", "lxx", "rso", "vul"):
            there = from_org(to_org(usfm, "eng"), scheme)
            assert to_org(there, scheme) == to_org(usfm, "eng"), (usfm, scheme)


def test_verse_counts_expose_the_psalm_divergence():
    assert max_verses("PSA", 23, "eng") == 6      # The LORD is my shepherd
    assert max_verses("PSA", 23, "lxx") == 10     # ...is eng's Psalm 24
    assert max_verses("PSA", 24, "eng") == 10
    assert chapter_count("PSA", "eng") == 150
    assert chapter_count("PSA", "lxx") == 151
    # A chapter the scheme doesn't have reports 0 rather than raising, so the
    # sampler can treat "no such chapter" as a plain drop.
    assert max_verses("PSA", 151, "eng") == 0
    assert chapter_count("NOSUCHBOOK", "eng") == 0


def test_a_scheme_numbers_books_its_editions_may_not_carry():
    """Schemes define numbering; editions define canon. The `eng` scheme numbers
    Tobit because an English Bible *may* include it (NRSVUE with Apocrypha does),
    while the NIV does not. So a scheme-level check must never be read as "this
    edition has this book" — that question is only answerable from the edition's
    own metadata, the same rule v0.4 established for canon."""
    assert chapter_count("TOB", "eng") == 14
    assert scheme_has("TOB.1.1", "eng")


def test_scheme_has_bounds_the_reference():
    assert scheme_has("PSA.23.6", "eng")
    assert not scheme_has("PSA.23.7", "eng")       # eng Psalm 23 ends at 6
    assert scheme_has("PSA.23.7", "lxx")           # lxx's has 10
    assert not scheme_has("PSA.23.0", "eng")
    assert not scheme_has("nonsense", "eng")


def test_an_unknown_scheme_raises_rather_than_guessing():
    """Silently passing a reference through an unknown scheme would score a
    model against whatever that reference happens to mean there."""
    with pytest.raises(VersificationError):
        translate("GEN.1.1", "eng", "klingon")
