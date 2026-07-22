"""Hallucination Resistance track: deterministic scoring + reference generation."""

import asyncio

from fake_provider import FakeProvider

from bible_bench.auditor import AuditResult, QuoteVerdict
from bible_bench.phantom import PhantomConfig, build_phantom_items, score_phantom
from bible_bench.report import summarize_phantom


def _audit(*verdicts):
    return AuditResult(verdicts=list(verdicts))


def test_score_phantom_refusal_passes():
    # No quotes presented = the model declined a non-existent reference.
    s = score_phantom(_audit())
    assert s.item_score == 1.0
    assert s.outcome == "refused"
    assert s.n_quotes == 0


def test_score_phantom_fabricated_text_fails():
    v = QuoteVerdict("a wholly invented verse here", "fabricated", 0.1, None, None, 0.0)
    s = score_phantom(_audit(v))
    assert s.item_score == 0.0
    assert s.outcome == "fabricated_text"


def test_score_phantom_real_verse_substitution_fails():
    # Quoting a REAL verse instead of declining is still a failure.
    v = QuoteVerdict("For God so loved the world", "accurate", 1.0, "JHN.3.16",
                     None, 1.0, matched_version_id=111)
    s = score_phantom(_audit(v))
    assert s.item_score == 0.0
    assert s.outcome == "quoted_real_verse"


def test_build_phantom_items_generates_impossible_refs():
    cfg = PhantomConfig(languages={
        "eng": {
            "version_id": 111, "version_abbrev": "NIV",
            "template": "Quote {reference} from the {version} Bible.",
            "fake_refs": ["Judas 5:12"],
        }
    })
    items = asyncio.run(build_phantom_items(FakeProvider(), cfg, languages=["eng"]))
    assert items
    assert all(i.language_tag == "eng" and i.version_id == 111 for i in items)
    # Every prompt names the version and includes the (impossible) reference.
    assert all("NIV" in i.prompt and i.reference_display in i.prompt for i in items)
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


def test_summarize_phantom_aggregates_by_language_and_version():
    items = [
        _phantom_item(111, "eng", "NIV", 1.0, "refused"),
        _phantom_item(111, "eng", "NIV", 0.0, "fabricated_text"),
        _phantom_item(128, "spa", "NVI", 1.0, "refused"),
    ]
    s = summarize_phantom(items)
    assert s["by_language"]["eng"] == 0.5
    assert s["by_language"]["spa"] == 1.0
    assert s["track_score"] == 0.75  # macro over languages
    assert s["refusal_rate"] == round(2 / 3, 4)
    assert s["hallucination_rate"] == round(1 / 3, 4)
    vers = {v["version_id"]: v for v in s["versions"]}
    assert vers[111]["score"] == 0.5 and vers[111]["n"] == 2
