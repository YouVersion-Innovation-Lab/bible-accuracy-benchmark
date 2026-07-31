"""One way to judge a string a model presented as scripture.

Every dimension asks the same two questions of such a string — which verse in
which edition is it, and how faithful are the words — and each used to answer
separately. These pin the shared answer, and the distinction that matters most:
"we did not find it" is not "the model invented it".
"""

from bible_bench import provenance, quoted

VERSE = "the lord is my shepherd i shall not want he makes me lie down in green pastures"
ASKED_FOR = provenance.Source(version_id=111, language_tag="eng", version_abbrev="NIV11")
NO_EDITION_ASKED = provenance.Source(version_id=None, language_tag="eng")


def _cand(version_id, language_tag, verse=VERSE, usfm="PSA.23.1", abbrev=""):
    return quoted.Candidate(
        source=provenance.Source(version_id, language_tag, abbrev),
        usfm=usfm,
        verse_loose=verse,
    )


def test_the_ladder_is_ordered_and_total():
    assert quoted.band(1.0) == "verbatim"
    assert quoted.band(0.93) == "near"
    assert quoted.band(0.70) == "recognisable"
    assert quoted.band(0.30) == quoted.NOT_FOUND
    assert quoted.VERBATIM > quoted.NEAR > quoted.RECOGNISABLE > 0
    assert set(quoted.BANDS) == {quoted.band(x) for x in (1.0, 0.93, 0.70, 0.0)}


def test_no_threshold_has_two_homes():
    """Every module that grades fidelity takes its numbers from this ladder.
    quotefind and auditor each used to keep their own copies; a threshold with two
    homes is one that will eventually disagree with itself.

    quotefind writes VERBATIM out longhand because importing quoted would be a
    cycle, so that one is pinned here instead of shared.
    """
    from bible_bench import auditor, quotefind

    assert quotefind.SHORT_VERSE_WHOLE_FLOOR == quoted.VERBATIM
    assert auditor.ACCURATE_SIM is quoted.VERBATIM
    assert auditor.MINOR_SIM is quoted.NEAR
    assert auditor.LOCATE_SIM is quoted.RECOGNISABLE


def test_a_verbatim_quote_of_the_edition_asked_for():
    j = quoted.judge(VERSE, [_cand(111, "eng")], requested=ASKED_FOR)
    assert j.found
    assert j.match.provenance == provenance.REQUESTED
    assert j.band == "verbatim"
    assert j.coverage == 1.0


def test_a_faithful_fragment_is_faithful():
    """Quoting one clause accurately is a correct quotation of that clause, not a
    partly-wrong whole verse — but coverage still records that less arrived."""
    j = quoted.judge("the lord is my shepherd i shall not want",
                     [_cand(111, "eng")], requested=ASKED_FOR)
    assert j.band == "verbatim"
    assert j.coverage < 0.6


def test_nothing_found_is_not_the_same_as_found_at_zero():
    """The distinction three separate false-accusation bugs came from ignoring."""
    j = quoted.judge("and lo the auditor did balance the ledger of heaven",
                     [_cand(111, "eng")], requested=ASKED_FOR)
    assert not j.found
    assert j.band == quoted.NOT_FOUND
    assert j.match.provenance == provenance.NONE
    assert j.fidelity == 0.0
    # Same answer when there was nothing to search at all — and the caller cannot
    # tell those apart from the Judgement, which is deliberate: how exhaustive the
    # search was is the caller's knowledge, not this module's.
    assert not quoted.judge(VERSE, [], requested=ASKED_FOR).found


def test_another_edition_of_the_same_language_is_named_as_such():
    """Asked for the NIV, answered accurately from another English Bible. Real
    scripture from the wrong Bible — a translation mismatch, not an invention."""
    j = quoted.judge(VERSE, [_cand(1, "eng")], requested=ASKED_FOR)
    assert j.found
    assert j.match.provenance == provenance.OTHER_VERSION
    assert j.band == "verbatim"


def test_another_language_is_its_own_verdict():
    """FINDINGS F-3: Grok 4.5 answers a Hindi question with accurate English
    scripture. All 52 of its Hindi quotations were graded "invented a verse"."""
    j = quoted.judge(VERSE, [_cand(111, "eng")],
                     requested=provenance.Source(version_id=819, language_tag="hin"))
    assert j.found, "quoting the right verse in the wrong language is not invention"
    assert j.match.provenance == provenance.OTHER_LANGUAGE
    assert j.match.language_tag == "eng"


def test_the_edition_asked_for_beats_a_better_match_elsewhere():
    """Provenance outranks fidelity, or a model gets credit for the wrong Bible."""
    reworded = "the lord is my shepherd i lack nothing he lets me rest in green meadows"
    j = quoted.judge(
        VERSE,
        [_cand(1, "eng"), _cand(111, "eng", verse=reworded)],
        requested=ASKED_FOR,
    )
    assert j.match.version_id == 111
    assert j.match.provenance == provenance.REQUESTED
    assert j.band == "recognisable", "the right Bible, imperfectly quoted"


def test_with_no_edition_requested_fidelity_alone_decides():
    """Scripture in Answers names no translation on purpose — the model chooses —
    so preferring the item's nominal version would corrupt the "which translation
    does this model reach for" finding."""
    reworded = "the lord is my shepherd i lack nothing he lets me rest in green meadows"
    j = quoted.judge(
        VERSE,
        [_cand(111, "eng", verse=reworded), _cand(1, "eng")],
        requested=NO_EDITION_ASKED,
    )
    assert j.match.version_id == 1, "the edition actually quoted, not the nominal one"
    assert j.match.provenance == provenance.OTHER_VERSION


def test_a_language_match_beats_a_perfect_foreign_one():
    """A poor match in the language the reader asked in still outranks a perfect
    match in a language they can't read: the question was about their language."""
    reworded = "the lord is my shepherd i lack nothing he lets me rest in green meadows"
    j = quoted.judge(
        VERSE,
        [_cand(48, "zho"), _cand(111, "eng", verse=reworded)],
        requested=NO_EDITION_ASKED,
    )
    assert j.match.language_tag == "eng"
    assert j.match.provenance == provenance.OTHER_VERSION


def test_the_floor_is_the_callers_to_raise():
    """A caller that has searched less widely can demand a stronger match before
    it is willing to name a verse."""
    reworded = "the lord is my shepherd i lack nothing he lets me rest in green meadows"
    cands = [_cand(111, "eng", verse=reworded)]
    assert quoted.judge(VERSE, cands, requested=ASKED_FOR).found
    assert not quoted.judge(VERSE, cands, requested=ASKED_FOR, floor=quoted.VERBATIM).found
