"""Content-first scripture detection: identify a span by content, not by the
reference printed next to it, across every translation of a language.

No real verse text appears here (none may be committed). The fixtures instead
reproduce the SHAPES that made real quotations undetectable — a combining accent,
a diacritic, an agglutinated verb ending — using the fake "1 Testium" corpus.
"""

import asyncio

from bible_bench import provenance, quoted
from bible_bench.normalize import normalize
from bible_bench.quotefind import (
    MIN_SHARED_FRACTION,
    Span,
    VersionIndex,
    fidelity_and_coverage,
    ngrams,
    similarity,
)

# Two "translations" of the same fake verses, differing in wording the way real
# translations do — the point being that a faithful quote of EITHER must be
# recognised as faithful.
V1 = {
    "TES.1.1": "In the beginning the maker shaped the heavens and the earth by his word",
    "TES.1.2": "And the maker said let there be light upon the face of the waters",
    "TES.2.1": "Blessed is the one who walks not in the counsel of the scornful",
}
V2 = {
    "TES.1.1": "At the first the creator formed the heavens and the earth through his word",
    "TES.1.2": "And the creator spoke saying let there be light over the face of the deep",
    "TES.2.1": "Happy is the person who does not walk in the counsel of the mocking",
}
CJK = {
    "TES.1.1": "起初造物者藉着他的话语创造了天和地",
    "TES.1.2": "造物者说要有光照在水面上",
}


def test_similarity_exact_and_partial():
    assert similarity("a b c d e", "a b c d e") == 1.0
    # A faithful FRAGMENT of a verse is a faithful quotation of that fragment.
    assert similarity("the heavens and the earth", V1["TES.1.1"].lower()) > 0.95
    assert similarity("", "anything") == 0.0


def test_similarity_prefers_the_fairer_reading():
    """Near-equal-length spans shouldn't be penalised by window framing."""
    quote = "woe to those who decree iniquitous decrees and who write oppressive statutes"
    verse = "woe to those who make iniquitous decrees who write oppressive statutes"
    # Two substituted words; must land in the "minor" band, not below it.
    assert quoted.NEAR <= similarity(quote, verse) < quoted.VERBATIM


def test_ngrams_are_characters_for_every_script():
    """One tokenisation, no spaced/unspaced fork to guess wrong about."""
    w = ngrams("one two three four five")
    assert all(len(g) == 6 for g in w)
    assert "onetwo" in w
    c = ngrams("起初造物者藉着他的话语")
    assert all(len(g) == 6 for g in c)
    assert "起初造物者藉" in c


def test_fidelity_and_coverage_separate_two_questions():
    verse = V1["TES.1.1"].lower()
    half = "in the beginning the maker shaped the heavens"
    fidelity, coverage = fidelity_and_coverage(half, verse)
    assert fidelity > 0.95, "a faithful fragment is faithful"
    assert coverage < 0.7, "but only part of the verse arrived"
    # Quoting past the end is not credited above a whole verse.
    _f, over = fidelity_and_coverage(verse + " " + verse, verse)
    assert over == 1.0
    assert fidelity_and_coverage("", verse) == (0.0, 0.0)


def test_index_identifies_the_right_verse_without_any_reference():
    idx = VersionIndex(1, V1)
    usfm, sim = idx.best("in the beginning the maker shaped the heavens and the earth by his word")
    assert usfm == "TES.1.1"
    assert sim > quoted.VERBATIM


def test_index_makes_no_claim_about_unrelated_text():
    idx = VersionIndex(1, V1)
    usfm, sim = idx.best("the quarterly earnings report exceeded analyst expectations")
    assert usfm is None or sim < quoted.RECOGNISABLE


def test_proposal_survives_scattered_one_character_differences():
    """The bug that produced hundreds of false "invented scripture" verdicts.

    An edition writes two words with accents the model omits. Under word 4-grams
    each difference destroys the four grams containing it, so a twelve-word verse
    differing at words 4 and 9 keeps exactly ONE shared gram against a floor of
    two — and a verse otherwise word-for-word is never compared at all. That is
    the real geometry of Russian 1 Peter 5:7, whose edition writes the verb with a
    stress mark and another word with a diaeresis: similarity 0.972, one shared
    4-gram, graded an invention.

    Stage 1 is a speed optimization, so what it declines to propose it silently
    decides. This asserts it proposes.
    """
    edition = {"TES.3.1": "Cast all your cáres upon him because he provídes for you always"}
    plain = "cast all your cares upon him because he provides for you always"
    idx = VersionIndex(1, edition)
    assert "TES.3.1" in idx.propose(plain), "a near-identical verse must be considered"
    usfm, sim = idx.best(plain)
    assert usfm == "TES.3.1"
    assert sim >= quoted.NEAR


def test_proposal_survives_whole_token_changes():
    """Agglutinative morphology changes whole words, which is fatal to word
    n-grams: Korean "맡기라" vs "맡겨 버리라" left one shared 4-gram out of six and
    a real quotation at 0.806 similarity was called invented."""
    edition = {"TES.4.1": "Entrust every worry unto him for he watches over you"}
    reworded = "entrust every worry to him for he watches you"
    idx = VersionIndex(1, edition)
    assert "TES.4.1" in idx.propose(reworded)
    _usfm, sim = idx.best(reworded)
    assert sim >= quoted.RECOGNISABLE, "recognisable, so a misquote — not an invention"


def test_proposal_bar_scales_to_the_shorter_side():
    """One absolute floor cannot serve a short span and a whole answer at once;
    the bar is a fraction of whichever side offers fewer grams."""
    idx = VersionIndex(1, V1)
    short = "the counsel of the scornful"
    assert len(ngrams(short)) < 40
    assert "TES.2.1" in idx.propose(short), "a short quotation must stay findable"
    assert 0 < MIN_SHARED_FRACTION < 1


def test_present_finds_an_unmarked_quote_inside_prose():
    """No quotation marks anywhere — detection is verse-driven, so it still
    finds the verse embedded in surrounding commentary."""
    idx = VersionIndex(1, V1)
    response = (
        "Many readers find comfort here. In the beginning the maker shaped the heavens "
        "and the earth by his word, which speaks to divine intent, as commentators note."
    )
    found = idx.present(response.lower(), floor=quoted.RECOGNISABLE)
    assert "TES.1.1" in found


def test_present_ignores_a_response_with_no_scripture():
    idx = VersionIndex(1, V1)
    assert idx.present(
        "this paragraph discusses supply chain logistics only", floor=quoted.RECOGNISABLE
    ) == {}


def test_cjk_needs_no_special_case():
    idx = VersionIndex(48, CJK)
    usfm, sim = idx.best("起初造物者藉着他的话语创造了天和地")
    assert usfm == "TES.1.1"
    assert sim > quoted.VERBATIM


class FakeClient:
    """Serves the fake translations the way BibleClient would."""

    CORPUS = {1: V1, 2: V2, 48: CJK}

    async def version(self, version_id):
        return {
            "books": [
                {"usfm": "GEN", "chapters": [{"usfm": "GEN.1", "canonical": True}]},
            ]
        }

    async def chapter_verses(self, version_id, chapter_usfm):
        return self.CORPUS[version_id]


ENG1 = provenance.Source(version_id=1, language_tag="eng", version_abbrev="V1")
ENG2 = provenance.Source(version_id=2, language_tag="eng", version_abbrev="V2")
ZHO = provenance.Source(version_id=48, language_tag="zho", version_abbrev="CJK")


def _scan(editions, spans, requested):
    return asyncio.run(
        quoted.scan(FakeClient(), editions, {}, spans, requested=requested)
    )


def test_scan_picks_the_translation_the_model_actually_quoted():
    """The regression this module exists for: a faithful quote of a translation
    other than the 'expected' one must be identified as faithful, and attributed
    to the translation it really came from."""
    spans = [
        # Verbatim from V2 — must not be judged against V1 and marked a misquote.
        Span(key="a", item_id="i1", text=V2["TES.1.1"], quoted=True),
        Span(key="b", item_id="i1", text=V1["TES.2.1"], quoted=True),
    ]
    no_edition_asked = {s.key: provenance.Source(None, "eng") for s in spans}
    _det, got = _scan([ENG1, ENG2], spans, no_edition_asked)
    assert got["a"].match.usfm == "TES.1.1"
    assert got["a"].match.version_id == 2, "attribute to the translation actually quoted"
    assert got["a"].fidelity > quoted.VERBATIM
    assert got["b"].match.version_id == 1
    assert got["a"].band == "verbatim"


def test_scan_reports_nothing_for_invented_text():
    spans = [Span(key="x", item_id="i", quoted=True,
                  text="And the auditor spake unto the ledger, saying")]
    _det, got = _scan([ENG1, ENG2], spans, {"x": provenance.Source(None, "eng")})
    assert "x" not in got or not got["x"].found


def test_scan_names_a_match_in_another_language_as_such():
    """FINDINGS F-3: asked in one language, the model quotes accurately in
    another. Searching only the language asked reported that as invention; all 52
    of Grok 4.5's Hindi quotations were graded "invented a verse"."""
    spans = [Span(key="q", item_id="i", text=V1["TES.1.1"], quoted=True)]
    asked_in_chinese = {"q": provenance.Source(version_id=48, language_tag="zho")}
    # Searching only the language asked: nothing found, which would read as invention.
    _det, narrow = _scan([ZHO], spans, asked_in_chinese)
    assert "q" not in narrow or not narrow["q"].found
    # Searching wider: real scripture, wrong language. A different claim entirely.
    _det, wide = _scan([ZHO, ENG1], spans, asked_in_chinese)
    assert wide["q"].found
    assert wide["q"].match.provenance == provenance.OTHER_LANGUAGE
    assert wide["q"].match.language_tag == "eng"


def test_scan_prefers_the_right_bible_over_a_better_match_elsewhere():
    """Provenance outranks fidelity, or a model gets credit for answering a
    question it wasn't asked."""
    spans = [Span(key="q", item_id="i", text=V1["TES.1.1"], quoted=True)]
    asked_for_v2 = {"q": provenance.Source(version_id=2, language_tag="eng")}
    _det, got = _scan([ENG1, ENG2], spans, asked_for_v2)
    # V1 is the verbatim match; V2 is the same verse, differently worded. The
    # edition ASKED FOR wins even though the other matches better.
    assert got["q"].match.version_id == 2
    assert got["q"].match.provenance == provenance.REQUESTED


def test_the_batched_search_and_the_pure_judgement_agree():
    """`scan` is the batched form of `judge`, not a second implementation of it.

    They must not be able to disagree: one is what production calls and the other
    is what the unit tests pin, so a divergence would mean the tested behaviour is
    not the shipped behaviour. `scan` narrows candidates to the strongest per
    provenance class and hands the actual choice to `judge`; this asserts the
    result is what `judge` alone would have said.
    """
    reworded = "at the first the creator formed the heavens and the earth by his word"
    spans = [Span(key="a", item_id="i", text=reworded, quoted=True)]
    asked_for_v1 = {"a": provenance.Source(version_id=1, language_tag="eng")}
    _det, got = _scan([ENG1, ENG2, ZHO], spans, asked_for_v1)

    direct = quoted.judge(
        normalize(reworded, "loose"),
        [
            quoted.Candidate(ENG1, "TES.1.1", normalize(V1["TES.1.1"], "loose")),
            quoted.Candidate(ENG2, "TES.1.1", normalize(V2["TES.1.1"], "loose")),
        ],
        requested=asked_for_v1["a"],
    )
    assert got["a"].match.version_id == direct.match.version_id
    assert got["a"].match.provenance == direct.match.provenance
    assert abs(got["a"].fidelity - direct.fidelity) < 1e-9
    assert abs(got["a"].coverage - direct.coverage) < 1e-9
