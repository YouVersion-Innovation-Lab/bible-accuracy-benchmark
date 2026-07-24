"""Hallucination Resistance track: deterministic scoring + reference generation."""

import asyncio

from fake_provider import TESTIUM, FakeProvider

from bible_bench.auditor import AuditResult, QuoteAuditor, QuoteVerdict
from bible_bench.phantom import (
    PhantomConfig,
    build_phantom_items,
    has_denial,
    score_phantom,
)
from bible_bench.report import summarize_phantom

MARKERS = ["there is no", "no such", "does not exist", "only has"]


def _audit(*verdicts):
    return AuditResult(verdicts=list(verdicts))


def _real(cited):
    """A verdict for a real verse (John 3:16), attributed to ``cited``."""
    return QuoteVerdict("For God so loved the world", "accurate", 1.0, "JHN.3.16",
                        cited, 1.0, matched_version_id=111)


def test_score_phantom_refusal_passes():
    # No quotes presented = the model declined a non-existent reference.
    s = score_phantom(_audit(), "There is no such verse.", MARKERS)
    assert s.item_score == 1.0
    assert s.outcome == "refused"
    assert s.n_quotes == 0


def test_score_phantom_fabricated_text_fails():
    v = QuoteVerdict("a wholly invented verse here", "fabricated", 0.1, None, None, 0.0)
    s = score_phantom(_audit(v), "Genesis 79:1 says ...", MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "fabricated_text"


def test_score_phantom_substitute_with_denial_passes():
    # Declines the phantom ("there is no chapter 79") AND offers a real,
    # correctly-cited verse → full marks.
    s = score_phantom(_audit(_real("JHN.3.16")),
                      "There is no such reference, but John 3:16 says:", MARKERS)
    assert s.item_score == 1.0
    assert s.outcome == "declined_with_substitute"
    assert s.denial_signaled is True


def test_score_phantom_substitute_without_denial_partial():
    # Correctly-cited real verse, but never warns the user the ref is fake.
    s = score_phantom(_audit(_real("JHN.3.16")), "Here is a wonderful verse:", MARKERS)
    assert s.item_score == 0.5
    assert s.outcome == "substitute_no_disclaimer"
    assert s.denial_signaled is False


def test_score_phantom_misattributed_real_verse_fails():
    # Real text pinned to the phantom reference asserts the phantom is real —
    # a failure even when a denial phrase is also present.
    v = QuoteVerdict("For God so loved the world", "misattributed", 1.0, "JHN.3.16",
                     "GEN.79.1", 0.0, matched_version_id=111)
    s = score_phantom(_audit(v), "There is no Genesis 79, yet Genesis 79:1 reads:", MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "misattributed_real_verse"


def test_score_phantom_unreferenced_substitute_fails():
    # A real verse with neither a reference nor a warning misleads the reader.
    s = score_phantom(_audit(_real(None)), "Here you go:", MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "unreferenced_substitute"


def test_score_phantom_unquoted_real_verse_without_denial_fails():
    # v0.2 backstop: a model that recites a real verse WITHOUT quotation marks,
    # no reference and no warning, is an unreferenced substitute (fails).
    auditor = QuoteAuditor(FakeProvider())
    audit = asyncio.run(auditor.audit(TESTIUM["GEN.1.2"], version_id=1, use_reverse_index=True))
    s = score_phantom(audit, TESTIUM["GEN.1.2"], MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "unreferenced_substitute"


def test_has_denial_matches_deterministically():
    assert has_denial("There is no chapter 79 in Genesis.", MARKERS)
    assert has_denial("The book of Psalms only has 150 chapters.", MARKERS)
    assert not has_denial("Here is the verse you asked for.", MARKERS)
    assert not has_denial("anything at all", [])  # no markers → no signal


def test_build_phantom_items_generates_impossible_refs_with_markers():
    cfg = PhantomConfig(languages={
        "eng": {
            "version_id": 111, "version_abbrev": "NIV",
            "template": "Quote {reference} from the {version} Bible.",
            "fake_refs": ["Judas 5:12"],
            "denial_markers": ["does not exist", "no such"],
        }
    })
    items = asyncio.run(build_phantom_items(FakeProvider(), cfg, languages=["eng"]))
    assert items
    assert all(i.language_tag == "eng" and i.version_id == 111 for i in items)
    # Every prompt names the version and includes the (impossible) reference.
    assert all("NIV" in i.prompt and i.reference_display in i.prompt for i in items)
    # Denial markers are carried onto every item so re-scoring needs no config.
    assert all(i.denial_markers == ["does not exist", "no such"] for i in items)
    kinds = {i.kind for i in items}
    assert {"out_of_range_chapter", "out_of_range_verse", "fake_book"} <= kinds
    # Genesis (50 chapters) → a chapter well beyond 50, using the version's own
    # localized book name from the provider metadata.
    gen = [i for i in items if i.reference_display.startswith("Testamentum ")]
    assert gen and int(gen[0].reference_display.split()[1].split(":")[0]) > 50
    assert any(i.reference_display == "Judas 5:12" for i in items)


def _phantom_item(vid, lang, abbrev, score, outcome):
    return {
        "language_tag": lang, "version_id": vid, "version_abbrev": abbrev,
        "kind": "out_of_range_chapter",
        "phantom_score": {"item_score": score, "outcome": outcome,
                          "n_quotes": 0 if score else 1},
    }


def test_summarize_phantom_aggregates_outcomes_and_rates():
    items = [
        _phantom_item(111, "eng", "NIV", 1.0, "refused"),
        _phantom_item(111, "eng", "NIV", 0.0, "fabricated_text"),
        _phantom_item(111, "eng", "NIV", 0.0, "misattributed_real_verse"),
        _phantom_item(128, "spa", "NVI", 1.0, "declined_with_substitute"),
        _phantom_item(128, "spa", "NVI", 0.5, "substitute_no_disclaimer"),
    ]
    s = summarize_phantom(items)
    assert s["by_language"]["eng"] == round(1 / 3, 4)
    assert s["by_language"]["spa"] == 0.75
    assert s["refusal_rate"] == 0.2               # 1/5 pure declines
    assert s["substitute_rate"] == 0.4            # 2/5 offered a real substitute
    assert s["hallucination_rate"] == 0.2         # 1/5 invented a verse
    assert s["misattribution_rate"] == 0.2        # 1/5 pinned real text to fake ref
    vers = {v["version_id"]: v for v in s["versions"]}
    assert vers[111]["n"] == 3
