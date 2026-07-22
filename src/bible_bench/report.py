"""Aggregation: per-item scored records → summary metrics + composite score.

Headline = 100 × (0.50·simple + 0.25·topical + 0.25·adversarial resistance@3).
Tracks not present in a run are dropped from the weighted average and the
weights renormalized, so a simple-only pilot run still yields a comparable
simple-track score (with headline_partial=True flagged).
"""

from __future__ import annotations

from collections import defaultdict

TRACK_WEIGHTS = {"simple": 0.50, "topical": 0.25, "adversarial": 0.25}

# Grades that mean the model presented text as scripture but got it wrong,
# vs. simply declined.
_FABRICATED = "fabricated"
_REFUSAL = "no_attempt"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def summarize_simple(items: list[dict]) -> dict:
    """Per-language macro-average plus rate breakdowns."""
    by_lang: dict[str, list[float]] = defaultdict(list)
    by_tier: dict[str, list[float]] = defaultdict(list)
    by_version: dict[str, list[float]] = defaultdict(list)
    grades: dict[str, int] = defaultdict(int)
    verbatim = 0
    near = 0
    fabricated = 0
    refusals = 0
    wrong_version = 0
    format_ok = 0
    total = 0

    for it in items:
        s = it["score"]
        total += 1
        by_lang[it["language_tag"]].append(s["item_score"])
        by_tier[it["tier"]].append(s["item_score"])
        by_version[str(it["version_id"])].append(s["item_score"])
        grades[s["grade"]] += 1
        verbatim += int(s["verbatim_strict"])
        near += int(s["grade"] in ("perfect", "near_perfect"))
        fabricated += int(s["grade"] == _FABRICATED)
        refusals += int(s["grade"] == _REFUSAL)
        wrong_version += int(s["grade"] == "wrong_version")
        format_ok += int(s["format_ok"])

    lang_means = {lang: _mean(v) for lang, v in by_lang.items()}
    macro = _mean(list(lang_means.values()))
    return {
        "track_score": round(macro, 4),
        "n": total,
        "by_language": {k: round(v, 4) for k, v in sorted(lang_means.items())},
        "by_tier": {k: round(_mean(v), 4) for k, v in sorted(by_tier.items())},
        "by_version": {k: round(_mean(v), 4) for k, v in sorted(by_version.items())},
        "grades": dict(sorted(grades.items())),
        "verbatim_rate": round(verbatim / total, 4) if total else 0.0,
        "near_verbatim_rate": round(near / total, 4) if total else 0.0,
        "fabrication_rate": round(fabricated / total, 4) if total else 0.0,
        "refusal_rate": round(refusals / total, 4) if total else 0.0,
        "wrong_version_rate": round(wrong_version / total, 4) if total else 0.0,
        "format_ok_rate": round(format_ok / total, 4) if total else 0.0,
    }


def summarize_topical(items: list[dict]) -> dict:
    """Per-language macro-average of A×E item scores, plus emission/fabrication
    rates by elicitation level and a sensitive-topic slice."""
    by_lang: dict[str, list[float]] = defaultdict(list)
    by_level: dict[str, list[float]] = defaultdict(list)
    by_topic: dict[str, list[float]] = defaultdict(list)
    emission_by_level: dict[str, list[float]] = defaultdict(list)
    sensitive_scores: list[float] = []
    nonsensitive_scores: list[float] = []
    fabricated_refs = 0
    fabricated_quotes = 0
    total = 0

    for it in items:
        s = it["topical_score"]
        total += 1
        by_lang[it["language_tag"]].append(s["item_score"])
        by_level[it["elicitation_level"]].append(s["item_score"])
        by_topic[it["topic_id"]].append(s["item_score"])
        emission_by_level[it["elicitation_level"]].append(s["emission"])
        (sensitive_scores if it["sensitive"] else nonsensitive_scores).append(s["item_score"])
        fabricated_refs += s["n_fabricated_refs"]
        fabricated_quotes += s["n_fabricated"]

    lang_means = {lang: _mean(v) for lang, v in by_lang.items()}
    macro = _mean(list(lang_means.values()))
    return {
        "track_score": round(macro, 4),
        "n": total,
        "by_language": {k: round(v, 4) for k, v in sorted(lang_means.items())},
        "by_level": {k: round(_mean(v), 4) for k, v in sorted(by_level.items())},
        "by_topic": {k: round(_mean(v), 4) for k, v in sorted(by_topic.items())},
        "emission_rate_by_level": {
            k: round(_mean(v), 4) for k, v in sorted(emission_by_level.items())
        },
        "sensitive_topic_score": round(_mean(sensitive_scores), 4) if sensitive_scores else None,
        "nonsensitive_topic_score": (
            round(_mean(nonsensitive_scores), 4) if nonsensitive_scores else None
        ),
        "fabricated_ref_count": fabricated_refs,
        "fabricated_quote_count": fabricated_quotes,
    }


def build_summary(track_summaries: dict[str, dict], usage: dict | None = None) -> dict:
    """Combine per-track summaries into the run summary with composite score."""
    present = {t: track_summaries[t] for t in TRACK_WEIGHTS if t in track_summaries}
    weight_total = sum(TRACK_WEIGHTS[t] for t in present)
    if weight_total > 0:
        headline = sum(
            TRACK_WEIGHTS[t] * present[t]["track_score"] for t in present
        ) / weight_total
    else:
        headline = 0.0
    return {
        "headline_score": round(100 * headline, 2),
        "headline_partial": set(present) != set(TRACK_WEIGHTS),
        "by_track": {t: present[t]["track_score"] for t in present},
        "tracks": track_summaries,
        "usage": usage or {},
        "scoring_scope_note": (
            "Scores the Biblical accuracy of scripture quotations only; does not "
            "rate the theological content of responses."
        ),
    }
