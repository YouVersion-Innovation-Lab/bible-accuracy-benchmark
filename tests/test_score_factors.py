"""The "what dropped this score" decomposition must ADD UP.

A credit-score-style factor list that doesn't reconcile is worse than none: a
reader can't tell which entry is wrong. These tests pin the arithmetic — each
dimension's factors sum to its own shortfall, and the headline factors sum to
(100 - headline_score) — and pin the one semantic distinction the list exists to
draw: a provider blocking its own output is not the model declining.
"""

from __future__ import annotations

from bible_bench.report import build_summary, summarize_phantom, summarize_simple, summarize_topical


def simple_item(lang: str, score: float, grade: str, **extra) -> dict:
    return {
        "language_tag": lang, "version_id": 1, "version_abbrev": "NIV", "usfm": "GEN.1.1",
        "tier": "body", "canon": "protestant",
        "score": {
            "item_score": score, "grade": grade, "verbatim_strict": grade == "perfect",
            "format_ok": True, "qer": 1 - score,
        },
        **extra,
    }


def topical_item(lang: str, score: float, emission: float, **extra) -> dict:
    return {
        "language_tag": lang, "version_id": 1, "version_abbrev": "NIV",
        "topic_id": "anxiety", "elicitation_level": "L1", "sensitive": False,
        "topical_score": {
            "item_score": score, "emission": emission, "accuracy": score,
            "n_quotes": 1, "n_accurate": 0, "n_fabricated": 0, "n_fabricated_refs": 0,
        },
        "quotes": [],
        **extra,
    }


def phantom_item(lang: str, score: float, outcome: str, **extra) -> dict:
    return {
        "language_tag": lang, "version_id": 1, "version_abbrev": "NIV",
        "kind": "out_of_range_chapter",
        "phantom_score": {"item_score": score, "outcome": outcome, "n_quotes": 0},
        **extra,
    }


def _total(factors: list[dict]) -> float:
    return sum(f["points"] for f in factors)


# The decomposition is exact in real arithmetic; published numbers are rounded
# (track scores to 4dp, factor points to 6dp), so reconciliation is asserted to
# the rounding floor rather than to zero.
TOL = 2e-4


def test_simple_factors_sum_to_the_shortfall():
    items = [
        simple_item("eng", 1.0, "perfect"),
        simple_item("eng", 0.6, "minor"),
        simple_item("eng", 0.0, "fabricated"),
        simple_item("spa", 0.0, "no_attempt"),
        simple_item("spa", 1.0, "perfect"),
    ]
    s = summarize_simple(items)
    assert abs(_total(s["score_factors"]) - (1 - s["track_score"])) < TOL
    # Ranked worst-first so the top entry is the biggest lever.
    pts = [f["points"] for f in s["score_factors"]]
    assert pts == sorted(pts, reverse=True)


def test_macro_weighting_means_a_small_language_counts_as_much():
    """Track scores macro-average over languages, so one bad item in a
    2-item language costs far more than one in a 100-item language. The factor
    list has to reflect that or it will point at the wrong cause."""
    items = [simple_item("eng", 1.0, "perfect") for _ in range(100)]
    items.append(simple_item("spa", 0.0, "fabricated"))
    items.append(simple_item("spa", 1.0, "perfect"))
    s = summarize_simple(items)
    (fab,) = [f for f in s["score_factors"] if f["key"] == "fabricated"]
    # Half of Spanish, which is half the macro average: 0.25 of the track score.
    assert abs(fab["points"] - 0.25) < TOL
    assert abs(_total(s["score_factors"]) - (1 - s["track_score"])) < TOL


def test_a_provider_block_is_not_the_model_declining():
    """Google's RECITATION filter blocks verbatim scripture. The user gets no
    verse, so it scores 0 — but reporting it as "declined" attributes a provider
    policy to the model."""
    items = [
        simple_item("eng", 0.0, "no_attempt", finish_reason="content_filter: RECITATION"),
        simple_item("eng", 0.0, "no_attempt", finish_reason="stop"),
        simple_item("eng", 1.0, "perfect", finish_reason="stop"),
    ]
    keys = {f["key"]: f for f in summarize_simple(items)["score_factors"]}
    assert keys["blocked_by_provider"]["n"] == 1
    assert keys["no_attempt"]["n"] == 1
    # Older runs record no finish_reason: fall back to the grade, never invent a block.
    plain = summarize_simple([simple_item("eng", 0.0, "no_attempt")])
    assert [f["key"] for f in plain["score_factors"]] == ["no_attempt"]


def test_topical_splits_never_quoted_from_quoted_badly():
    items = [
        topical_item("eng", 0.0, 0.0),   # quoted nothing
        topical_item("eng", 0.5, 1.0),   # quoted, half right
        topical_item("eng", 1.0, 1.0),
    ]
    s = summarize_topical(items)
    keys = {f["key"]: f for f in s["score_factors"]}
    assert keys["no_quote"]["n"] == 1
    assert keys["inaccurate_quotes"]["n"] == 1
    assert abs(_total(s["score_factors"]) - (1 - s["track_score"])) < TOL


def test_phantom_factors_sum_to_the_shortfall():
    items = [
        phantom_item("eng", 1.0, "refused"),
        phantom_item("eng", 0.5, "substitute_no_disclaimer"),
        phantom_item("eng", 0.0, "fabricated_text"),
        phantom_item("eng", 0.0, "no_response", finish_reason="content_filter"),
    ]
    s = summarize_phantom(items)
    keys = {f["key"] for f in s["score_factors"]}
    assert "blocked_by_provider" in keys and "no_response" not in keys
    assert abs(_total(s["score_factors"]) - (1 - s["track_score"])) < TOL


def test_headline_factors_reconcile_to_the_overall_score():
    """The whole point: a reader can add the list up and land on the score."""
    tracks = {
        "simple": summarize_simple([
            simple_item("eng", 0.8, "minor"), simple_item("spa", 0.0, "fabricated"),
        ]),
        "topical": summarize_topical([
            topical_item("eng", 0.0, 0.0), topical_item("spa", 0.9, 1.0),
        ]),
        "phantom": summarize_phantom([
            phantom_item("eng", 1.0, "refused"), phantom_item("spa", 0.0, "fabricated_text"),
        ]),
    }
    s = build_summary(tracks)
    assert abs(_total(s["score_factors"]) - (100 - s["headline_score"])) < 0.05
    # Each factor names which dimension it came from, so the panel can group.
    assert {f["track"] for f in s["score_factors"]} <= {"simple", "topical", "phantom"}
    assert all(f["points"] > 0 for f in s["score_factors"])


def test_a_perfect_run_has_no_factors():
    tracks = {"simple": summarize_simple([simple_item("eng", 1.0, "perfect")])}
    s = build_summary(tracks)
    assert s["score_factors"] == []
    assert s["headline_score"] == 100.0
