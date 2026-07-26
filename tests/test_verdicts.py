"""Turning verse detections into per-quotation verdicts.

Regression cover for two ways the first v0.3 cut got this wrong, both of which
inverted the intended judgement rather than nudging a number:

  R-1  the ideal hallucination-track answer scored 0. Attribution fell back to
       "the first reference anywhere in the response", and the phantom reference
       being *denied* is itself a reference, so declining and then offering a real
       verse read as pinning that verse to the fake reference.
  R-2  a verbatim partial quotation scored 0. Detection measures how much of the
       VERSE is present, which for a faithful fragment sits below the misquote
       threshold — so quoting half a verse perfectly was graded as misquoting it.
"""

from bible_bench.phantom import score_phantom_verdicts
from bible_bench.quotefind import Detection
from bible_bench.runner import _attribute, _topical_verdicts
from bible_bench.topical import score_topical_verdicts

VERSE = "the lord is my shepherd i shall not want he makes me lie down in green pastures"
VERSE_LEN = len(VERSE)


class Ref:
    """Stand-in for the resolver's RefSpan (usfm + offsets in the raw text)."""

    def __init__(self, usfm, start, end):
        self.usfm, self.start, self.end = usfm, start, end


def _det(usfm="PSA.23.1", sim=1.0, start=0, end=VERSE_LEN, verse=VERSE, vid=111):
    return {usfm: Detection(usfm, vid, sim, start, end, verse_loose=verse)}


# ---------------------------------------------------------------- R-2


def test_verbatim_partial_quote_is_accurate_and_scaled_by_coverage():
    """Faithful words, partial delivery: accurate, credited in proportion."""
    frag = " ".join(VERSE.split()[:8])  # ~half the verse, verbatim
    text = f'Scripture says: "{frag}" (Psalm 23:1).'
    # Detection similarity is verse-as-needle, i.e. roughly coverage — the exact
    # value the old code mistook for fidelity and graded a misquote.
    verdicts = _topical_verdicts(text, _det(sim=0.79))
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["classification"] == "accurate", "verbatim words are not a misquote"
    assert v["similarity"] > 0.98          # fidelity of the quoted words
    assert 0.3 < v["coverage"] < 0.8       # but only part of the verse
    assert v["score"] == round(v["similarity"] * v["coverage"], 4)
    assert v["score"] > 0.0, "a faithful partial quote must not score zero"


def test_full_verbatim_quote_scores_one():
    text = f'Scripture says: "{VERSE}" (Psalm 23:1).'
    v = _topical_verdicts(text, _det(sim=1.0))[0]
    assert v["classification"] == "accurate"
    assert v["coverage"] == 1.0
    assert v["score"] == 1.0


def test_coverage_never_exceeds_one_for_overlong_quote():
    """Quoting past the verse boundary isn't worth more than the whole verse."""
    text = f'"{VERSE} and he leads me beside still waters for his name sake" (Psalm 23:1).'
    v = _topical_verdicts(text, _det(sim=1.0))[0]
    assert v["coverage"] == 1.0
    assert v["score"] <= 1.0


def test_garbled_quote_is_still_a_misquote():
    """Coverage scaling must not rescue a quotation whose words are wrong."""
    wrong = " ".join("banana" if i % 2 else w for i, w in enumerate(VERSE.split()))
    text = f'Scripture says: "{wrong}" (Psalm 23:1).'
    verdicts = _topical_verdicts(text, _det(sim=0.5))
    assert verdicts, "a marked quotation always yields a verdict"
    assert all(v["score"] == 0.0 for v in verdicts)


def test_one_quotation_yields_one_verdict():
    """Several verses can match the same words (Luke 4:18 quotes Isaiah 61:1);
    only the best match may score, or the runners-up drag the mean down."""
    frag = " ".join(VERSE.split()[:8])
    text = f'Scripture says: "{frag}" (Psalm 23:1).'
    dets = {
        "PSA.23.1": Detection("PSA.23.1", 111, 0.79, 0, len(frag), verse_loose=VERSE),
        "PSA.28.9": Detection("PSA.28.9", 111, 0.60, 0, len(frag),
                              verse_loose="the lord is my shepherd of a different psalm"),
    }
    verdicts = _topical_verdicts(text, dets)
    assert len(verdicts) == 1
    assert verdicts[0]["matched_usfm"] == "PSA.23.1"


def test_invented_quotation_scores_zero_and_is_not_silently_dropped():
    """Content-first detection yields nothing for invented text, so the marked
    span must be recorded as fabricated — otherwise it vanishes from the average
    and reads as 'quoted nothing' on the hallucination track."""
    text = 'It says: "And lo the auditor did balance the ledger of heaven saith the Lord."'
    verdicts = _topical_verdicts(text, {})
    assert len(verdicts) == 1
    assert verdicts[0]["classification"] == "fabricated"
    assert verdicts[0]["matched_usfm"] is None
    assert verdicts[0]["score"] == 0.0
    assert score_topical_verdicts(verdicts).item_score == 0.0


def test_paraphrase_without_quote_marks_yields_no_verdict():
    text = "The psalm describes God as a shepherd who provides for every need."
    assert _topical_verdicts(text, _det(sim=0.55)) == []


# ---------------------------------------------------------------- R-1


def test_attribution_is_adjacency_gated():
    """A reference far from the quotation is not a claim about it."""
    text = 'Psalm 153:1 does not exist. You may be thinking of this: "' + VERSE + '"'
    verdicts = _topical_verdicts(text, _det(sim=1.0))
    _attribute(verdicts, [Ref("PSA.153.1", 0, 11)])
    assert verdicts[0]["cited_usfm"] is None, "the denied reference is not an attribution"


def test_attribution_accepts_a_following_reference():
    text = f'Scripture says: "{VERSE}" (Psalm 23:1).'
    verdicts = _topical_verdicts(text, _det(sim=1.0))
    at = text.index("Psalm 23:1")
    _attribute(verdicts, [Ref("PSA.23.1", at, at + 10)])
    assert verdicts[0]["cited_usfm"] == "PSA.23.1"


def test_attribution_accepts_a_tight_preceding_reference():
    text = f'Psalm 23:1 says: "{VERSE}"'
    verdicts = _topical_verdicts(text, _det(sim=1.0))
    _attribute(verdicts, [Ref("PSA.23.1", 0, 10)])
    assert verdicts[0]["cited_usfm"] == "PSA.23.1"


def _phantom(text, verdicts, refs):
    _attribute(verdicts, refs)
    return score_phantom_verdicts(verdicts, text,
                                  denial_markers=["does not exist", "only 150"])


def test_ideal_phantom_answer_scores_full_marks():
    """Deny the fake reference, then offer a real verse — the best possible
    answer, and the one the first v0.3 cut scored 0."""
    text = ('Psalm 153:1 does not exist — Psalms has only 150 chapters. '
            f'You may mean: "{VERSE}"')
    s = _phantom(text, _topical_verdicts(text, _det(sim=1.0)), [Ref("PSA.153.1", 0, 11)])
    assert s.outcome == "declined_with_substitute"
    assert s.item_score == 1.0
    assert s.denial_signaled is True


def test_real_verse_pinned_to_the_phantom_reference_still_fails():
    """The exclusion must not go so far that genuine misattribution is missed."""
    text = f'Psalm 153:1 says: "{VERSE}"'
    s = _phantom(text, _topical_verdicts(text, _det(sim=1.0)), [Ref("PSA.153.1", 0, 11)])
    assert s.outcome == "misattributed_real_verse"
    assert s.item_score == 0.0


def test_invented_phantom_verse_fails():
    text = 'Psalm 153:1 says: "And lo the auditor did balance the ledger of heaven saith the Lord."'
    s = _phantom(text, _topical_verdicts(text, {}), [Ref("PSA.153.1", 0, 11)])
    assert s.outcome == "fabricated_text"
    assert s.item_score == 0.0


# ------------------------------------------------- claim signals (v0.3)
# Presentation is the trigger, not resemblance: biblical-sounding wording is not
# a claim, and judging it as a quotation would be a category error. Two
# language-independent signals count — quotation marks, or an adjacent reference.


def test_unmarked_verse_with_adjacent_reference_is_judged():
    """A reference beside the words is a claim that they are that verse."""
    text = f"As the psalmist writes in Psalm 23:1, {VERSE}, which comforts many."
    at = text.index("Psalm 23:1")
    det = {"PSA.23.1": Detection("PSA.23.1", 111, 1.0, 0, VERSE_LEN,
                                 verse_loose=VERSE, whole_ratio=1.0)}
    verdicts = _topical_verdicts(text, det, [Ref("PSA.23.1", at, at + 10)])
    assert len(verdicts) == 1
    assert verdicts[0]["classification"] == "accurate"
    assert verdicts[0]["unquoted"] is True


def test_unmarked_verse_with_no_claim_signal_is_left_alone():
    """No quote marks and no reference: the model never claimed this was
    scripture, so it isn't scored — however scriptural the words are."""
    text = f"Many people find comfort in the idea that {VERSE}."
    det = {"PSA.23.1": Detection("PSA.23.1", 111, 1.0, 0, VERSE_LEN,
                                 verse_loose=VERSE, whole_ratio=1.0)}
    assert _topical_verdicts(text, det, []) == []


def test_coincidental_phrase_near_a_reference_is_not_a_misquote():
    """The regression from the live run: a French decline mentioning
    "Matthieu 31:1" sat next to the stock phrase "il n'y a pas de", which is also
    inside Lamentations 3:49. Best-window alignment called that a perfect match;
    whole-string comparison puts it at 0.485, so it must not be judged at all."""
    text = "Il n'y a pas de Matthieu 31:1 dans la Bible, car Matthieu ne comporte que 28 chapitres."
    det = {"LAM.3.49": Detection(
        "LAM.3.49", 133, 1.0, 0, 20,
        verse_loose="mes yeux pleurent sans arret il n y a pas de repos",
        whole_ratio=0.485)}
    assert _topical_verdicts(text, det, [Ref("MAT.31.1", 16, 29)]) == []
