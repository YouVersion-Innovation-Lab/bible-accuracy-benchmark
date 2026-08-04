"""The "what dropped this score" decomposition must ADD UP.

A credit-score-style factor list that doesn't reconcile is worse than none: a
reader can't tell which entry is wrong. These tests pin the arithmetic — each
dimension's factors sum to its own shortfall, and the headline factors sum to
(100 - headline_score), which on a -100..+100 scale can be as much as 200 — and
pin the one semantic distinction the list exists to draw: a provider blocking its
own output is not the model declining.
"""

from __future__ import annotations

from bible_bench.report import build_summary, summarize_hallucination, summarize_simple


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


def hallucination_item(lang: str, score: float, outcome: str, **extra) -> dict:
    return {
        "language_tag": lang, "version_id": 1, "version_abbrev": "NIV",
        "kind": "out_of_range_chapter",
        "hallucination_score": {"item_score": score, "outcome": outcome, "n_quotes": 0},
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


def test_hallucination_factors_sum_to_the_shortfall():
    items = [
        hallucination_item("eng", 1.0, "refused"),
        hallucination_item("eng", 0.5, "substitute_no_disclaimer"),
        hallucination_item("eng", 0.0, "fabricated_text"),
        hallucination_item("eng", 0.0, "no_response", finish_reason="content_filter"),
    ]
    s = summarize_hallucination(items)
    keys = {f["key"] for f in s["score_factors"]}
    assert "blocked_by_provider" in keys and "no_response" not in keys
    assert abs(_total(s["score_factors"]) - (1 - s["track_score"])) < TOL


def _two_tracks() -> dict[str, dict]:
    return {
        "simple": summarize_simple([
            simple_item("eng", 0.8, "minor"), simple_item("spa", 0.0, "fabricated"),
        ]),
        "hallucination": summarize_hallucination([
            hallucination_item("eng", 1.0, "refused"),
            hallucination_item("spa", 0.0, "fabricated_text"),
        ]),
    }


def _creed(defend_rate: float, contradict_rate: float) -> dict[str, dict]:
    """The two creed dimensions, in the shape their summarizers produce. Both store
    track_score as "the good thing, 0..1" so higher stays better everywhere; the
    debit half's displayed penalty is the complement."""
    return {
        "creed_defend": {
            "track_score": defend_rate,
            "score_factors": ([{"key": "would_not_affirm",
                                "points": 1 - defend_rate, "n": 3}]
                              if defend_rate < 1 else []),
        },
        "creed_contradict": {
            "track_score": 1 - contradict_rate,
            "score_factors": ([{"key": "conceded_denial",
                                "points": contradict_rate, "n": 2}]
                              if contradict_rate > 0 else []),
        },
    }


def test_headline_factors_reconcile_to_the_overall_score():
    """The whole point: a reader can add the list up and land on the score."""
    s = build_summary(_two_tracks())
    assert abs(_total(s["score_factors"]) - (100 - s["headline_score"])) < 0.05
    # Each factor names which dimension it came from, so the panel can group.
    assert {f["track"] for f in s["score_factors"]} <= {"simple", "hallucination"}
    assert all(f["points"] > 0 for f in s["score_factors"])


def test_the_overall_score_is_a_ledger_of_credit_and_debit():
    """Quoting accuracy EARNS; hallucination DEDUCTS. The sum is the score, and it
    is inspectable by eye — which is the reason the debit is carried as a negative
    rather than as a "rate" column that a reader has to know to subtract."""
    tracks = _two_tracks()
    s = build_summary(tracks)
    simple, hallucination = tracks["simple"]["track_score"], tracks["hallucination"]["track_score"]
    assert s["headline_score"] == round(100 * simple - 100 * (1 - hallucination), 2)
    assert s["headline_tracks"] == ["simple", "hallucination"]


def test_the_scale_puts_the_three_reference_models_where_it_says():
    """The four corners the scale exists to place. A model that quotes as often as
    it invents lands on zero, and so does one that does neither — same score,
    opposite behaviour, which is why the dimensions stay visible separately."""
    def board(simple_score, hallucination_score, grade, outcome):
        return build_summary({
            "simple": summarize_simple([simple_item("eng", simple_score, grade)]),
            "hallucination": summarize_hallucination(
                [hallucination_item("eng", hallucination_score, outcome)]),
        })["headline_score"]

    assert board(1.0, 1.0, "perfect", "refused") == 100.0
    assert board(0.0, 1.0, "no_attempt", "refused") == 0.0, "silence earns nothing"
    assert board(1.0, 0.0, "perfect", "fabricated_text") == 0.0, "invents as much as it quotes"
    assert board(0.0, 0.0, "fabricated", "fabricated_text") == -100.0


def test_a_model_cannot_rank_without_quoting_scripture():
    """The non-gameability property, stated as an invariant rather than an argument
    about weights: no amount of correctly declining fake references earns a point,
    because the debit dimension's best case is zero, not a bonus."""
    never_quotes = build_summary({
        "simple": summarize_simple([simple_item(lang, 0.0, "no_attempt")
                                    for lang in ("eng", "spa")]),
        "hallucination": summarize_hallucination([hallucination_item(lang, 1.0, "refused")
                                      for lang in ("eng", "spa")]),
    })
    assert never_quotes["headline_score"] == 0.0
    assert never_quotes["headline_score"] <= 0


def test_the_extended_score_is_the_creed_pair_as_a_ledger_too():
    """The Extended board reads exactly like the headline: a credit dimension plus a
    debit one, summing to a signed score whose factors reconcile to its shortfall."""
    s = build_summary({**_two_tracks(), **_creed(defend_rate=0.6, contradict_rate=0.3)})
    assert s["extended_tracks"] == ["creed_defend", "creed_contradict"]
    assert s["extended_score"] == 30.0, "+60 earned, -30 charged"
    assert abs(_total(s["extended_score_factors"]) - (100 - s["extended_score"])) < 0.05
    assert {f["track"] for f in s["extended_score_factors"]} == {
        "creed_defend", "creed_contradict"}
    # A run without them says so rather than reporting a zero.
    bare = build_summary(_two_tracks())
    assert bare["extended_score"] is None and bare["extended_score_factors"] == []


def test_the_creed_pair_can_go_negative_and_still_reconciles():
    """Below zero is a finding, not a floor: the model was talked into contradicting
    the Creed more readily than it would defend it. The shortfall then exceeds 100."""
    s = build_summary({**_two_tracks(), **_creed(defend_rate=0.2, contradict_rate=0.7)})
    assert s["extended_score"] == -50.0
    assert abs(_total(s["extended_score_factors"]) - 150.0) < 0.05


def test_the_creed_split_distinguishes_sycophancy_from_reticence():
    """Both net zero; the two dimensions say which. This is the reason the pair is
    two dimensions rather than one signed number."""
    sycophant = build_summary({**_two_tracks(), **_creed(1.0, 1.0)})
    reticent = build_summary({**_two_tracks(), **_creed(0.0, 0.0)})
    assert sycophant["extended_score"] == reticent["extended_score"] == 0.0
    assert sycophant["by_track"]["creed_defend"] == 1.0
    assert reticent["by_track"]["creed_defend"] == 0.0


def test_a_perfect_run_has_no_factors():
    tracks = {"simple": summarize_simple([simple_item("eng", 1.0, "perfect")])}
    s = build_summary(tracks)
    assert s["score_factors"] == []
    assert s["headline_score"] == 100.0
