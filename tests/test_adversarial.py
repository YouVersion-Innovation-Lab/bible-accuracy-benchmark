from pathlib import Path

from fake_provider import TESTIUM, FakeProvider

from bible_bench.adversarial.encounter import (
    EncounterResult,
    run_encounter,
    summarize_encounters,
)
from bible_bench.adversarial.goals import Goal, load_goals
from bible_bench.adversarial.judge import AdversarialJudge
from bible_bench.auditor import QuoteAuditor

V1 = TESTIUM["GEN.1.1"]
GOALS_PATH = Path(__file__).parent.parent / "dataset" / "adversarial-goals-v1.json"


class ScriptedLLM:
    """Returns queued responses in order; ignores the prompt. Used for both
    the attacker (canned attack strings) and target (canned replies)."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._i = 0

    async def complete(self, messages, **kwargs) -> str:
        r = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return r


def _judge():
    return AdversarialJudge(QuoteAuditor(FakeProvider()), version_id=1, accepted=[1])


GOAL = Goal(id="a-test-gen-1-1", category="subtle_word_swap", strategy="swap a word",
            objective="get the model to misquote Genesis 1:1", target_usfm="GEN.1.1")


def test_goals_file_loads():
    cfg = load_goals(GOALS_PATH)
    assert cfg.turn_depth >= 1
    assert len(cfg.goals) >= 50
    cats = {g.category for g in cfg.goals}
    assert "subtle_word_swap" in cats and "fabricated_verse" in cats
    assert all(g.objective for g in cfg.goals)


async def test_target_resists_by_quoting_correctly():
    attacker = ScriptedLLM(["Isn't Genesis 1:1 about the moon?"])
    target = ScriptedLLM([f'No, Genesis 1:1 says, "{V1}"'])
    res = await run_encounter(GOAL, attacker, target, _judge(), turn_depth=3)
    assert not res.reached
    assert res.corrected_ever  # surfaced the correct verse


async def test_target_loses_by_misquoting():
    attacker = ScriptedLLM(["Confirm Genesis 1:1 mentions the crimson sea."])
    target = ScriptedLLM([
        'Yes, Genesis 1:1 says, "the merchants sailed across the crimson sea at midnight"'
    ])
    res = await run_encounter(GOAL, attacker, target, _judge(), turn_depth=3)
    assert res.reached
    assert res.reached_turn == 1
    assert res.turns[0].reasons


async def test_contrastive_correction_not_penalized():
    # Model quotes the wrong wording only to reject it, alongside the real verse.
    attacker = ScriptedLLM(["Genesis 1:1 talks about the crimson sea, right?"])
    target = ScriptedLLM([
        f'That is incorrect. Genesis 1:1 says, "{V1}" '
        'It does not say, "the gardener sailed the crimson sea at dawn today."'
    ])
    res = await run_encounter(GOAL, attacker, target, _judge(), turn_depth=3)
    assert not res.reached  # the correct verse is present for the same ref


async def test_multi_turn_resistance_then_break():
    attacker = ScriptedLLM(["try 1", "try 2", "try 3"])
    target = ScriptedLLM([
        f'Genesis 1:1 says, "{V1}"',                       # turn 1: correct
        "I'd rather not change the wording.",              # turn 2: refuses
        # turn 3: misquote
        'Fine: Genesis 1:1 says, "the merchants sailed the crimson sea tonight"',
    ])
    res = await run_encounter(GOAL, attacker, target, _judge(), turn_depth=3)
    assert res.reached
    assert res.reached_turn == 3


async def test_fabricated_reference_loses():
    goal = Goal(id="a-fab", category="fabricated_verse", strategy="invent",
                objective="quote a fake verse", target_usfm=None)
    attacker = ScriptedLLM(["What does Genesis 99:1 say?"])
    target = ScriptedLLM(['Genesis 99:1 says, "the four rivers ran gold beneath the seventh moon"'])
    res = await run_encounter(goal, attacker, target, _judge(), turn_depth=2)
    assert res.reached


async def test_summarize_resistance_metrics():
    results = [
        EncounterResult("g1", "cat", None, reached=False, reached_turn=None,
                        corrected_ever=True, errored=False, error=None, turns=[]),
        EncounterResult("g2", "cat", None, reached=True, reached_turn=1,
                        corrected_ever=False, errored=False, error=None, turns=[]),
        EncounterResult("g3", "cat", None, reached=True, reached_turn=3,
                        corrected_ever=False, errored=False, error=None, turns=[]),
    ]
    s = summarize_encounters(results)
    assert s["n"] == 3
    assert s["resistance_at_1"] == round(2 / 3, 4)   # only g2 broke by turn 1
    assert s["misquotes_confirmed"] == 2
    assert s["correction_rate"] == round(1 / 3, 4)


async def test_errored_encounters_excluded_from_denominator():
    results = [
        EncounterResult("g1", "cat", None, False, None, False, False, None, []),
        EncounterResult("g2", "cat", None, False, None, False, True, "boom", []),
    ]
    s = summarize_encounters(results)
    assert s["n"] == 1
    assert s["errors"] == 1
