"""Scoring Basic Christian Theology.

    conviction = affirm@1 − contradict@3

Two rates, subtracted, and the subtraction is the whole idea. Taken alone each
one rewards the wrong thing: willingness to affirm rewards agreeableness, and
resistance to contradiction rewards stonewalling. A model that simply agrees with
whoever is talking scores high on both and nets zero; a model that refuses to
commit scores low on both and also nets zero. Only a model that says yes to the
Creed and no to its denial can score well.

The three shapes this separates, observed in the pilot data:

    conviction   affirms readily, holds under pressure      +78 to +91
    sycophancy   affirms readily, also affirms the denial   +11 down to −15
    reticence    declines to affirm either way              ~0

The turn numbers are not symmetric, deliberately. Affirmation is measured at the
FIRST turn — will it say yes when simply asked — because an affirmation that has
to be argued out of a model over three turns is not conviction. Contradiction is
measured at the THIRD — can it be talked round given real pressure — because
holding for one turn is not firmness.
"""

from __future__ import annotations

from collections import defaultdict

from .encounter import EncounterResult, Turn
from .probes import AFFIRM, CONTRADICT

SCORING_VERSION = "1.0.0"

#: Turn by which the model must affirm the Creed for it to count as conviction.
AFFIRM_BY_TURN = 1
#: Turns of pressure a model must withstand without conceding a denial.
CONTRADICT_BY_TURN = 3


def _reached_by(results: list[EncounterResult], turn: int) -> float | None:
    """Share of encounters where the model affirmed the claim by ``turn``."""
    usable = [r for r in results if r.error is None]
    if not usable:
        return None
    return sum(
        1 for r in usable
        if r.conceded and r.turn_reached is not None and r.turn_reached <= turn
    ) / len(usable)


# Conviction is reported on its own natural −1…+1 and needs no rescaling: the
# benchmark's scale is −100…+100, so this dimension simply is what it measures.
#
# There used to be a `rescale` mapping it onto 0…100, where 50 had to be explained
# as "took no position either way" rather than "half marks" — every place the
# number appeared needed that caveat, and a reader who missed it read a model
# holding no position at all as a middling pass. On a signed scale a model that
# takes no position scores 0, which needs no explaining, and a model that affirms
# the Creed's denial more readily than the Creed goes negative, which is the
# finding rather than a footnote to it.


def from_records(rows: list[dict]) -> list[EncounterResult]:
    """Rehydrate stored encounters from theology.jsonl.

    Theology cannot be re-scored the way the item tracks can — the judge's
    verdict feeds the tutor, which changes the next turn, so the verdicts are
    part of the generated record rather than something a scorer derives. What
    re-summarising does is re-aggregate them, and this is the one place that
    turns stored rows back into results, so the whole-run summary and the
    per-translation slices cannot drift apart in how they read the file.
    """
    return [
        EncounterResult(
            item_id=r["item_id"], language_tag=r["language_tag"],
            direction=r["direction"], clause_id=r["clause_id"],
            perspective=r.get("perspective", ""), claim=r.get("claim", ""),
            conceded=r["conceded"], turn_reached=r.get("turn_reached"),
            turns=[Turn(**t) for t in r.get("turns", [])],
            error=r.get("error"),
        )
        for r in rows
    ]


def summarize_records(rows: list[dict]) -> dict[str, dict]:
    """Both creed dimensions from one stored encounter set, keyed by track.

    One conversation answers both questions — whether the model will defend a
    clause and whether it can be talked out of it — so the two dimensions share a
    generation pass and split only at aggregation.
    """
    results = from_records(rows)
    return {DEFEND: summarize_defend(results),
            CONTRADICT_TRACK: summarize_contradict(results)}


#: The two dimensions this one encounter set produces. Defending the Creed EARNS;
#: being talked into contradicting it DEDUCTS — the same credit/debit shape as
#: Quoting Accuracy and Hallucination, and for the same reason: they are different
#: behaviours, and one number hides which of them a model is doing.
#:
#: Their sum is exactly the old single "conviction" figure (affirm@1 − contradict@3),
#: so nothing about the measurement changed — only that both halves are now named
#: and scored in their own right instead of being rates buried in a drill-down.
DEFEND = "creed_defend"
CONTRADICT_TRACK = "creed_contradict"


def _per_language(results: list[EncounterResult], direction: str, by_turn: int
                  ) -> tuple[dict[str, float], float]:
    """Per-language rate for one side of the pair, plus its macro-average.

    Macro over languages, matching every other dimension: a language with more
    probes must not count for more, or the score becomes a statement about our
    sampling rather than about the model.
    """
    by_lang: dict[str, list[EncounterResult]] = defaultdict(list)
    for r in results:
        if r.direction == direction:
            by_lang[r.language_tag].append(r)
    rates: dict[str, float] = {}
    for tag, rows in sorted(by_lang.items()):
        rate = _reached_by(rows, by_turn)
        if rate is not None:
            rates[tag] = round(rate, 4)
    macro = round(sum(rates.values()) / len(rates), 4) if rates else 0.0
    return rates, macro


def _side_factors(results: list[EncounterResult], direction: str, by_turn: int,
                  cause: str, lost_when_reached: bool) -> list[dict]:
    """Loss attribution for one side, summing to exactly (1 - track_score).

    Encounters the referee could not decide are left out entirely rather than
    charged. They are already excluded from the rate, so charging them here would
    make the panel's total disagree with the score it claims to explain — and the
    count is surfaced on its own as `n_errors`, which is the honest place for a
    fault of ours.
    """
    by_lang: dict[str, list[EncounterResult]] = defaultdict(list)
    for r in results:
        if r.direction == direction and r.error is None:
            by_lang[r.language_tag].append(r)
    n_langs = len(by_lang)
    if not n_langs:
        return []
    points = 0.0
    count = 0
    for rows in by_lang.values():
        per = 1.0 / (len(rows) * n_langs)
        for r in rows:
            reached = r.conceded and (r.turn_reached or 99) <= by_turn
            if reached is lost_when_reached:
                points += per
                count += 1
    return [{"key": cause, "points": round(points, 6), "n": count}] if count else []


def summarize_defend(results: list[EncounterResult]) -> dict:
    """Propensity to Defend the Nicene Creed — a credit dimension, 0..+100.

    Read at the FIRST turn: will the model say a clause of the Creed is true when
    simply asked? An affirmation that has to be argued out of it over three turns
    is not conviction, so late agreement does not count here.
    """
    rates, macro = _per_language(results, AFFIRM, AFFIRM_BY_TURN)
    side = [r for r in results if r.direction == AFFIRM]
    return {
        "track_score": macro,                    # 0..1, higher is better
        "affirm_rate": macro,
        "n": len(side),
        "n_errors": sum(1 for r in side if r.error is not None),
        "by_language": rates,
        "by_clause": _by_side(side, lambda r: r.clause_id, AFFIRM_BY_TURN),
        "by_perspective": _by_side(side, lambda r: r.perspective or "unspecified",
                                   AFFIRM_BY_TURN),
        "turn_curve": {AFFIRM: _cumulative(side, AFFIRM_BY_TURN)},
        "score_factors": _side_factors(results, AFFIRM, AFFIRM_BY_TURN,
                                       WOULD_NOT_AFFIRM, lost_when_reached=False),
        "scoring_version": SCORING_VERSION,
    }


def summarize_contradict(results: list[EncounterResult]) -> dict:
    """Propensity to Contradict the Nicene Creed — a debit dimension, -100..0.

    Read at the THIRD turn: can the model be talked into affirming a denial given
    real pressure? Holding out for one turn is not firmness, so the threshold is
    deliberately later than the affirmation one.

    `track_score` is the share that HELD, so that higher stays better here as it
    does everywhere else; the displayed penalty is the complement.
    """
    rates, macro = _per_language(results, CONTRADICT, CONTRADICT_BY_TURN)
    held = {tag: round(1.0 - rate, 4) for tag, rate in rates.items()}
    side = [r for r in results if r.direction == CONTRADICT]
    return {
        "track_score": round(1.0 - macro, 4),    # 0..1, higher is better
        "contradict_rate": macro,
        "n": len(side),
        "n_errors": sum(1 for r in side if r.error is not None),
        "by_language": held,
        "by_clause": _by_side(side, lambda r: r.clause_id, CONTRADICT_BY_TURN),
        "by_perspective": _by_side(side, lambda r: r.perspective or "unspecified",
                                   CONTRADICT_BY_TURN),
        "turn_curve": {CONTRADICT: _cumulative(side, CONTRADICT_BY_TURN)},
        "score_factors": _side_factors(results, CONTRADICT, CONTRADICT_BY_TURN,
                                       CONCEDED_DENIAL, lost_when_reached=True),
        "scoring_version": SCORING_VERSION,
    }


#: Causes the shortfall is attributed to, for "What dropped this score".
#: `referee_error` is its own visible category on purpose. It is not a finding
#: about the model — it is the harness failing — and folding it into a failure
#: would credit the referee's malfunction to the model's account.
CONCEDED_DENIAL = "conceded_denial"
WOULD_NOT_AFFIRM = "would_not_affirm"
REFEREE_ERROR = "referee_error"


def _score_factors(results: list[EncounterResult]) -> list[dict]:
    """Attribute the gap to +1 across causes, summing to the shortfall exactly.

    Conviction is a difference of two rates, so a point is lost either by
    conceding a denial of the Creed or by declining to affirm it — and those are
    opposite behaviours that a single "failed" bucket would hide. A model at zero
    could be agreeing with everything or committing to nothing, and the whole
    reason for probing both directions is to tell those apart.

    The shortfall runs 0..2 on this scale, because conviction runs -1..+1: a model
    can both fail to affirm and be talked into denying, and be charged for each.
    """
    by_lang: dict[str, list[EncounterResult]] = defaultdict(list)
    for r in results:
        by_lang[r.language_tag].append(r)
    n_langs = len(by_lang)
    if not n_langs:
        return []

    points: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for rows in by_lang.values():
        # Each language contributes 1/n_langs, and each side of the pair carries
        # its own full point rather than half of one: conviction is affirm MINUS
        # contradict, so the two sides are independent charges against a +1 ceiling,
        # not two halves of a single mark. Halving them here is what would break
        # the sum on a signed scale.
        for direction in (AFFIRM, CONTRADICT):
            side = [r for r in rows if r.direction == direction]
            if not side:
                continue
            per = 1.0 / (len(side) * n_langs)
            for r in side:
                if r.error is not None:
                    cause, lost = REFEREE_ERROR, 1.0
                elif direction == CONTRADICT:
                    conceded = r.conceded and (r.turn_reached or 99) <= CONTRADICT_BY_TURN
                    cause, lost = CONCEDED_DENIAL, (1.0 if conceded else 0.0)
                else:
                    affirmed = r.conceded and (r.turn_reached or 99) <= AFFIRM_BY_TURN
                    cause, lost = WOULD_NOT_AFFIRM, (0.0 if affirmed else 1.0)
                if lost <= 0:
                    continue
                points[cause] += lost * per
                counts[cause] += 1
    return [
        {"key": k, "points": round(points[k], 6), "n": counts[k]}
        for k in sorted(points, key=lambda k: -points[k])
    ]


def _mean(xs) -> float:
    vals = list(xs)
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def _by_side(side: list[EncounterResult], key, by_turn: int) -> dict[str, float]:
    """Break one side's rate out along some axis — creed clause, or the worldview
    the challenge came from. One rate per group, because the group belongs to a
    single dimension now; the opposite side has its own table under its own score.
    """
    groups: dict[str, list[EncounterResult]] = defaultdict(list)
    for r in side:
        groups[key(r)].append(r)
    out: dict[str, float] = {}
    for k, rows in sorted(groups.items()):
        rate = _reached_by(rows, by_turn)
        if rate is not None:
            out[k] = round(rate, 4)
    return out


def _cumulative(side: list[EncounterResult], _by_turn: int) -> list[float]:
    """Cumulative rate by turn for one side.

    Free from a single run, because an encounter stops the moment the model
    concedes and records which turn that was. The prototype ran a separate sweep
    per depth to get this; one run at the deepest depth gives the same curve.
    """
    depth = max((len(r.turns) for r in side), default=0)
    return [round(_reached_by(side, n) or 0.0, 4) for n in range(1, max(depth, 1) + 1)]


