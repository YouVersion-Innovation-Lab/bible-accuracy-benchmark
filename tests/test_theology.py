"""Basic Christian Theology: the pair is the measurement.

Replaces the retired adversarial suite. The cases below are the ones where a
single-direction test, or a lenient default, would report the opposite of what
happened — which is the failure mode this dimension is most exposed to, since an
LLM is both the attacker and the scorer.
"""

import asyncio

import pytest

from bible_bench import theology
from bible_bench.theology import AFFIRM, CONTRADICT, EncounterResult, Turn, VerdictError
from bible_bench.theology.score import (
    CONCEDED_DENIAL,
    REFEREE_ERROR,
    WOULD_NOT_AFFIRM,
    rescale,
)


def enc(lang, direction, *, conceded, turn=None, error=None, n_turns=1):
    return EncounterResult(
        item_id=f"{lang}-{direction}-{turn}-{error}-{conceded}-{n_turns}",
        language_tag=lang, direction=direction, clause_id="one-god",
        perspective="Atheist", claim="x", conceded=conceded, turn_reached=turn,
        turns=[Turn(i, "a", "r", conceded and i == turn) for i in range(1, n_turns + 1)],
        error=error,
    )


def held(lang, direction, n=1):
    """Conceded nothing across the full three turns."""
    return [enc(lang, direction, conceded=False, n_turns=3) for _ in range(n)]


def gave_way(lang, direction, turn, n=1):
    return [enc(lang, direction, conceded=True, turn=turn, n_turns=turn) for _ in range(n)]


# --------------------------------------------------------------- the three shapes


def test_conviction_scores_high():
    """Affirms the Creed at once, never concedes a denial."""
    s = theology.summarize(gave_way("eng", AFFIRM, 1, 10) + held("eng", CONTRADICT, 10))
    assert s["affirm_rate"] == 1.0
    assert s["contradict_rate"] == 0.0
    assert s["conviction"] == 1.0
    assert s["track_score"] == 1.0


def test_a_model_that_agrees_with_everything_nets_zero():
    """The reason both directions are run. Agreeing readily to the Creed AND to
    its denial is not conviction, and a single-direction test would call it
    excellent — Gemini 3 Flash scored 63.9% affirm / 78.9% contradict in the
    pilot, i.e. worse than taking no position at all."""
    s = theology.summarize(gave_way("eng", AFFIRM, 1, 10) + gave_way("eng", CONTRADICT, 1, 10))
    assert s["affirm_rate"] == 1.0, "looks perfect on the affirm side alone"
    assert s["conviction"] == 0.0, "and is worth nothing once both sides are counted"
    assert s["track_score"] == 0.5


def test_a_model_that_commits_to_nothing_also_nets_zero():
    """The other way to score 50: refuse to affirm, refuse to deny. Claude
    Sonnet 4.6 sat here in the pilot at 26.5% / 25.2%."""
    s = theology.summarize(held("eng", AFFIRM, 10) + held("eng", CONTRADICT, 10))
    assert s["affirm_rate"] == 0.0
    assert s["contradict_rate"] == 0.0
    assert s["track_score"] == 0.5, "same score as the sycophant, opposite behaviour"


def test_conceding_the_denial_more_readily_than_the_creed_goes_below_fifty():
    """A negative conviction is a real finding and must stay visible, not clamp."""
    s = theology.summarize(gave_way("eng", AFFIRM, 1, 3) + held("eng", AFFIRM, 7)
                           + gave_way("eng", CONTRADICT, 1, 8) + held("eng", CONTRADICT, 2))
    assert s["conviction"] < 0
    assert s["track_score"] < 0.5


# --------------------------------------------------------------- turn asymmetry


def test_affirmation_must_be_immediate_but_resistance_must_last():
    """The turn thresholds are deliberately asymmetric. An affirmation argued out
    of a model over three turns is not conviction; holding for one turn is not
    firmness."""
    late = theology.summarize(gave_way("eng", AFFIRM, 3, 10) + held("eng", CONTRADICT, 10))
    assert late["affirm_rate"] == 0.0, "affirming only by turn 3 does not count"

    early = theology.summarize(gave_way("eng", AFFIRM, 1, 10)
                               + gave_way("eng", CONTRADICT, 3, 10))
    assert early["contradict_rate"] == 1.0, "conceding by turn 3 does count against it"


def test_the_turn_curve_comes_from_one_run():
    """Each encounter stops when it concedes and records the turn, so the whole
    cumulative curve is derivable without a separate run per depth."""
    s = theology.summarize(
        gave_way("eng", CONTRADICT, 1, 2) + gave_way("eng", CONTRADICT, 3, 2)
        + held("eng", CONTRADICT, 6) + held("eng", AFFIRM, 10)
    )
    curve = s["turn_curve"][CONTRADICT]
    assert curve[0] == 0.2, "2 of 10 by turn 1"
    assert curve[1] == 0.2, "none more by turn 2"
    assert curve[2] == 0.4, "2 more by turn 3"
    assert curve == sorted(curve), "cumulative, so it cannot go down"


# --------------------------------------------------------------- honest failure


def test_a_referee_error_is_not_scored_against_the_model():
    """The dimension's worst hazard: the harness failing and the model paying.
    An encounter the judge could not decide is excluded from both rates."""
    clean = theology.summarize(gave_way("eng", AFFIRM, 1, 5) + held("eng", CONTRADICT, 5))
    with_err = theology.summarize(
        gave_way("eng", AFFIRM, 1, 5) + held("eng", CONTRADICT, 5)
        + [enc("eng", CONTRADICT, conceded=False, error="VerdictError: unreadable")]
    )
    assert with_err["conviction"] == clean["conviction"]
    assert with_err["n_errors"] == 1


def test_referee_errors_are_their_own_visible_cause():
    """Named in the loss breakdown rather than folded into a failure, so a
    harness fault can never read as a finding about the model."""
    s = theology.summarize(
        gave_way("eng", AFFIRM, 1, 4) + held("eng", CONTRADICT, 4)
        + [enc("eng", AFFIRM, conceded=False, error="boom")]
    )
    keys = {f["key"] for f in s["score_factors"]}
    assert REFEREE_ERROR in keys


def test_an_unreadable_verdict_raises_rather_than_passing():
    """The prototype's `str(x).lower() == "true"` turned any malformed verdict
    into "the model held firm" — a point awarded for a referee glitch. Reasoning
    models make this routine: too small a budget and they never emit the JSON."""
    from bible_bench.theology.encounter import _read_verdict
    from bible_bench.theology.probes import TheologyItem

    item = TheologyItem(id="i", track="theology", language_tag="eng",
                        direction=CONTRADICT, clause_id="c", clause="C",
                        perspective="Atheist", probe_n=0, claim="x")
    for junk in ("", "[1]", "thinking about it...", "{}"):
        with pytest.raises(VerdictError):
            _read_verdict(junk, item, 1)
    assert _read_verdict('{"conceded": true, "reasoning": "y"}', item, 1)[0] is True
    assert _read_verdict('  {"conceded": false}  ', item, 1)[0] is False


def test_a_garbled_verdict_is_retried_before_it_raises():
    """One stray token should not lose a whole encounter; a persistent failure
    still must not become a silent pass."""
    from bible_bench.theology.encounter import _judge_turn
    from bible_bench.theology.probes import TheologyItem

    item = TheologyItem(id="i", track="theology", language_tag="eng",
                        direction=CONTRADICT, clause_id="c", clause="C",
                        perspective="Atheist", probe_n=0, claim="x")
    calls = []

    async def flaky(messages, **kw):
        calls.append(1)
        return "[1]" if len(calls) < 3 else '{"conceded": true, "reasoning": "ok"}'

    conceded, _ = asyncio.run(_judge_turn(flaky, item, "resp", 1))
    assert conceded is True
    assert len(calls) == 3

    async def always_bad(messages, **kw):
        return "nonsense"

    with pytest.raises(VerdictError):
        asyncio.run(_judge_turn(always_bad, item, "resp", 1))


# --------------------------------------------------------------- bookkeeping


def test_failure_direction_is_not_symmetric():
    """Conceding a denial is the failure; conceding an affirmation is the goal.
    One rule for both would report half the dimension backwards."""
    assert theology.is_failure(gave_way("eng", CONTRADICT, 1)[0]) is True
    assert theology.is_failure(held("eng", CONTRADICT)[0]) is False
    assert theology.is_failure(gave_way("eng", AFFIRM, 1)[0]) is False
    assert theology.is_failure(held("eng", AFFIRM)[0]) is True


def test_languages_are_macro_averaged():
    """A language with more probes must not count for more, or the score becomes
    a statement about our sampling rather than about the model."""
    s = theology.summarize(
        gave_way("eng", AFFIRM, 1, 40) + held("eng", CONTRADICT, 40)      # perfect, many
        + held("hin", AFFIRM, 2) + gave_way("hin", CONTRADICT, 1, 2)      # worst, few
    )
    assert s["by_language"]["eng"] == 1.0
    assert s["by_language"]["hin"] == 0.0
    assert s["track_score"] == pytest.approx(0.5), "the two languages weigh equally"


def test_a_translation_filter_narrows_theology_instead_of_dropping_it():
    """Filtering the site to a translation must not quietly remove this dimension
    from the Extended Score. Theology names no translation, so a slice narrows it
    to that translation's language — the same rule Scripture in Answers follows.

    Caught in the browser: under a KJV filter the Extended Score became the
    Scripture-in-Answers score alone, still captioned "50% Basic Christian
    Theology". A missing registry entry, invisible from the whole-run number.
    """
    from dataclasses import asdict

    from bible_bench.report import summarize_slices

    theo = [asdict(r) for r in
            gave_way("eng", AFFIRM, 1, 4) + held("eng", CONTRADICT, 4)     # eng: perfect
            + held("spa", AFFIRM, 4) + gave_way("spa", CONTRADICT, 1, 4)]  # spa: worst
    simple = [
        {"item_id": f"s{i}", "language_tag": lang, "version_id": vid,
         "version_abbrev": ab, "usfm": "JHN.3.16", "tier": "famous",
         "canon": "protestant", "finish_reason": "stop",
         "score": {"grade": "perfect", "item_score": 1.0, "qer": 0.0,
                   "verbatim_strict": True, "verbatim_loose": True,
                   "format_ok": True, "overquote": False}}
        for i, (lang, vid, ab) in enumerate([("eng", 111, "NIV"), ("spa", 149, "RVR1960")])
    ]

    slices = {s["version_abbrev"]: s for s in
              summarize_slices({"simple": simple, "theology": theo})}
    assert set(slices) == {"NIV", "RVR1960"}
    for ab in ("NIV", "RVR1960"):
        assert "theology" in slices[ab]["tracks"], f"{ab} lost the dimension entirely"
        assert "theology" not in slices[ab]["translation_scoped"]
        assert "theology" in slices[ab]["language_scoped"], "narrowed by language, not dropped"
    # And it narrowed to the right language rather than reusing the whole run.
    assert slices["NIV"]["tracks"]["theology"]["track_score"] == 1.0
    assert slices["RVR1960"]["tracks"]["theology"]["track_score"] == 0.0


def test_stored_encounters_rehydrate_through_one_path():
    """`summarize` and the slice summarizer must read theology.jsonl the same way,
    or a filtered score and the whole-run score could disagree about the data."""
    from dataclasses import asdict

    results = gave_way("eng", AFFIRM, 1, 3) + held("eng", CONTRADICT, 3)
    rows = [asdict(r) for r in results]
    assert theology.summarize_records(rows) == theology.summarize(results)
    assert theology.from_records(rows) == results


def test_the_rescale_keeps_negatives_visible():
    assert rescale(1.0) == 100.0
    assert rescale(0.0) == 50.0
    assert rescale(-1.0) == 0.0
    assert rescale(-0.15) < 50.0, "a sycophant must not be flattered to 50"


def test_loss_attribution_sums_to_the_shortfall():
    """A 'what dropped this score' list that doesn't add up is worse than none —
    a reader cannot tell which entry is wrong."""
    results = (gave_way("eng", AFFIRM, 1, 6) + held("eng", AFFIRM, 4)
               + gave_way("eng", CONTRADICT, 2, 3) + held("eng", CONTRADICT, 7))
    s = theology.summarize(results)
    total = sum(f["points"] for f in s["score_factors"])
    assert total == pytest.approx(1.0 - s["track_score"], abs=1e-6)
    keys = {f["key"] for f in s["score_factors"]}
    assert keys == {WOULD_NOT_AFFIRM, CONCEDED_DENIAL}


def test_probe_thinning_keeps_every_clause_and_both_directions():
    """A fast pass that dropped whole creed clauses would be a different
    benchmark, not a smaller one — and dropping one side of a pair would break
    the measurement outright."""
    spec = theology.load_spec()
    items = theology.build_items(spec, seed="test", per_clause=1)
    langs = {i.language_tag for i in items}
    assert langs == set(spec.language_tags)
    for lang in langs:
        mine = [i for i in items if i.language_tag == lang]
        clauses = {i.clause_id for i in mine}
        assert len(clauses) == 21, f"{lang} lost clauses"
        assert len(mine) == 42, f"{lang} should be 21 clauses x 2 directions"
    # Every language must draw the SAME probes, or their scores aren't comparable.
    per_lang = {
        lang: sorted((i.clause_id, i.probe_n) for i in items if i.language_tag == lang)
        for lang in langs
    }
    assert len(set(map(str, per_lang.values()))) == 1


def test_every_language_carries_an_identical_probe_set():
    """Enforced at load: a translation that dropped a probe would make one
    language's score quietly incomparable with the rest."""
    spec = theology.load_spec()
    shapes = {
        tag: [(c["id"], len(c["probes"])) for c in data["clauses"]]
        for tag, data in spec.languages.items()
    }
    assert len({str(v) for v in shapes.values()}) == 1
    assert len(spec.language_tags) == 11


def test_paired_probes_stay_in_opposition_after_translation():
    """The pair IS the measurement. A translator that softened a contradiction
    into mere doubt would silently break the instrument in that language."""
    spec = theology.load_spec()
    for tag, data in spec.languages.items():
        for clause in data["clauses"]:
            for probe in clause["probes"]:
                a, c = probe["affirm"].strip(), probe["contradict"].strip()
                assert a and c, f"{tag} {clause['id']}#{probe['n']}: empty half"
                assert a != c, f"{tag} {clause['id']}#{probe['n']}: pair collapsed"
