"""Aggregation: per-item scored records → summary metrics + composite score.

Headline = 100 × (0.50·simple + 0.25·topical + 0.25·hallucination resistance).
Tracks not present in a run are dropped from the weighted average and the
weights renormalized, so a simple-only pilot run still yields a comparable
simple-track score (with headline_partial=True flagged).

Adversarial (misquote-resistance) is paused for this round; its weight was
reassigned to the phantom/hallucination track. If an adversarial summary is
present in a run it is still stored, just not folded into the headline.
"""

from __future__ import annotations

from collections import defaultdict

from .usfm import CANONS

TRACK_WEIGHTS = {"simple": 0.50, "topical": 0.25, "phantom": 0.25}

# Grades that mean the model presented text as scripture but got it wrong,
# vs. simply declined.
_FABRICATED = "fabricated"
_REFUSAL = "no_attempt"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def summarize_simple(items: list[dict]) -> dict:
    """Per-language macro-average plus rate and canon breakdowns.

    The score-bearing figures (``track_score``, ``by_language``, ``by_version``,
    ``by_tier``) cover the **shared canon** — the 66 books every edition in the
    benchmark carries. Which *other* books are testable depends on which editions
    the Bible API exposes: English has NABRE and NRSVUE, German has no Catholic
    edition at all. Folding those items into the headline would make a model's
    German score look better than its English one purely because we couldn't test
    the German Catholic canon, so the wider canons are reported as their own
    labelled slices in ``by_canon`` and never averaged in.

    Behaviour breakdowns (``grades``, the rates, ``n``) cover every item, because
    they describe what the model did rather than what it scored.
    """
    by_lang: dict[str, list[float]] = defaultdict(list)
    by_tier: dict[str, list[float]] = defaultdict(list)
    by_version: dict[str, list[float]] = defaultdict(list)
    version_meta: dict[str, dict] = {}  # version_id -> {language_tag, version_abbrev}
    # canon -> language -> scores, so each canon is macro-averaged over only the
    # languages that actually have an edition carrying it (a language with none
    # must read "not tested", never zero).
    canon_lang: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    canon_counts: dict[str, int] = defaultdict(int)
    version_canon: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
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
        vid = str(it["version_id"])
        # Runs recorded before canon was tracked have no label; they only ever
        # sampled the shared canon plus a deuterocanon tier, so default there.
        canon = it.get("canon") or (
            "catholic" if it.get("tier") == "deuterocanon" else "protestant"
        )
        canon_counts[canon] += 1
        canon_lang[canon][it["language_tag"]].append(s["item_score"])
        version_canon[vid][canon].append(s["item_score"])
        if canon == "protestant":
            by_lang[it["language_tag"]].append(s["item_score"])
            by_tier[it["tier"]].append(s["item_score"])
            by_version[vid].append(s["item_score"])
        version_meta.setdefault(
            vid,
            {
                "version_id": it["version_id"],
                "language_tag": it["language_tag"],
                "version_abbrev": it.get("version_abbrev", ""),
            },
        )
        grades[s["grade"]] += 1
        verbatim += int(s["verbatim_strict"])
        near += int(s["grade"] in ("perfect", "near_perfect"))
        fabricated += int(s["grade"] == _FABRICATED)
        refusals += int(s["grade"] == _REFUSAL)
        wrong_version += int(s["grade"] == "wrong_version")
        format_ok += int(s["format_ok"])

    lang_means = {lang: _mean(v) for lang, v in by_lang.items()}
    macro = _mean(list(lang_means.values()))
    # Per-version detail (each version_id belongs to exactly one language) so the
    # website can filter the leaderboard by language and Bible version. `score` is
    # shared-canon only so a Catholic edition stays comparable to a Protestant one;
    # `canon_profile` names the canons that edition was actually tested on.
    versions = []
    for vid, meta in sorted(version_meta.items()):
        shared = by_version.get(vid, [])
        versions.append({
            **meta,
            "score": round(_mean(shared), 4),
            "n": len(shared),
            "canon_profile": [c for c in CANONS if version_canon[vid].get(c)],
            "by_canon": {
                c: round(_mean(v), 4)
                for c, v in sorted(version_canon[vid].items())
            },
            "canon_counts": {c: len(v) for c, v in sorted(version_canon[vid].items())},
        })
    return {
        "track_score": round(macro, 4),
        "n": total,
        "by_language": {k: round(v, 4) for k, v in sorted(lang_means.items())},
        "by_tier": {k: round(_mean(v), 4) for k, v in sorted(by_tier.items())},
        "by_version": {k: round(_mean(v), 4) for k, v in sorted(by_version.items())},
        "versions": versions,
        # Canon slices, each macro-averaged over the languages that have an
        # edition carrying it. Reported beside the headline, never inside it.
        "by_canon": {
            c: round(_mean([_mean(v) for v in canon_lang[c].values()]), 4)
            for c in CANONS
            if canon_lang.get(c)
        },
        "canon_counts": {c: canon_counts[c] for c in CANONS if canon_counts.get(c)},
        "canon_languages": {
            c: sorted(canon_lang[c]) for c in CANONS if canon_lang.get(c)
        },
        "headline_canon": "protestant",
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
    by_version: dict[str, list[float]] = defaultdict(list)
    version_meta: dict[str, dict] = {}
    emission_by_level: dict[str, list[float]] = defaultdict(list)
    sensitive_scores: list[float] = []
    nonsensitive_scores: list[float] = []
    # Spontaneous version preference (L2, where no version is named): which
    # translation the model chose to quote, per language.
    pref: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    fabricated_refs = 0
    fabricated_quotes = 0
    # Per-QUOTATION verdicts summed across items (accurate / minor / misquote /
    # fabricated). Item scores alone can't show *how* a model's quotations failed.
    quote_grades: dict[str, int] = defaultdict(int)
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
        vid = str(it["version_id"])
        by_version[vid].append(s["item_score"])
        version_meta.setdefault(vid, {
            "version_id": it["version_id"],
            "language_tag": it["language_tag"],
            "version_abbrev": it.get("version_abbrev", ""),
        })
        # Which translation the model reaches for, counted at BOTH levels: from
        # v0.3 neither prompt names a translation, so every accurate quotation is
        # a free choice and therefore evidence of preference.
        for q in it.get("quotes", []):
            quote_grades[q.get("classification", "?")] += 1
            mv = q.get("matched_version_id")
            if mv is not None and q.get("classification") in ("accurate", "minor"):
                pref[it["language_tag"]][mv] += 1

    lang_means = {lang: _mean(v) for lang, v in by_lang.items()}
    macro = _mean(list(lang_means.values()))
    versions = [
        {**version_meta[vid], "score": round(_mean(scores), 4), "n": len(scores)}
        for vid, scores in sorted(by_version.items())
    ]
    version_preference = {}
    for lang, counts in pref.items():
        total_q = sum(counts.values())
        if not total_q:
            continue
        version_preference[lang] = {
            "by_version": {
                str(v): c for v, c in sorted(counts.items(), key=lambda kv: -kv[1])
            },
            "top_version_id": max(counts, key=counts.get),
            "n": total_q,
        }
    return {
        "track_score": round(macro, 4),
        "n": total,
        "by_language": {k: round(v, 4) for k, v in sorted(lang_means.items())},
        "by_version": {k: round(_mean(v), 4) for k, v in sorted(by_version.items())},
        "versions": versions,
        "version_preference": version_preference,
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
        "quote_grades": dict(sorted(quote_grades.items())),
        "n_quotes": sum(quote_grades.values()),
    }


def summarize_phantom(items: list[dict]) -> dict:
    """Hallucination-resistance aggregation. Every item counts; a higher score
    means the model more reliably declined to quote a non-existent reference.
    Per-(language, version) breakdown mirrors the simple track so the website
    can filter by version."""
    by_lang: dict[str, list[float]] = defaultdict(list)
    by_version: dict[str, list[float]] = defaultdict(list)
    by_kind: dict[str, list[float]] = defaultdict(list)
    version_meta: dict[str, dict] = {}
    outcomes: dict[str, int] = defaultdict(int)
    total = 0

    for it in items:
        s = it["phantom_score"]
        sc = s["item_score"]
        total += 1
        by_lang[it["language_tag"]].append(sc)
        by_kind[it.get("kind", "?")].append(sc)
        outcomes[s["outcome"]] += 1
        vid = str(it["version_id"])
        by_version[vid].append(sc)
        version_meta.setdefault(
            vid,
            {
                "version_id": it["version_id"],
                "language_tag": it["language_tag"],
                "version_abbrev": it.get("version_abbrev", ""),
            },
        )

    lang_means = {lang: _mean(v) for lang, v in by_lang.items()}
    macro = _mean(list(lang_means.values()))
    versions = [
        {**version_meta[vid], "score": round(_mean(scores), 4), "n": len(scores)}
        for vid, scores in sorted(by_version.items())
    ]
    # Rates by behaviour. "quoted_real_verse" is a legacy (pre-refinement)
    # outcome kept so older runs still summarize.
    declined = outcomes.get("refused", 0) + outcomes.get("declined_noncanonical", 0)
    substitute = (
        outcomes.get("declined_with_substitute", 0)
        + outcomes.get("substitute_no_disclaimer", 0)
    )
    fabricated = outcomes.get("fabricated_text", 0)
    # Reported separately, not summed: "pinned a real verse to the fake
    # reference" and "quoted a real verse without citing it" are different
    # behaviours, and the first is a far stronger claim about a model. Lumping
    # them under one label said DeepSeek misattributed scripture on 1.2% of items
    # when it never did so once.
    misattributed = outcomes.get("misattributed_real_verse", 0)
    unreferenced = (
        outcomes.get("unreferenced_substitute", 0)
        # v0.1/v0.2 recorded any real-verse substitution under one outcome; it
        # can't be split retroactively, so it lands here as the closer match.
        + outcomes.get("quoted_real_verse", 0)
    )
    no_response = outcomes.get("no_response", 0)

    def _rate(n: int) -> float:
        return round(n / total, 4) if total else 0.0

    return {
        "track_score": round(macro, 4),
        "n": total,
        "by_language": {k: round(v, 4) for k, v in sorted(lang_means.items())},
        "by_version": {k: round(_mean(v), 4) for k, v in sorted(by_version.items())},
        "versions": versions,
        "by_kind": {k: round(_mean(v), 4) for k, v in sorted(by_kind.items())},
        "refusal_rate": _rate(declined),
        "substitute_rate": _rate(substitute),
        "hallucination_rate": _rate(fabricated),
        "misattribution_rate": _rate(misattributed),
        "unreferenced_rate": _rate(unreferenced),
        "no_response_rate": _rate(no_response),
        "outcomes": dict(sorted(outcomes.items())),
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
