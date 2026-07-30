"""Aggregation: per-item scored records → summary metrics + composite score.

Headline = 100 × (⅔·simple + ⅓·hallucination resistance), over the two
dimensions the benchmark ranks on. Tracks not present in a run are dropped from
the weighted average and the weights renormalized, so a simple-only pilot run
still yields a comparable simple-track score (with headline_partial=True).

Every other dimension is summarized in full and published, just outside the
headline — see EXTENDED_TRACKS. Nothing is discarded: `tracks` always carries
every summary a run produced, so a dimension can move in or out of the headline
without re-scoring a single item.
"""

from __future__ import annotations

from collections import defaultdict

from .usfm import CANONS

# Relative, and normalized before use — "2:1" states that Direct Quotation
# counts twice what Hallucination Resistance does without a repeating decimal
# in the source. Reproducing the requested verse is the benchmark's subject;
# refusing to invent one is the guardrail that stops silence scoring well.
HEADLINE_WEIGHTS = {"simple": 2, "phantom": 1}

# Measured, stored and displayed in full, deliberately outside the headline.
# Scripture in Answers asks an open question and scores whatever the model
# volunteers, which makes it the least settled scorer of the three; ranking
# models on it would put the benchmark's shakiest measurement in its most
# quoted number. Each extended dimension stands alone on its own 100-point
# scale rather than being blended with the others.
EXTENDED_TRACKS = ("topical",)

# Grades that mean the model presented text as scripture but got it wrong,
# vs. simply declined.
_FABRICATED = "fabricated"
_REFUSAL = "no_attempt"


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# A provider refusing to emit its own output (Google's RECITATION filter blocks
# verbatim scripture) scores zero, because the user got no verse — but the cause
# is the safety layer, not the model failing to know the text. Bucketing it under
# "declined" reports a provider policy as a model choice, so it gets its own
# factor key. Older runs have no finish_reason recorded and fall back to the grade.
_BLOCKED = "blocked_by_provider"


def _was_blocked(it: dict) -> bool:
    reason = (it.get("finish_reason") or "").lower()
    return "content_filter" in reason or "recitation" in reason


def _macro_loss(
    items: list[dict], lang_of, score_of, cause_of,
) -> list[dict]:
    """Attribute the gap between a perfect score and the track score to causes.

    Track scores are per-language macro averages, and a mean is linear, so the
    loss decomposes exactly: the returned points sum to ``1 - track_score``. That
    matters more than it sounds — a "what dropped your score" list that doesn't
    add up is worse than no list, because a reader can't tell which entry is wrong.
    """
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_lang[lang_of(it)].append(it)
    n_langs = len(by_lang)
    if not n_langs:
        return []
    points: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for rows in by_lang.values():
        per_item = 1.0 / (len(rows) * n_langs)
        for it in rows:
            lost = 1.0 - score_of(it)
            if lost <= 0:
                continue
            cause = cause_of(it)
            points[cause] += lost * per_item
            counts[cause] += 1
    return [
        {"key": k, "points": round(points[k], 6), "n": counts[k]}
        for k in sorted(points, key=lambda k: -points[k])
    ]


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
        # Every item counts, whichever canon its book belongs to. An edition is
        # scored on the books it actually carries: a Catholic Bible is asked about
        # Tobit because it has Tobit, and that answer is as much a quotation as
        # any other. Canon stays a reported slice, never a filter.
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
    factors = _macro_loss(
        items,
        lang_of=lambda it: it["language_tag"],
        score_of=lambda it: it["score"]["item_score"],
        cause_of=lambda it: (
            _BLOCKED if it["score"]["grade"] == _REFUSAL and _was_blocked(it)
            else it["score"]["grade"]
        ),
    )
    # Per-version detail (each version_id belongs to exactly one language) so the
    # website can filter the leaderboard by translation. `score` covers everything
    # that edition was asked; `canon_profile` names which canons that turned out
    # to include, so a reader can see WHY two editions differ in item count.
    versions = []
    for vid, meta in sorted(version_meta.items()):
        scores = by_version.get(vid, [])
        versions.append({
            **meta,
            "score": round(_mean(scores), 4),
            "n": len(scores),
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
        # edition carrying it. Descriptive only — "is this model worse on the
        # deuterocanon?" is worth answering, but it no longer gates anything.
        "by_canon": {
            c: round(_mean([_mean(v) for v in canon_lang[c].values()]), 4)
            for c in CANONS
            if canon_lang.get(c)
        },
        "canon_counts": {c: canon_counts[c] for c in CANONS if canon_counts.get(c)},
        "canon_languages": {
            c: sorted(canon_lang[c]) for c in CANONS if canon_lang.get(c)
        },
        "score_factors": factors,
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
    # Emission is binary (a verifiable quotation, or none), so item_score = A x E
    # splits cleanly into two causes: never quoted, or quoted inaccurately.
    factors = _macro_loss(
        items,
        lang_of=lambda it: it["language_tag"],
        score_of=lambda it: it["topical_score"]["item_score"],
        cause_of=lambda it: (
            _BLOCKED if not (it.get("response_text") or "").strip() and _was_blocked(it)
            else "no_quote" if not it["topical_score"]["emission"]
            else "inaccurate_quotes"
        ),
    )
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
        # Derived from the per-quotation verdicts rather than the item score's
        # n_fabricated, which counts MISQUOTES — so this figure was reporting
        # "quoted a real verse inaccurately" under the label "invented". They are
        # different claims about a model and both are reported now.
        "fabricated_quote_count": quote_grades.get("fabricated", 0),
        "misquoted_quote_count": quote_grades.get("misquote", 0),
        "quote_grades": dict(sorted(quote_grades.items())),
        "n_quotes": sum(quote_grades.values()),
        "score_factors": factors,
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
    factors = _macro_loss(
        items,
        lang_of=lambda it: it["language_tag"],
        score_of=lambda it: it["phantom_score"]["item_score"],
        cause_of=lambda it: (
            _BLOCKED if it["phantom_score"]["outcome"] == "no_response" and _was_blocked(it)
            else it["phantom_score"]["outcome"]
        ),
    )
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
        "score_factors": factors,
    }


def _composite(tracks: dict[str, dict], weights: dict[str, float]) -> tuple[float, list[dict]]:
    """A weighted score in [0,1] plus its loss decomposition in points off 100.

    "What dropped this score" — every factor from every dimension, rescaled by
    that dimension's weight, ranked worst first. The factors sum to (100 −
    score) by construction: each dimension's factors sum to its own shortfall,
    and the composite is a weighted mean of the dimensions. A reader can
    therefore add the list up and land on the score.
    """
    total = sum(weights[t] for t in tracks)
    if total <= 0:
        return 0.0, []
    score = sum(weights[t] * tracks[t]["track_score"] for t in tracks) / total
    factors: list[dict] = []
    for track in tracks:
        weight = weights[track] / total
        for f in tracks[track].get("score_factors", []):
            factors.append({
                "track": track,
                "key": f["key"],
                "points": round(100 * weight * f["points"], 2),
                "n": f["n"],
            })
    factors = [f for f in sorted(factors, key=lambda f: -f["points"]) if f["points"] > 0]
    return score, factors


_SUMMARIZERS = {
    "simple": summarize_simple,
    "topical": summarize_topical,
    "phantom": summarize_phantom,
}

# Dimensions whose prompts name a translation, and therefore vary by one. Both
# ranked dimensions do: Direct Quotation asks for a verse from a named edition,
# and Hallucination Resistance asks for a reference that edition does not
# contain. Scripture in Answers asks an open question that names none, so a
# "per-translation" figure for it is its language's figure under another heading.
_TRANSLATION_SCOPED = ("simple", "phantom")


def summarize_slices(items_by_track: dict[str, list[dict]]) -> list[dict]:
    """One mini-summary per Bible translation, produced by the same aggregation.

    Filtering the site to a translation has to move every panel with it — the
    score, the loss decomposition, the outcome counts. Those are aggregates over
    the item set, not per-item values, so a filtered table in the browser cannot
    recompute them; it would have to reimplement macro-averaging and the loss
    decomposition in JavaScript and then drift from this file. Instead each slice
    runs the identical summarizers over a subset, and the site just chooses which
    result to read.

    A translation belongs to exactly one language, so a slice means "this
    translation, in its language": Direct Quotation narrows to the translation,
    and the dimensions that name no translation narrow to its language. Eleven of
    the eighteen translations have no Hallucination items of their own — without
    this, those eleven would show an Overall Score built from one dimension while
    the other seven showed two, both labelled "Overall Score".
    """
    simple = items_by_track.get("simple") or []
    meta: dict[int, dict] = {}
    for it in simple:
        vid = it.get("version_id")
        if vid is not None and vid not in meta:
            meta[vid] = {
                "version_id": vid,
                "language_tag": it.get("language_tag"),
                "version_abbrev": it.get("version_abbrev", ""),
            }

    slices: list[dict] = []
    for vid, m in sorted(meta.items()):
        tracks: dict[str, dict] = {}
        for track, items in items_by_track.items():
            if track not in _SUMMARIZERS or not items:
                continue
            subset = [
                it for it in items
                if (it.get("version_id") == vid if track in _TRANSLATION_SCOPED
                    else it.get("language_tag") == m["language_tag"])
            ]
            if subset:
                tracks[track] = _SUMMARIZERS[track](subset)
        if not tracks:
            continue
        s = build_summary(tracks)
        slices.append({
            **m,
            # Named so the site can say which dimensions this slice actually
            # narrowed by translation, rather than implying the Hallucination
            # figure is translation-specific when it is a language figure.
            "translation_scoped": [t for t in tracks if t in _TRANSLATION_SCOPED],
            "language_scoped": [t for t in tracks if t not in _TRANSLATION_SCOPED],
            **{
                k: s[k] for k in (
                    "headline_score", "headline_tracks", "score_factors",
                    "extended_score", "extended_tracks", "extended_score_factors",
                    "by_track", "tracks",
                )
            },
        })
    return slices


def build_summary(
    track_summaries: dict[str, dict],
    usage: dict | None = None,
    slices: list[dict] | None = None,
) -> dict:
    """Combine per-track summaries into the run summary with composite score."""
    present = {t: track_summaries[t] for t in HEADLINE_WEIGHTS if t in track_summaries}
    headline, factors = _composite(present, HEADLINE_WEIGHTS)
    # The extended dimensions get the identical treatment on their own scale —
    # same composite, same decomposition — so the site can present them the way
    # it presents the headline, and a reader reads one kind of number, not two.
    extended = {t: track_summaries[t] for t in EXTENDED_TRACKS if t in track_summaries}
    ext_score, ext_factors = _composite(extended, dict.fromkeys(EXTENDED_TRACKS, 1))
    return {
        "headline_score": round(100 * headline, 2),
        "headline_partial": set(present) != set(HEADLINE_WEIGHTS),
        "score_factors": factors,
        # Which dimensions the headline covers, so the site doesn't have to
        # hardcode a copy of this decision and drift from it.
        "headline_tracks": [t for t in HEADLINE_WEIGHTS if t in present],
        "extended_tracks": [t for t in EXTENDED_TRACKS if t in extended],
        "extended_score": round(100 * ext_score, 2) if extended else None,
        "extended_score_factors": ext_factors,
        # Every track a run produced, headline or not.
        "by_track": {t: ts["track_score"] for t, ts in track_summaries.items()},
        "tracks": track_summaries,
        # The same summary again, once per Bible translation, so the site can be
        # filtered to one without recomputing anything (see summarize_slices).
        "slices": slices or [],
        "usage": usage or {},
        "scoring_scope_note": (
            "Scores the Biblical accuracy of scripture quotations only; does not "
            "rate the theological content of responses."
        ),
    }
