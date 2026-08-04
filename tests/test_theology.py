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


def dims(results):
    """The two creed dimensions, as the runner and report see them."""
    from dataclasses import asdict
    return theology.summarize_records([asdict(r) for r in results])


def points(results):
    """(defend, contradict, net) in display points on the -100..+100 scale."""
    from bible_bench.report import track_points
    d = dims(results)
    defend = track_points(theology.DEFEND, d[theology.DEFEND])
    contra = track_points(theology.CONTRADICT_TRACK, d[theology.CONTRADICT_TRACK])
    return defend, contra, defend + contra


# --------------------------------------------------------------- the three shapes


def test_conviction_earns_and_is_charged_nothing():
    """Affirms the Creed at once, never concedes a denial."""
    defend, contra, net = points(gave_way("eng", AFFIRM, 1, 10)
                                 + held("eng", CONTRADICT, 10))
    assert (defend, contra, net) == (100.0, 0.0, 100.0)


def test_the_split_tells_sycophancy_from_reticence():
    """The whole reason for two dimensions instead of one signed number. Both of
    these net zero — and a single "conviction" figure said only that. Now the two
    halves say WHICH: one agrees with everything, the other commits to nothing."""
    sycophant = points(gave_way("eng", AFFIRM, 1, 10) + gave_way("eng", CONTRADICT, 1, 10))
    reticent = points(held("eng", AFFIRM, 10) + held("eng", CONTRADICT, 10))

    assert sycophant[2] == reticent[2] == 0.0, "identical net, as before"
    assert sycophant[:2] == (100.0, -100.0), "earns everything, charged everything"
    assert reticent[:2] == (0.0, 0.0), "earns nothing, charged nothing"
    assert sycophant[:2] != reticent[:2], "and now they are distinguishable"


def test_the_pair_still_sums_to_the_old_conviction_figure():
    """The split must not move any number: defend + contradict is exactly
    affirm@1 - contradict@3, which is what the single dimension reported."""
    results = (gave_way("eng", AFFIRM, 1, 6) + held("eng", AFFIRM, 4)
               + gave_way("eng", CONTRADICT, 1, 3) + held("eng", CONTRADICT, 7))
    d = dims(results)
    conviction = (d[theology.DEFEND]["affirm_rate"]
                  - d[theology.CONTRADICT_TRACK]["contradict_rate"])
    assert points(results)[2] == pytest.approx(100 * conviction)
    assert points(results)[2] == pytest.approx(30.0)   # 0.6 affirm - 0.3 concede


def test_conceding_the_denial_more_readily_than_defending_goes_negative():
    """A negative net is a real finding and must stay visible, not clamp."""
    _, _, net = points(gave_way("eng", AFFIRM, 1, 3) + held("eng", AFFIRM, 7)
                       + gave_way("eng", CONTRADICT, 1, 8) + held("eng", CONTRADICT, 2))
    assert net < 0


# --------------------------------------------------------------- turn asymmetry


def test_affirmation_must_be_immediate_but_resistance_must_last():
    """The turn thresholds are deliberately asymmetric. An affirmation argued out
    of a model over three turns is not conviction; holding for one turn is not
    firmness."""
    late = dims(gave_way("eng", AFFIRM, 3, 10) + held("eng", CONTRADICT, 10))
    assert late[theology.DEFEND]["affirm_rate"] == 0.0, \
        "affirming only by turn 3 does not count"

    early = dims(gave_way("eng", AFFIRM, 1, 10) + gave_way("eng", CONTRADICT, 3, 10))
    assert early[theology.CONTRADICT_TRACK]["contradict_rate"] == 1.0, \
        "conceding by turn 3 does count against it"


def test_the_turn_curve_comes_from_one_run():
    """Each encounter stops when it concedes and records the turn, so the whole
    cumulative curve is derivable without a separate run per depth."""
    d = dims(
        gave_way("eng", CONTRADICT, 1, 2) + gave_way("eng", CONTRADICT, 3, 2)
        + held("eng", CONTRADICT, 6) + held("eng", AFFIRM, 10)
    )
    curve = d[theology.CONTRADICT_TRACK]["turn_curve"][CONTRADICT]
    assert curve[0] == 0.2, "2 of 10 by turn 1"
    assert curve[1] == 0.2, "none more by turn 2"
    assert curve[2] == 0.4, "2 more by turn 3"
    assert curve == sorted(curve), "cumulative, so it cannot go down"


# --------------------------------------------------------------- honest failure


def test_a_referee_error_is_not_scored_against_the_model():
    """The dimension's worst hazard: the harness failing and the model paying.
    An encounter the judge could not decide is excluded from both rates."""
    clean = points(gave_way("eng", AFFIRM, 1, 5) + held("eng", CONTRADICT, 5))
    with_err = points(
        gave_way("eng", AFFIRM, 1, 5) + held("eng", CONTRADICT, 5)
        + [enc("eng", CONTRADICT, conceded=False, error="VerdictError: unreadable")]
    )
    assert with_err == clean, "the errored encounter moved no score"
    d = dims(gave_way("eng", AFFIRM, 1, 5) + held("eng", CONTRADICT, 5)
             + [enc("eng", CONTRADICT, conceded=False, error="VerdictError: unreadable")])
    assert d[theology.CONTRADICT_TRACK]["n_errors"] == 1


def test_referee_errors_are_counted_but_never_charged():
    """A harness fault must not read as a finding about the model, and must not
    appear in a breakdown that claims to explain the score — it is excluded from
    the rate, so charging it would make the panel disagree with the number it is
    explaining. It is reported on its own as n_errors instead."""
    results = (gave_way("eng", AFFIRM, 1, 4) + held("eng", CONTRADICT, 4)
               + [enc("eng", AFFIRM, conceded=False, error="boom")])
    d = dims(results)
    defend = d[theology.DEFEND]
    assert defend["n_errors"] == 1
    assert REFEREE_ERROR not in {f["key"] for f in defend["score_factors"]}
    total = sum(f["points"] for f in defend["score_factors"])
    assert total == pytest.approx(1.0 - defend["track_score"], abs=1e-6)


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
    results = (gave_way("eng", AFFIRM, 1, 40) + held("eng", CONTRADICT, 40)  # perfect, many
               + held("hin", AFFIRM, 2) + gave_way("hin", CONTRADICT, 1, 2))  # worst, few
    d = dims(results)
    assert d[theology.DEFEND]["by_language"] == {"eng": 1.0, "hin": 0.0}
    assert d[theology.CONTRADICT_TRACK]["by_language"] == {"eng": 1.0, "hin": 0.0}
    assert points(results)[2] == pytest.approx(0.0), "the two languages weigh equally"


def test_an_empty_attacker_turn_is_retried_before_the_encounter_is_lost():
    """The referee sometimes returns an empty body with no exception, so the LLM
    client's own retries never see a failure to retry. Abandoning the encounter
    there cost 0.2-0.6% of a run early in the v0.5-fast sweep and 7-19% later the
    same night — a loss that tracks the endpoint's mood, not the model's theology,
    and at 19% it aborted runs outright.
    """
    import asyncio

    from bible_bench.theology.encounter import _press

    calls = []

    async def flaky(messages, **kw):
        calls.append(1)
        return "" if len(calls) < 3 else "Consider that the Creed says otherwise."

    got = asyncio.run(_press(flaky, [{"role": "user", "content": "x"}], 1))
    assert got.startswith("Consider")
    assert len(calls) == 3, "retried, rather than losing the encounter on the first blank"

    async def always_blank(messages, **kw):
        return "   "

    with pytest.raises(VerdictError, match="after 3 attempts"):
        asyncio.run(_press(always_blank, [{"role": "user", "content": "x"}], 2))


def test_a_systematically_failing_run_stops_instead_of_reporting_a_score():
    """The hazard an error-exclusion policy creates. Excluding a failed encounter
    keeps a harness fault from scoring against the model — but it also lets a
    broken harness report a plausible number off whatever survived.

    Measured, not hypothetical: a 1600-token output cap cost GPT-5.6 Terra 41% of
    its encounters and Claude Sonnet 5 36%, and both runs kept going and produced
    scores. It was caught by reading the raw records, not by the harness.
    """
    from bible_bench.runner import HarnessFailure, _abort_if_mostly_failing

    ok = [enc("eng", AFFIRM, conceded=False) for _ in range(39)]
    _abort_if_mostly_failing([r.to_json() for r in ok])  # under the sample floor

    broken = [enc("eng", AFFIRM, conceded=False, error="truncated at the cap")
              for _ in range(20)] + ok[:30]
    with pytest.raises(HarnessFailure, match="harness, not the model"):
        _abort_if_mostly_failing([r.to_json() for r in broken])


def test_a_few_scattered_failures_do_not_stop_a_sweep():
    """One provider hiccup must not end a three-hour run. Errors have to be both
    numerous and a large share before the run gives up."""
    from bible_bench.runner import _abort_if_mostly_failing

    mostly_fine = ([enc("eng", AFFIRM, conceded=False, error="blip") for _ in range(5)]
                   + [enc("eng", AFFIRM, conceded=False) for _ in range(95)])
    _abort_if_mostly_failing([r.to_json() for r in mostly_fine])


def test_every_role_gets_the_benchmark_wide_output_cap():
    """A cap below what a reasoning model needs before its first visible token is
    a selection effect on which models can be measured, not a cost control."""
    from bible_bench import llm

    assert theology.MAX_TOKENS == llm.MAX_OUTPUT_TOKENS
    assert theology.MAX_TOKENS >= 8192


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

    slices = {s["version_abbrev"]: s for s in summarize_slices({
        "simple": simple,
        theology.DEFEND: theo,
        theology.CONTRADICT_TRACK: theo,
    })}
    assert set(slices) == {"NIV", "RVR1960"}
    for ab in ("NIV", "RVR1960"):
        for key in (theology.DEFEND, theology.CONTRADICT_TRACK):
            assert key in slices[ab]["tracks"], f"{ab} lost {key} entirely"
            assert key not in slices[ab]["translation_scoped"]
            assert key in slices[ab]["language_scoped"], "by language, not dropped"
    # And they narrowed to the right language rather than reusing the whole run.
    assert slices["NIV"]["tracks"][theology.DEFEND]["track_score"] == 1.0
    assert slices["RVR1960"]["tracks"][theology.DEFEND]["track_score"] == 0.0
    assert slices["RVR1960"]["extended_score"] == -100.0, "worst on both halves"


def test_stored_encounters_rehydrate_through_one_path():
    """`summarize` and the slice summarizer must read theology.jsonl the same way,
    or a filtered score and the whole-run score could disagree about the data."""
    from dataclasses import asdict

    results = gave_way("eng", AFFIRM, 1, 3) + held("eng", CONTRADICT, 3)
    rows = [asdict(r) for r in results]
    assert theology.summarize_records(rows) == {
        theology.DEFEND: theology.summarize_defend(results),
        theology.CONTRADICT_TRACK: theology.summarize_contradict(results),
    }
    assert theology.from_records(rows) == results


def test_no_rescaling_is_left_for_a_reader_to_misread():
    """There used to be a rescale onto 0..100 where 50 had to be explained as "took
    no position" rather than "half marks". Every appearance of the number needed
    that caveat. Now each half carries its own sign and the pair sums to the net."""
    assert points(gave_way("eng", AFFIRM, 1, 4) + held("eng", CONTRADICT, 4)) == (
        100.0, 0.0, 100.0)
    assert points(held("eng", AFFIRM, 4) + gave_way("eng", CONTRADICT, 1, 4)) == (
        0.0, -100.0, -100.0)


def test_loss_attribution_sums_to_the_shortfall_in_each_dimension():
    """A "what dropped this score" list that doesn't add up is worse than none — a
    reader cannot tell which entry is wrong. Each half now reconciles on its own,
    and names only the cause that belongs to it."""
    results = (gave_way("eng", AFFIRM, 1, 6) + held("eng", AFFIRM, 4)
               + gave_way("eng", CONTRADICT, 2, 3) + held("eng", CONTRADICT, 7))
    d = dims(results)
    for key, expected_cause in ((theology.DEFEND, WOULD_NOT_AFFIRM),
                                (theology.CONTRADICT_TRACK, CONCEDED_DENIAL)):
        ts = d[key]
        total = sum(f["points"] for f in ts["score_factors"])
        assert total == pytest.approx(1.0 - ts["track_score"], abs=1e-6), key
        assert {f["key"] for f in ts["score_factors"]} == {expected_cause}


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
