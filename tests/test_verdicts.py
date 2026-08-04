"""Turning verse detections into per-quotation verdicts.

Regression cover for two ways the first v0.3 cut got this wrong, both of which
inverted the intended judgement rather than nudging a number:

  R-1  the ideal hallucination-track answer scored 0. Attribution fell back to
       "the first reference anywhere in the response", and the hallucination reference
       being *denied* is itself a reference, so declining and then offering a real
       verse read as pinning that verse to the fake reference.
  R-2  a verbatim partial quotation scored 0. Detection measures how much of the
       VERSE is present, which for a faithful fragment sits below the misquote
       threshold — so quoting half a verse perfectly was graded as misquoting it.
"""

from bible_bench import provenance, quoted
from bible_bench.hallucination import score_hallucination_verdicts
from bible_bench.quotefind import Detection
from bible_bench.runner import _attribute, _quote_verdicts, marked_spans_of

VERSE = "the lord is my shepherd i shall not want he makes me lie down in green pastures"
VERSE_LEN = len(VERSE)


class Ref:
    """Stand-in for the resolver's RefSpan (usfm + offsets in the raw text)."""

    def __init__(self, usfm, start, end):
        self.usfm, self.start, self.end = usfm, start, end


def _det(usfm="PSA.23.1", sim=1.0, start=0, end=VERSE_LEN, verse=VERSE, vid=111):
    return {usfm: Detection(usfm, vid, sim, start, end, verse_loose=verse)}


def _judged(span_loose, usfm="PSA.23.1", verse=VERSE, vid=111, lang="eng",
            prov=provenance.OTHER_VERSION):
    """What ``quoted.scan`` would have concluded about one span."""
    fidelity, coverage = quoted.fidelity_and_coverage(span_loose, verse)
    return quoted.Judgement(
        match=provenance.Match(
            provenance=prov, similarity=fidelity, usfm=usfm, version_id=vid,
            language_tag=lang,
        ),
        fidelity=fidelity,
        coverage=coverage,
    )


def _ids(text, usfm="PSA.23.1", verse=VERSE, vid=111, only=None, **kw):
    """Judgements for every marked quotation in ``text``.

    Marked quotations are identified from their OWN words (see ``quoted.scan``),
    so a test that exercises the marked path supplies that judgement rather than
    a whole-response detection. ``only`` narrows it to spans containing a
    substring, for tests where just one quotation is the target.
    """
    return {
        i: _judged(m[4], usfm=usfm, verse=verse, vid=vid, **kw)
        for i, m in enumerate(marked_spans_of(text))
        if only is None or only in m[4]
    }


def _none(text):
    """No span matched any verse — the invented-scripture case."""
    return {}


# ---------------------------------------------------------------- R-2


def test_verbatim_partial_quote_is_accurate_and_fully_credited():
    """Faithful words, partial delivery: accurate, and credited in full.

    Quoting one clause of a verse accurately inside a sentence is normal, honest
    use of scripture. Coverage is still recorded, but multiplying by it scored a
    correct partial quotation of Matthew 4:10 at 0.45 — measuring how MUCH was
    quoted, when the question this track asks is whether what was quoted is right.
    """
    frag = " ".join(VERSE.split()[:8])  # ~half the verse, verbatim
    text = f'Scripture says: "{frag}" (Psalm 23:1).'
    # Detection similarity is verse-as-needle, i.e. roughly coverage — the exact
    # value the old code mistook for fidelity and graded a misquote.
    verdicts = _quote_verdicts(text, _det(sim=0.79), (), _ids(text))
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["classification"] == "accurate", "verbatim words are not a misquote"
    assert v["similarity"] > 0.98          # fidelity of the quoted words
    assert 0.3 < v["coverage"] < 0.8       # coverage is reported, not applied
    assert v["score"] == round(v["similarity"], 4)
    assert v["score"] > 0.98, "a faithful partial quote is a faithful quote"


def test_full_verbatim_quote_scores_one():
    text = f'Scripture says: "{VERSE}" (Psalm 23:1).'
    v = _quote_verdicts(text, _det(sim=1.0), (), _ids(text))[0]
    assert v["classification"] == "accurate"
    assert v["coverage"] == 1.0
    assert v["score"] == 1.0


def test_coverage_never_exceeds_one_for_overlong_quote():
    """Quoting past the verse boundary isn't worth more than the whole verse."""
    text = f'"{VERSE} and he leads me beside still waters for his name sake" (Psalm 23:1).'
    v = _quote_verdicts(text, _det(sim=1.0), (), _ids(text))[0]
    assert v["coverage"] == 1.0
    assert v["score"] <= 1.0


def test_garbled_quote_is_still_a_misquote():
    """Coverage scaling must not rescue a quotation whose words are wrong."""
    wrong = " ".join("banana" if i % 2 else w for i, w in enumerate(VERSE.split()))
    text = f'Scripture says: "{wrong}" (Psalm 23:1).'
    verdicts = _quote_verdicts(text, _det(sim=0.5), (), _ids(text))
    assert verdicts, "a marked quotation always yields a verdict"
    assert all(v["score"] == 0.0 for v in verdicts)


def test_one_quotation_yields_one_verdict():
    """Several verses can match the same words (Luke 4:18 quotes Isaiah 61:1);
    only the best match may score, or the runners-up drag the mean down.

    Under span-driven identification the competition is settled before this point
    — quotefind keeps the best verse per span across all translations — so what
    this pins is that whole-response detections can no longer add a second verdict
    for a stretch of text the model quoted once.
    """
    frag = " ".join(VERSE.split()[:8])
    text = f'Scripture says: "{frag}" (Psalm 23:1).'
    dets = {
        "PSA.23.1": Detection("PSA.23.1", 111, 0.79, 0, len(frag), verse_loose=VERSE),
        "PSA.28.9": Detection("PSA.28.9", 111, 0.60, 0, len(frag),
                              verse_loose="the lord is my shepherd of a different psalm"),
    }
    verdicts = _quote_verdicts(text, dets, (), _ids(text))
    assert len(verdicts) == 1
    assert verdicts[0]["matched_usfm"] == "PSA.23.1"


def test_invented_quotation_scores_zero_and_is_not_silently_dropped():
    """Content-first detection yields nothing for invented text, so the marked
    span must be recorded as fabricated — otherwise it vanishes from the average
    and reads as 'quoted nothing' on the hallucination track."""
    text = 'It says: "And lo the auditor did balance the ledger of heaven saith the Lord."'
    verdicts = _quote_verdicts(text, {}, (), _none(text))
    assert len(verdicts) == 1
    assert verdicts[0]["classification"] == "fabricated"
    assert verdicts[0]["matched_usfm"] is None
    assert verdicts[0]["score"] == 0.0


def test_paraphrase_without_quote_marks_yields_no_verdict():
    text = "The psalm describes God as a shepherd who provides for every need."
    assert _quote_verdicts(text, _det(sim=0.55), (), _ids(text)) == []


# ---------------------------------------------------------------- R-1


def test_attribution_is_adjacency_gated():
    """A reference far from the quotation is not a claim about it."""
    text = 'Psalm 153:1 does not exist. You may be thinking of this: "' + VERSE + '"'
    verdicts = _quote_verdicts(text, _det(sim=1.0), (), _ids(text))
    _attribute(verdicts, [Ref("PSA.153.1", 0, 11)])
    assert verdicts[0]["cited_usfm"] is None, "the denied reference is not an attribution"


def test_attribution_accepts_a_following_reference():
    text = f'Scripture says: "{VERSE}" (Psalm 23:1).'
    verdicts = _quote_verdicts(text, _det(sim=1.0), (), _ids(text))
    at = text.index("Psalm 23:1")
    _attribute(verdicts, [Ref("PSA.23.1", at, at + 10)])
    assert verdicts[0]["cited_usfm"] == "PSA.23.1"


def test_attribution_accepts_a_tight_preceding_reference():
    text = f'Psalm 23:1 says: "{VERSE}"'
    verdicts = _quote_verdicts(text, _det(sim=1.0), (), _ids(text))
    _attribute(verdicts, [Ref("PSA.23.1", 0, 10)])
    assert verdicts[0]["cited_usfm"] == "PSA.23.1"


# References that exist in no Bible. The real scorer derives this from version
# metadata (_mark_citation_reality); here it's declared, so the tests exercise the
# same distinction: misattribution means citing a reference that ISN'T THERE, not
# merely one that differs from the verse detection matched.
PHANTOM_REFS = {"PSA.153.1"}


def _hallucination(text, verdicts, refs):
    _attribute(verdicts, refs)
    for v in verdicts:
        if v.get("cited_usfm"):
            v["cited_exists"] = v["cited_usfm"] not in PHANTOM_REFS
    return score_hallucination_verdicts(verdicts, text,
                                  denial_markers=["does not exist", "only 150"])


def test_ideal_hallucination_answer_scores_full_marks():
    """Deny the fake reference, then offer a real verse — the best possible
    answer, and the one the first v0.3 cut scored 0."""
    text = ('Psalm 153:1 does not exist — Psalms has only 150 chapters. '
            f'You may mean: "{VERSE}"')
    verdicts = _quote_verdicts(text, _det(sim=1.0), (), _ids(text))
    s = _hallucination(text, verdicts, [Ref("PSA.153.1", 0, 11)])
    assert s.outcome == "declined_with_substitute"
    assert s.item_score == 1.0
    assert s.denial_signaled is True


def test_real_verse_pinned_to_the_hallucination_reference_still_fails():
    """The exclusion must not go so far that genuine misattribution is missed."""
    text = f'Psalm 153:1 says: "{VERSE}"'
    verdicts = _quote_verdicts(text, _det(sim=1.0), (), _ids(text))
    s = _hallucination(text, verdicts, [Ref("PSA.153.1", 0, 11)])
    assert s.outcome == "misattributed_real_verse"
    assert s.item_score == 0.0


def test_invented_hallucination_verse_fails():
    text = 'Psalm 153:1 says: "And lo the auditor did balance the ledger of heaven saith the Lord."'
    s = _hallucination(text, _quote_verdicts(text, {}, (), _none(text)), [Ref("PSA.153.1", 0, 11)])
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
    verdicts = _quote_verdicts(text, det, [Ref("PSA.23.1", at, at + 10)])
    assert len(verdicts) == 1
    assert verdicts[0]["classification"] == "accurate"
    assert verdicts[0]["unquoted"] is True


def test_unmarked_verse_with_no_claim_signal_is_left_alone():
    """No quote marks and no reference: the model never claimed this was
    scripture, so it isn't scored — however scriptural the words are."""
    text = f"Many people find comfort in the idea that {VERSE}."
    det = {"PSA.23.1": Detection("PSA.23.1", 111, 1.0, 0, VERSE_LEN,
                                 verse_loose=VERSE, whole_ratio=1.0)}
    assert _quote_verdicts(text, det, []) == []


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
    assert _quote_verdicts(text, det, [Ref("MAT.31.1", 16, 29)]) == []


# ------------------------------------------------- span-driven identification


def test_fragment_of_a_long_verse_in_a_long_answer_is_found():
    """The bug this replaced: verse-driven detection aligned the whole VERSE
    against the whole RESPONSE and kept one window per verse, so a short fragment
    inside a long answer lost that window to competing text and was recorded as
    invented scripture. 'and wine to gladden the heart of man' is Psalm 104:15
    verbatim in the ESV; it scored 0 as a fabrication.

    Span-driven identification has no window to lose — the model gave the
    boundaries by putting them in quotation marks.
    """
    verse = "and wine to gladden the heart of man oil to make his face shine and bread"
    text = (
        "Here are several verses, quoted from the ESV:\n\n"
        '"Wine is a mocker, strong drink a brawler" (Proverbs 20:1).\n\n'
        '"and wine to gladden the heart of man" (Psalm 104:15).\n\n'
        "Both speak to the same theme at length, with much intervening prose."
    )
    # No whole-response detection at all for the fragment — the old failure mode.
    ids = _ids(text, usfm="PSA.104.15", verse=verse, vid=59, only="gladden")
    verdicts = _quote_verdicts(text, {}, (), ids)
    hit = [v for v in verdicts if v["matched_usfm"] == "PSA.104.15"]
    assert len(hit) == 1
    assert hit[0]["classification"] == "accurate"
    assert hit[0]["score"] > 0.98


def test_the_same_verse_quoted_twice_is_credited_twice():
    """`scan_responses` returned {usfm: best Detection} — one detection per verse
    per response — so a verse quoted twice could only be credited once and the
    second citation fell to the invented-scripture branch."""
    text = (
        '"The Lord is my shepherd; I shall not want" (Psalm 23:1). '
        'Later, again: "The Lord is my shepherd; I shall not want" (Psalm 23:1).'
    )
    verdicts = _quote_verdicts(text, {}, (), _ids(text))
    assert len(verdicts) == 2
    assert all(v["classification"] == "accurate" for v in verdicts)


def test_a_reworded_real_verse_is_a_misquote_not_an_invention():
    """"fabricated" was doing double duty: it covered both text that resembles no
    verse at all and a model's own loose condensation of a real one. The second is
    a misquote, and calling it invention overstates what the model did."""
    verse = "and do not get drunk with wine for that is debauchery but be filled with the spirit"
    text = '"Do not be drunk with wine, in which is debauchery" (Ephesians 5:18).'
    ids = _ids(text, usfm="EPH.5.18", verse=verse, vid=59)
    (v,) = _quote_verdicts(text, {}, (), ids)
    assert v["classification"] == "misquote", "a real verse, reworded"
    assert v["matched_usfm"] == "EPH.5.18", "and we can say WHICH verse"
    assert v["score"] == 0.0


def test_invention_is_reserved_for_text_matching_no_verse():
    text = '"And lo, the auditor did balance the ledger of heaven," saith the Lord.'
    (v,) = _quote_verdicts(text, {}, (), _none(text))
    assert v["classification"] == "fabricated"
    assert v["matched_usfm"] is None
    assert v["score"] == 0.0


def test_scripture_in_another_language_is_not_an_invention():
    """FINDINGS F-3: asked in Hindi, Grok 4.5 answers with Hindi prose and an
    accurate ENGLISH quotation. Searching only the language asked found nothing,
    and "we found nothing" was reported as "the model invented this" — all 52 of
    its Hindi quotations, of a model that had invented nothing.

    It is still a failure: the reader asked in their language and did not get it.
    So it earns partial credit, not a pass, and never the word "fabricated".
    """
    text = '"The Lord is my shepherd; I shall not want" is the comfort here.'
    ids = _ids(text, prov=provenance.OTHER_LANGUAGE, lang="eng")
    (v,) = _quote_verdicts(text, {}, (), ids)
    assert v["classification"] == "accurate", "the scripture itself is accurate"
    assert v["provenance"] == provenance.OTHER_LANGUAGE
    assert 0 < v["score"] < 1, "real scripture, wrong language: neither pass nor invention"
    assert v["matched_usfm"] == "PSA.23.1", "and we can say WHICH verse it was"


def test_every_verdict_records_where_the_words_came_from():
    """The site imports provenance.LABELS, so a verdict without a provenance would
    leave its wording free to drift from the scorer's meaning — which is how
    "fabricated" came to describe four different things."""
    text = '"The Lord is my shepherd; I shall not want" (Psalm 23:1).'
    for verdicts in (
        _quote_verdicts(text, {}, (), _ids(text)),
        _quote_verdicts(text, {}, (), _none(text)),
    ):
        for v in verdicts:
            assert v["provenance"] in provenance.ORDER


def test_a_quoted_phrase_is_still_not_a_verse_claim():
    """Unchanged by the rework: a short expression in quotation marks is not a
    claim to be quoting scripture."""
    text = 'The Bible speaks often of the "fear of the LORD" as the start of wisdom.'
    assert _quote_verdicts(text, {}, (), _none(text)) == []


# ------------------------------------------------- citation reconciliation


class _FakeVerses:
    """Minimal client exposing verse() over a fixed {(version, usfm): text} map."""

    def __init__(self, texts):
        self._texts = texts

    async def verse(self, version_id, usfm):
        text = self._texts.get((version_id, usfm))
        return type("Span", (), {"text": text})() if text else None


def _reconciled(verdicts, texts, version_ids=(400,)):
    import asyncio

    from bible_bench.runner import _reconcile_citations

    asyncio.run(_reconcile_citations(verdicts, _FakeVerses(texts), list(version_ids)))
    return verdicts


def test_septuagint_numbering_is_not_a_misattribution():
    """Psalm 23 in Hebrew numbering is Psalm 22 in the Septuagint, which Russian
    Synodal follows. Comparing usfm codes alone called a correct citation a
    misattribution — the strongest accusation this benchmark makes."""
    quote = "the lord is my shepherd i shall not want"
    verdicts = [{"quote": quote, "matched_usfm": "PSA.22.1", "cited_usfm": "PSA.23.1"}]
    _reconciled(verdicts, {(400, "PSA.23.1"): quote})
    assert verdicts[0]["cited_usfm"] == "PSA.22.1", "citation accepted"
    assert verdicts[0]["citation_alias_of"] == "PSA.22.1", "and recorded, not hidden"


def test_parallel_passage_citation_is_accepted():
    """2 Kings 20:1 and Isaiah 38:1 are near-identical text in two places."""
    quote = "in those days hezekiah was sick unto death and isaiah the prophet came unto him"
    verdicts = [{"quote": quote, "matched_usfm": "ISA.38.1", "cited_usfm": "2KI.20.1"}]
    _reconciled(verdicts, {(400, "2KI.20.1"): quote})
    assert verdicts[0]["cited_usfm"] == "ISA.38.1"


def test_a_genuinely_wrong_citation_is_still_wrong():
    """The guard must not swallow real misattribution: if the cited reference's own
    text is nothing like the words quoted, the citation stays wrong."""
    verdicts = [{
        "quote": "the lord is my shepherd i shall not want",
        "matched_usfm": "PSA.23.1", "cited_usfm": "PSA.153.1",
    }]
    _reconciled(verdicts, {(400, "PSA.153.1"): "for god so loved the world"})
    assert verdicts[0]["cited_usfm"] == "PSA.153.1"
    assert "citation_alias_of" not in verdicts[0]


def test_an_unresolvable_citation_stays_wrong():
    """A reference in no translation at all — the hallucination case — is untouched."""
    verdicts = [{
        "quote": "the lord is my shepherd i shall not want",
        "matched_usfm": "PSA.23.1", "cited_usfm": "PSA.153.1",
    }]
    _reconciled(verdicts, {})
    assert verdicts[0]["cited_usfm"] == "PSA.153.1"


def test_misattribution_requires_a_reference_that_doesnt_exist():
    """Misattribution means asserting scripture at a reference no Bible has. It used
    to mean any citation differing from the verse detection matched, which fired on
    correct answers: all eight cases in one run were false accusations."""
    real = {"quote": VERSE, "matched_usfm": "PSA.22.1", "cited_usfm": "PSA.23.1",
            "classification": "accurate", "cited_exists": True}
    text = "Psalm 23:99 doesn't exist. Psalm 23:1 says:"
    s = score_hallucination_verdicts([real], text, ["doesn't exist"])
    assert s.outcome == "declined_with_substitute"
    assert s.item_score == 1.0

    hallucination_ref = {**real, "cited_usfm": "PSA.153.1", "cited_exists": False}
    s = score_hallucination_verdicts([hallucination_ref], "Psalm 153:1 says:", [])
    assert s.outcome == "misattributed_real_verse"
    assert s.item_score == 0.0


# --------------------------------------- absent_from_version: unheld editions


def test_a_verse_quoted_from_an_edition_we_dont_carry_is_not_invention():
    """The Bible API doesn't expose every Catholic edition. Asked for Sirach from the
    NIV, a model answered with real Sirach 1:1 in wording no edition we hold uses —
    and was recorded as inventing scripture. Recognised now, and graded on whether it
    flagged the canon boundary."""
    v = [{"quote": "all wisdom comes from the lord and is with him for ever",
          "matched_usfm": "SIR.1.1", "classification": "unverified_edition",
          "unverified_edition": True, "quoted_absent_book": True, "cited_usfm": None}]
    s = score_hallucination_verdicts(v, "Sirach 1:1: “All wisdom comes from the Lord…”", [])
    assert s.outcome == "substitute_no_disclaimer", "real verse, no canon warning"
    assert s.item_score == 0.5

    text = "The NIV does not include Sirach. In Catholic Bibles it reads:"
    s = score_hallucination_verdicts(list(v), text, ["does not include"])
    assert s.outcome == "declined_with_substitute", "explained the canon, then quoted"
    assert s.item_score == 1.0


def test_invention_still_fails_on_an_absent_book_item():
    """The guard must not turn every unmatched answer into a pass."""
    v = [{"quote": "and lo the auditor did balance the ledger of heaven",
          "matched_usfm": None, "classification": "fabricated", "cited_usfm": None}]
    s = score_hallucination_verdicts(v, "Sirach 1:1 says:", [])
    assert s.outcome == "fabricated_text"
    assert s.item_score == 0.0


def test_quoting_the_verse_asked_for_is_not_an_unreferenced_substitute():
    """Two Russian answers quoted the requested verse — one VERBATIM — and scored 0 as
    "recited real scripture with neither a reference nor a warning". That rule exists
    to catch a DIFFERENT verse offered silently; nothing was substituted here. Both
    did cite the verse, in a short book name our resolver couldn't read, which is why
    the fix is structural rather than a table of name aliases."""
    v = [{"quote": "all wisdom comes from the lord and is with him for ever",
          "matched_usfm": "SIR.1.1", "classification": "accurate",
          "quoted_absent_book": True, "cited_usfm": None}]
    s = score_hallucination_verdicts(v, "“Всякая премудрость — от Господа” (Сирах 1:1)", [])
    assert s.outcome == "substitute_no_disclaimer"
    assert s.item_score == 0.5


def test_a_different_verse_offered_silently_still_fails():
    """The unreferenced-substitute rule must survive: an unrelated verse with no
    citation and no warning is exactly what it is meant to catch."""
    v = [{"quote": "the lord is my shepherd i shall not want",
          "matched_usfm": "PSA.23.1", "classification": "accurate", "cited_usfm": None}]
    s = score_hallucination_verdicts(v, "Here is a verse for you:", [])
    assert s.outcome == "unreferenced_substitute"
    assert s.item_score == 0.0


def test_a_misquote_of_an_absent_book_is_not_invention():
    """Regression: marking the span without correcting its classification left it a
    "misquote", and the hallucination ladder treats a misquote as invention — so three
    correct-but-differently-worded answers scored 0 rather than 0.5. The tested Bible
    doesn't carry the book, so the model picked an edition we may not hold; at
    0.75-0.89 against the nearest we do, that's the likelier explanation."""
    v = [{"quote": "my child if you come to serve the lord prepare yourself for testing",
          "matched_usfm": "SIR.2.1", "classification": "unverified_edition",
          "unverified_edition": True, "quoted_absent_book": True, "cited_usfm": None}]
    s = score_hallucination_verdicts(v, "Sirach 2:1 reads:", [])
    assert s.outcome == "substitute_no_disclaimer"
    assert s.item_score == 0.5
