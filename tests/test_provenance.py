"""Provenance is the one vocabulary every dimension shares.

The cases below are the ones that were previously mislabelled — each is a real
observation from a published run, not a hypothetical.
"""

from __future__ import annotations

from bible_bench import provenance as prov

ENG_NLT = prov.Source(version_id=116, language_tag="eng", version_abbrev="NLT")
HIN_HHBD = prov.Source(version_id=819, language_tag="hin", version_abbrev="HHBD")


def test_the_edition_asked_for_is_the_strongest_match():
    m = prov.classify(requested=ENG_NLT, matched_version_id=116,
                      matched_language_tag="eng", similarity=1.0)
    assert m.provenance == prov.REQUESTED
    assert m.is_real_scripture


def test_another_edition_of_the_same_language_is_not_an_invention():
    """Asked for the NLT, answered accurately from the KJV. Real scripture from
    the wrong Bible — a translation mismatch, not a fabrication."""
    m = prov.classify(requested=ENG_NLT, matched_version_id=1,
                      matched_language_tag="eng", similarity=0.99)
    assert m.provenance == prov.OTHER_VERSION
    assert m.is_real_scripture


def test_another_language_is_its_own_verdict():
    """Grok 4.5 answers a Hindi question with an accurate English NIV quotation
    (FINDINGS F-3). All 52 of its Hindi quotations were graded 'invented a verse';
    they matched no HINDI edition, which is a different claim entirely."""
    m = prov.classify(requested=HIN_HHBD, matched_version_id=111,
                      matched_language_tag="eng", similarity=1.0)
    assert m.provenance == prov.OTHER_LANGUAGE
    assert m.is_real_scripture, "quoting the right verse in the wrong language is not invention"


def test_only_a_match_against_nothing_earns_the_word_fabricated():
    m = prov.classify(requested=ENG_NLT, matched_version_id=None,
                      matched_language_tag=None)
    assert m.provenance == prov.NONE
    assert not m.is_real_scripture


def test_an_unknown_language_on_the_match_stays_conservative():
    """A hit whose language we can't name is treated as the same language — the
    weaker accusation. Guessing OTHER_LANGUAGE would invent a finding."""
    m = prov.classify(requested=ENG_NLT, matched_version_id=1,
                      matched_language_tag=None, similarity=0.9)
    assert m.provenance == prov.OTHER_VERSION


def test_provenance_is_ordered_strongest_first():
    assert prov.rank(prov.REQUESTED) < prov.rank(prov.OTHER_VERSION)
    assert prov.rank(prov.OTHER_VERSION) < prov.rank(prov.OTHER_LANGUAGE)
    assert prov.rank(prov.OTHER_LANGUAGE) < prov.rank(prov.NONE)
    assert prov.rank("something-new") == len(prov.ORDER)


def test_best_prefers_provenance_over_similarity():
    """A perfect match in the wrong language must not beat a good match in the
    right edition — otherwise a model gets credit for the wrong Bible."""
    weaker_but_right = prov.classify(requested=ENG_NLT, matched_version_id=116,
                                     matched_language_tag="eng", similarity=0.80)
    perfect_but_foreign = prov.classify(requested=ENG_NLT, matched_version_id=819,
                                        matched_language_tag="hin", similarity=1.0)
    assert prov.best([perfect_but_foreign, weaker_but_right]) is weaker_but_right
    # Within one provenance, similarity decides.
    close = prov.classify(requested=ENG_NLT, matched_version_id=1,
                          matched_language_tag="eng", similarity=0.7)
    closer = prov.classify(requested=ENG_NLT, matched_version_id=111,
                           matched_language_tag="eng", similarity=0.95)
    assert prov.best([close, closer]) is closer
    assert prov.best([]).provenance == prov.NONE


def test_every_provenance_has_a_label_for_the_site():
    """The site imports LABELS so its wording cannot drift from the scorer's
    meaning — which is how 'fabricated' came to describe four different things."""
    assert set(prov.LABELS) == set(prov.ORDER)
    assert all(prov.LABELS[p] for p in prov.ORDER)
