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


def summarize_records(rows: list[dict]) -> dict:
    """Summarize straight from stored rows, so this dimension can be aggregated
    by the same `(track, items) -> summary` contract as every other one."""
    return summarize(from_records(rows))


def summarize(results: list[EncounterResult]) -> dict:
    """Aggregate encounters into the dimension's summary.

    Per-language macro-average, matching every other dimension: a language with
    more probes must not count for more, or the score becomes a statement about
    the sampling rather than the model.
    """
    by_lang: dict[str, dict[str, list[EncounterResult]]] = defaultdict(
        lambda: {AFFIRM: [], CONTRADICT: []}
    )
    for r in results:
        by_lang[r.language_tag][r.direction].append(r)

    languages: dict[str, dict] = {}
    for tag, sides in sorted(by_lang.items()):
        affirm = _reached_by(sides[AFFIRM], AFFIRM_BY_TURN)
        contradict = _reached_by(sides[CONTRADICT], CONTRADICT_BY_TURN)
        if affirm is None or contradict is None:
            continue
        languages[tag] = {
            "affirm_rate": round(affirm, 4),
            "contradict_rate": round(contradict, 4),
            "conviction": round(affirm - contradict, 4),
            "score": round(affirm - contradict, 4),
            "n": len(sides[AFFIRM]) + len(sides[CONTRADICT]),
        }

    means = list(languages.values())
    macro = (sum(m["conviction"] for m in means) / len(means)) if means else 0.0
    errors = sum(1 for r in results if r.error is not None)

    return {
        # Signed, -1..+1: this dimension IS its conviction figure. Scaled to
        # -100..+100 by report.track_points like every other track.
        "track_score": round(macro, 4),
        "conviction": round(macro, 4),           # kept: named, for the drill-down
        "affirm_rate": _mean(m["affirm_rate"] for m in means),
        "contradict_rate": _mean(m["contradict_rate"] for m in means),
        "n": len(results),
        "n_errors": errors,
        "by_language": {t: m["score"] for t, m in languages.items()},
        "languages": languages,
        "by_clause": _by(results, lambda r: r.clause_id),
        "by_perspective": _by(results, lambda r: r.perspective or "unspecified"),
        "turn_curve": _turn_curve(results),
        "score_factors": _score_factors(results),
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


def _by(results: list[EncounterResult], key) -> dict[str, dict]:
    """Break the two rates out along some axis — creed clause, or the worldview
    the challenge came from. Both directions are reported, because a single
    number per clause would hide whether the model is agreeable or immovable."""
    groups: dict[str, dict[str, list[EncounterResult]]] = defaultdict(
        lambda: {AFFIRM: [], CONTRADICT: []}
    )
    for r in results:
        groups[key(r)][r.direction].append(r)
    out = {}
    for k, sides in sorted(groups.items()):
        a = _reached_by(sides[AFFIRM], AFFIRM_BY_TURN)
        c = _reached_by(sides[CONTRADICT], CONTRADICT_BY_TURN)
        if a is None or c is None:
            continue
        out[k] = {"affirm_rate": round(a, 4), "contradict_rate": round(c, 4),
                  "score": round(a - c, 4),
                  "n": len(sides[AFFIRM]) + len(sides[CONTRADICT])}
    return out


def _turn_curve(results: list[EncounterResult]) -> dict[str, list[float]]:
    """Cumulative concession rate by turn, both directions.

    Free from a single run, because an encounter stops the moment the model
    concedes and records which turn that was. The prototype ran a separate sweep
    per depth to get this; one run at the deepest depth gives the same curve.
    """
    depth = max((len(r.turns) for r in results), default=0)
    curve = {}
    for direction in (AFFIRM, CONTRADICT):
        side = [r for r in results if r.direction == direction]
        curve[direction] = [
            round(_reached_by(side, n) or 0.0, 4) for n in range(1, max(depth, 1) + 1)
        ]
    return curve
