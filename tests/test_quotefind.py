"""Content-first scripture detection: identify a span by content, not by the
reference printed next to it, across every translation of a language."""

import asyncio

from bible_bench.quotefind import (
    IDENTIFY_FLOOR,
    Span,
    VersionIndex,
    identify_all,
    is_unspaced,
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
    assert 0.90 <= similarity(quote, verse) < 0.98


def test_ngrams_word_and_char_modes():
    w = ngrams("one two three four five", unspaced=False)
    assert "one two three four" in w and "two three four five" in w
    c = ngrams("起初造物者藉着他的话语", unspaced=True)
    assert all(len(g) == 8 for g in c)
    assert any("起初造物者" in g for g in c)


def test_is_unspaced_detects_cjk():
    assert is_unspaced("起初造物者藉着他的话语创造了天和地")
    assert not is_unspaced("In the beginning the maker shaped the heavens")


def test_index_identifies_the_right_verse_without_any_reference():
    idx = VersionIndex(1, V1, unspaced=False)
    usfm, sim = idx.best("in the beginning the maker shaped the heavens and the earth by his word")
    assert usfm == "TES.1.1"
    assert sim > 0.98


def test_index_makes_no_claim_about_unrelated_text():
    idx = VersionIndex(1, V1, unspaced=False)
    usfm, sim = idx.best("the quarterly earnings report exceeded analyst expectations")
    assert usfm is None or sim < IDENTIFY_FLOOR


def test_present_finds_an_unmarked_quote_inside_prose():
    """No quotation marks anywhere — detection is verse-driven, so it still
    finds the verse embedded in surrounding commentary."""
    idx = VersionIndex(1, V1, unspaced=False)
    response = (
        "Many readers find comfort here. In the beginning the maker shaped the heavens "
        "and the earth by his word, which speaks to divine intent, as commentators note."
    )
    found = idx.present(response.lower())
    assert "TES.1.1" in found
    assert found["TES.1.2"] if "TES.1.2" in found else True  # only assert the target


def test_present_ignores_a_response_with_no_scripture():
    idx = VersionIndex(1, V1, unspaced=False)
    assert idx.present("this paragraph discusses supply chain logistics only") == {}


def test_unspaced_index_identifies_cjk_verse():
    idx = VersionIndex(48, CJK, unspaced=True)
    usfm, sim = idx.best("起初造物者藉着他的话语创造了天和地")
    assert usfm == "TES.1.1"
    assert sim > 0.98


class FakeClient:
    """Serves the two fake translations the way BibleClient would."""

    CORPUS = {1: V1, 2: V2}

    async def version(self, version_id):
        return {
            "books": [
                {"usfm": "GEN", "chapters": [{"usfm": "GEN.1", "canonical": True}]},
            ]
        }

    async def chapter_verses(self, version_id, chapter_usfm):
        return self.CORPUS[version_id]


def test_identify_all_picks_the_translation_the_model_actually_quoted():
    """The regression this module exists for: a faithful quote of a translation
    other than the 'expected' one must be identified as faithful, and attributed
    to the translation it really came from."""
    client = FakeClient()
    spans = [
        # Verbatim from V2 — must not be judged against V1 and marked a misquote.
        Span(key="a", item_id="i1", text=V2["TES.1.1"], quoted=True),
        # Verbatim from V1.
        Span(key="b", item_id="i1", text=V1["TES.2.1"], quoted=True),
    ]
    got = asyncio.run(identify_all(client, [1, 2], spans))
    assert got["a"].usfm == "TES.1.1"
    assert got["a"].version_id == 2, "should attribute to the translation actually quoted"
    assert got["a"].similarity > 0.98
    assert got["b"].usfm == "TES.2.1"
    assert got["b"].version_id == 1
    assert got["b"].similarity > 0.98


def test_identify_all_reports_nothing_for_invented_text():
    client = FakeClient()
    spans = [Span(key="x", item_id="i", text="And the auditor spake unto the ledger, saying", quoted=True)]
    got = asyncio.run(identify_all(client, [1, 2], spans))
    assert "x" not in got


def test_classification_bands():
    from bible_bench.quotefind import Identification

    assert Identification("A.1.1", 1, 1.0).classification(accurate=0.98, minor=0.90) == "accurate"
    assert Identification("A.1.1", 1, 0.93).classification(accurate=0.98, minor=0.90) == "minor"
    assert Identification("A.1.1", 1, 0.80).classification(accurate=0.98, minor=0.90) == "partial"
