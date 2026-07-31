"""Direct Quotation: answering accurately in the wrong language is not invention.

The reference case is GPT-5.6 Terra declining an in-copyright translation and
offering a different one instead (docs/FINDINGS.md F-1), and MiniMax M3 answering
a Spanish request with the verse in Chinese. Both were graded "invented a verse".

The pass that catches them runs only over answers a same-language search could
not explain, so these tests exercise that second look end to end — including the
versification step, because "the same verse" must mean the same verse and not the
same verse NUMBER.
"""

import asyncio

import pytest
from fake_bible import CJK, LATIN, LATIN_ALT_VERSION, LATIN_NEIGHBOR

from bible_bench.dataset import BenchmarkItem
from bible_bench.runner import score_simple
from bible_bench.yv_client import VerseSpan

# Two languages, one verse. GEN.1.1 exists under every scheme, so the test isolates
# the language question from the versification one (covered separately below).
ENG_A, ENG_B, ZHO = 111, 1, 48
LANGS = {ENG_A: "eng", ENG_B: "eng", ZHO: "zho"}


class FakeClient:
    """Serves one verse in three editions, the way BibleClient would.

    ``vrs`` is per edition so the versification path is really exercised: the
    Chinese edition below follows a scheme that numbers Psalms differently.
    """

    def __init__(self, texts, vrs=None, chapter=None):
        self.texts = texts                      # {version_id: {usfm: text}}
        self.vrs = vrs or {}                    # {version_id: scheme}
        self.chapter = chapter or {}            # {version_id: {usfm: text}} neighbours
        self.asked: list[tuple[int, str]] = []  # every (version, usfm) looked up

    def load_language_versions(self, language_tag, *, include_duplicates=False):
        return [v for v, tag in LANGS.items() if tag == language_tag]

    async def version(self, version_id):
        return {"vrs": self.vrs.get(version_id, "eng"), "books": []}

    async def verse(self, version_id, usfm):
        self.asked.append((version_id, usfm))
        text = self.texts.get(version_id, {}).get(usfm)
        return VerseSpan(usfm, 1, text, usfm) if text else None

    async def chapter_verses(self, version_id, chapter_usfm):
        return self.chapter.get(version_id, {})

    def release_version(self, version_id):
        pass


def _item(version_id, usfm="GEN.1.1", source_usfm="GEN.1.1"):
    return BenchmarkItem(
        id=f"s-{LANGS[version_id]}-{version_id}-{usfm}",
        track="simple",
        language_tag=LANGS[version_id],
        language_name=LANGS[version_id],
        version_id=version_id,
        version_abbrev="X",
        usfm=usfm,
        source_usfm=source_usfm,
        tier="famous",
        template_id="t1",
    )


def _score(client, item, response, *, also=()):
    """Score ``item``, with ``also`` present in the run but unanswered.

    ``also`` matters: the cross-language pass searches the editions the RUN
    covers, taken from its own items. That is deliberate — the benchmark only
    claims to have searched what it tests — but it means a run covering one
    language has no other language to find, so a test needs the second item to
    put that edition in scope, exactly as a real run does.
    """
    items = {item.id: item, **{i.id: i for i in also}}
    responses = [{"item_id": item.id, "response_text": response,
                  "input_tokens": 0, "output_tokens": 0}]
    return asyncio.run(score_simple(items, responses, client))


def test_answering_in_another_language_is_not_invention():
    """Asked for the Chinese edition, answered verbatim from an English one."""
    client = FakeClient({ZHO: {"GEN.1.1": CJK}, ENG_A: {"GEN.1.1": LATIN}})
    (rec,) = _score(client, _item(ZHO), LATIN, also=[_item(ENG_A)])
    assert rec["score"]["grade"] == "other_language"
    assert rec["score"]["item_score"] == 0.25, "real scripture: not zero, not full"
    assert rec["score"]["best_foreign"]["similarity"] > 0.98


def test_a_same_language_edition_is_still_wrong_version_not_wrong_language():
    """The narrower claim wins when it fits: another English Bible is a
    translation mismatch, and calling it a language mismatch would overstate it."""
    client = FakeClient({ENG_A: {"GEN.1.1": LATIN_ALT_VERSION},
                         ENG_B: {"GEN.1.1": LATIN},
                         ZHO: {"GEN.1.1": CJK}})
    (rec,) = _score(client, _item(ENG_A), LATIN)
    assert rec["score"]["grade"] == "wrong_version"


def test_invention_survives_when_no_language_has_it():
    """The pass must not launder every failure into a wrong-language verdict."""
    client = FakeClient({ZHO: {"GEN.1.1": CJK}, ENG_A: {"GEN.1.1": LATIN}})
    (rec,) = _score(client, _item(ZHO),
                    "And the auditor did balance the ledger of heaven, saith the scribe.",
                    also=[_item(ENG_A)])
    assert rec["score"]["grade"] in ("fabricated", "no_attempt")
    assert rec["score"]["item_score"] == 0.0


def test_a_correct_answer_never_reaches_the_second_pass():
    """Cost is proportional to the problem: only answers already graded as
    inventions are re-examined."""
    client = FakeClient({ZHO: {"GEN.1.1": CJK}, ENG_A: {"GEN.1.1": LATIN}})
    (rec,) = _score(client, _item(ZHO), CJK, also=[_item(ENG_A)])
    assert rec["score"]["grade"] in ("perfect", "near_perfect")
    assert not any(v == ENG_A for v, _ in client.asked), "no English edition consulted"


def test_the_second_pass_translates_the_reference_between_schemes():
    """"The same verse" must mean the same verse, not the same verse NUMBER.

    Psalms are renumbered wholesale between the English and Septuagint-derived
    schemes, so looking up the requested code verbatim in a foreign edition
    retrieves a DIFFERENT psalm — and comparing against the wrong psalm would
    report an invention again, one layer further down.
    """
    # The item asks for eng PSA.24.1; an lxx-scheme edition numbers it PSA.23.1.
    client = FakeClient(
        texts={ZHO: {}, ENG_A: {"PSA.24.1": LATIN, "PSA.23.1": LATIN_NEIGHBOR}},
        vrs={ENG_A: "eng", ZHO: "lxx"},
    )
    item = _item(ENG_A, usfm="PSA.24.1", source_usfm="PSA.24.1")
    # The Chinese edition carries nothing here, so nothing is found — the point of
    # the test is which reference was requested of it.
    _score(client, item, "wholly unrelated prose about supply chain logistics",
           also=[_item(ZHO, usfm="PSA.23.1", source_usfm="PSA.24.1")])
    zho_lookups = [u for v, u in client.asked if v == ZHO]
    assert zho_lookups, "the foreign edition should have been consulted"
    assert "PSA.23.1" in zho_lookups, (
        f"expected the lxx numbering of eng PSA.24.1, asked for {zho_lookups}"
    )
    assert "PSA.24.1" not in zho_lookups, "asking the raw code would fetch another psalm"


@pytest.mark.parametrize("scheme", ["eng", "org", "lxx", "rso", "nonsense-scheme"])
def test_the_second_pass_survives_any_scheme(scheme):
    """Genesis 1:1 is Genesis 1:1 under every scheme, so the verdict must not
    depend on which one an edition declares — and an unknown scheme must drop that
    edition quietly rather than sink the run. Scoring a whole run cannot hinge on
    one edition's metadata being a name we recognise."""
    client = FakeClient(
        texts={ZHO: {"GEN.1.1": CJK}, ENG_A: {"GEN.1.1": LATIN}},
        vrs={ENG_A: scheme, ZHO: scheme},
    )
    (rec,) = _score(client, _item(ZHO), LATIN, also=[_item(ENG_A)])
    expected = "fabricated" if scheme == "nonsense-scheme" else "other_language"
    assert rec["score"]["grade"] == expected
