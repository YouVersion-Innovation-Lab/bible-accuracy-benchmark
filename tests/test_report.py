"""Aggregation of scored items into a track summary — in particular the
per-version breakdown that powers the website's language + Bible-version
filter."""

from bible_bench.report import summarize_simple


def _item(lang, version_id, abbrev, score, *, tier="body"):
    return {
        "language_tag": lang,
        "tier": tier,
        "version_id": version_id,
        "version_abbrev": abbrev,
        "score": {
            "item_score": score,
            "grade": "perfect" if score == 1.0 else "major",
            "verbatim_strict": score == 1.0,
            "format_ok": True,
        },
    }


def test_versions_breakdown_carries_language_and_abbrev():
    items = [
        _item("eng", 1, "KJV", 1.0),
        _item("eng", 1, "KJV", 0.5),  # KJV mean = 0.75
        _item("eng", 111, "NIV11", 0.2),  # NIV mean = 0.2
        _item("spa", 149, "RVR1960", 0.6),  # Spanish mean = 0.6
    ]
    summary = summarize_simple(items)
    versions = {v["version_id"]: v for v in summary["versions"]}

    assert set(versions) == {1, 111, 149}
    assert versions[1]["score"] == 0.75
    assert versions[1]["n"] == 2
    assert versions[1]["language_tag"] == "eng"
    assert versions[1]["version_abbrev"] == "KJV"
    assert versions[149]["language_tag"] == "spa"

    # A version belongs to exactly one language, so per-version detail is the
    # same as per-(language, version) — the filter can rely on that.
    assert versions[111]["score"] == 0.2
    # Per-language macro-average is unaffected by the added detail.
    assert summary["by_language"]["spa"] == 0.6


def test_versions_empty_for_no_items():
    assert summarize_simple([])["versions"] == []
