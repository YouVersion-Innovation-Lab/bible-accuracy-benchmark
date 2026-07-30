"""Canon is a property of a Bible version, not of the benchmark.

These pin the v0.4 split: ``VerseRef.parse`` answers syntax, the client answers
membership, and the canon tables are labels that gate nothing. The bug they guard
against is specific — a model that correctly quoted 3 Maccabees used to be scored
as having invented it, because a hard-coded book list kept that book out of the
detection index.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from bible_bench.report import summarize_simple
from bible_bench.usfm import canon_of


class FakeMetaClient:
    """Minimal stand-in exposing only what canon questions need."""

    def __init__(self, books_by_version: dict[int, dict[str, list[str]]]):
        self._books = books_by_version
        self._chapter_sets: dict[int, frozenset[str]] = {}
        self._book_sets: dict[int, frozenset[str]] = {}

    async def version(self, version_id: int) -> dict:
        return {
            "abbreviation": f"V{version_id}",
            "books": [
                {"usfm": b, "human": b.title(),
                 "chapters": [{"usfm": c, "canonical": True} for c in chs]}
                for b, chs in self._books[version_id].items()
            ],
        }

    # Reuse the real implementations — they're what's under test.
    version_books = None  # bound below
    version_contains = None
    _known_chapters = None
    chapter_usfms = None


def _bind_real_methods() -> None:
    from bible_bench.yv_client import BibleClient

    for name in ("version_books", "version_contains", "_known_chapters", "chapter_usfms"):
        setattr(FakeMetaClient, name, getattr(BibleClient, name))


_bind_real_methods()


NIV = {"GEN": ["GEN.1"], "PSA": ["PSA.1"]}
NABRE = {"GEN": ["GEN.1"], "PSA": ["PSA.1"], "TOB": ["TOB.1", "TOB.2"]}
SYNODAL = {"GEN": ["GEN.1"], "3MA": ["3MA.1"]}


def test_version_contains_answers_membership_not_syntax():
    client = FakeMetaClient({1: NIV, 2: NABRE, 3: SYNODAL})
    run = asyncio.get_event_loop_policy().new_event_loop().run_until_complete

    # A well-formed reference to a book this version lacks: absent, not invalid.
    assert run(client.version_contains(1, "TOB.1.1")) is False
    assert run(client.version_contains(2, "TOB.1.1")) is True
    # Orthodox books were unreachable before v0.4 — the pattern rejected them.
    assert run(client.version_contains(3, "3MA.1.1")) is True
    assert run(client.version_contains(1, "3MA.1.1")) is False
    # Chapter-level too: a real book, a chapter it doesn't have.
    assert run(client.version_contains(2, "TOB.9.1")) is False
    # Malformed input is answered, not raised.
    assert run(client.version_contains(1, "not a reference")) is False


def test_chapter_usfms_no_longer_filters_by_canon():
    """The prefetch enumeration must include deuterocanonical/Orthodox chapters,
    or they never reach the cache and stay invisible to quote detection."""
    client = FakeMetaClient({2: NABRE, 3: SYNODAL})
    run = asyncio.get_event_loop_policy().new_event_loop().run_until_complete
    assert "TOB.1" in run(client.chapter_usfms(2))
    assert "3MA.1" in run(client.chapter_usfms(3))


def _simple_item(lang: str, vid: int, usfm: str, score: float) -> dict:
    return {
        "language_tag": lang, "version_id": vid, "version_abbrev": f"V{vid}",
        "usfm": usfm, "tier": "body", "canon": canon_of(usfm.split(".")[0]),
        "score": {
            "item_score": score, "grade": "perfect", "verbatim_strict": True,
            "format_ok": True, "qer": 0.0,
        },
    }


def test_every_canon_is_scored_together():
    """One score, all books. An edition is scored on what it actually carries: a
    Catholic Bible is asked about Tobit because it HAS Tobit, and that answer is
    as much a quotation as any other. Canon remains a reported slice so "is this
    model worse on the deuterocanon?" stays answerable, but it gates nothing."""
    items = [
        _simple_item("eng", 1, "GEN.1.1", 1.0),
        _simple_item("eng", 2, "TOB.1.1", 0.0),   # Catholic — counts
        _simple_item("eng", 2, "3MA.1.1", 0.0),   # Eastern — counts
        _simple_item("deu", 5, "GEN.1.1", 1.0),
    ]
    s = summarize_simple(items)
    # English averages all three of its items; German has only its one.
    assert s["by_language"]["eng"] == round(1 / 3, 4)
    assert s["by_language"]["deu"] == 1.0
    assert s["track_score"] == round((1 / 3 + 1.0) / 2, 4)
    assert "headline_canon" not in s
    # Still reported, just no longer a filter.
    assert s["by_canon"] == {"protestant": 1.0, "catholic": 0.0, "orthodox": 0.0}
    assert s["canon_counts"] == {"protestant": 2, "catholic": 1, "orthodox": 1}
    # German has no Catholic edition: absent from that slice, never a zero.
    assert s["canon_languages"]["catholic"] == ["eng"]
    assert s["canon_languages"]["protestant"] == ["deu", "eng"]
    assert set(s["by_tier"]) == {"body"}


def test_the_loss_decomposition_still_reconciles_with_every_canon_in():
    """The factor list has to add up to the shortfall, and it did that by
    filtering to the same subset the score averaged. Now that the score covers
    everything, so must the factors."""
    items = [
        _simple_item("eng", 1, "GEN.1.1", 0.5),
        _simple_item("eng", 2, "TOB.1.1", 0.0),
        _simple_item("deu", 5, "GEN.1.1", 0.8),
    ]
    s = summarize_simple(items)
    total = sum(f["points"] for f in s["score_factors"])
    assert abs(total - (1 - s["track_score"])) < 2e-4


def test_a_versions_score_covers_every_book_it_was_asked():
    """Per-translation is the primary granularity, and there a wider canon is not
    a comparability problem: each edition is scored on its own books. canon_profile
    records which canons that turned out to include, so a reader can see why two
    editions differ in item count."""
    items = [
        _simple_item("eng", 1, "GEN.1.1", 0.9),
        _simple_item("eng", 2, "GEN.1.1", 0.8),
        _simple_item("eng", 2, "TOB.1.1", 0.2),
    ]
    by_id = {v["version_id"]: v for v in summarize_simple(items)["versions"]}
    assert by_id[2]["score"] == 0.5            # (0.8 + 0.2) / 2 — everything
    assert by_id[2]["n"] == 2
    assert by_id[2]["canon_profile"] == ["protestant", "catholic"]
    assert by_id[2]["by_canon"] == {"catholic": 0.2, "protestant": 0.8}
    assert by_id[1]["canon_profile"] == ["protestant"]


def test_older_runs_without_canon_labels_still_summarize():
    """v0.2/v0.3 records have no `canon` field and used tier="deuterocanon"."""
    old = _simple_item("eng", 2, "TOB.1.1", 0.5)
    del old["canon"]
    old["tier"] = "deuterocanon"
    shared = _simple_item("eng", 1, "GEN.1.1", 1.0)
    del shared["canon"]
    s = summarize_simple([shared, old])
    assert s["track_score"] == 0.75           # both items, one language
    assert s["by_canon"] == {"protestant": 1.0, "catholic": 0.5}


def test_spec_has_no_hard_coded_canon_book_list():
    """The sampling spec must derive extra-canon books from version metadata; a
    committed book list is the thing v0.4 removed."""
    spec = json.loads(open("dataset/spec-v1.json").read())
    assert "deuterocanon" not in spec
    # The deuterocanon needs no separate pass: body draws from the union of every
    # book any edition carries, so "which books exist" is answered by the
    # editions rather than by a count in the spec.
    assert "extra_canon" not in spec
    assert spec["tiers"]["body"]["books"].startswith("union of every book")


@pytest.mark.parametrize(
    ("book", "expected"),
    [("GEN", "protestant"), ("REV", "protestant"), ("TOB", "catholic"),
     ("ESG", "catholic"), ("S3Y", "catholic"), ("3MA", "orthodox"),
     ("PS2", "orthodox"), ("MAN", "orthodox"), ("XYZ", "other")],
)
def test_canon_of(book: str, expected: str):
    assert canon_of(book) == expected
