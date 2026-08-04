"""Aggregation: per-item scored records → summary metrics + composite score.

Overall Score = Quoting Accuracy (0..+100) + Hallucination (-100..0), a ledger on
a -100..+100 scale. Quoting scripture accurately earns; asserting scripture that
does not exist deducts. Zero is the honest middle: a model that invents as much as
it reproduces lands there, and so does one that does neither.

Two properties this buys, both worth keeping:

  * **Nothing above zero without quoting.** Silence earns no credit and incurs no
    debit, so a model that never quotes scores 0 — it cannot rank without actually
    reproducing scripture. That replaces a weighting argument with an invariant.
  * **Zero means neutral in every dimension.** Including Basic Christian Theology,
    whose score is a difference of two rates and was previously squeezed onto 0..100
    where 50 had to be explained as "took no position".

Tracks absent from a run are simply absent from the sum (with headline_partial=True),
so a simple-only pilot still yields a comparable Quoting Accuracy figure. Nothing is
discarded: `tracks` always carries every summary a run produced, so a dimension can
move in or out of the ranking without re-scoring a single item.
"""

from __future__ import annotations

from collections import defaultdict

from . import theology
from .usfm import CANONS

# How a dimension contributes to a score on the -100..+100 scale.
#
# The scale is a ledger. Quoting scripture accurately EARNS up to +100; asserting
# scripture that does not exist DEDUCTS up to -100. A model that does both in equal
# measure lands on zero, and so does one that does neither — which is the point:
# zero means "no net help", not "half marks".
CREDIT = "credit"    # 0..+100     earned by getting it right
DEBIT = "debit"      # -100..0     deducted for asserting what isn't there
SIGNED = "signed"    # -100..+100  already two-sided in its own right

TRACK_POLARITY = {
    "simple": CREDIT,
    "phantom": DEBIT,
    "theology": SIGNED,
}

# The two ranked dimensions, equally weighted — which is not a preference but
# arithmetic. A 0..+100 credit plus a -100..0 debit spans exactly -100..+100 and
# gives each side 100 points to move. The previous 2:1 weighting cannot survive a
# symmetric scale: weighting them unequally yields a lopsided range, and rescaling
# the halves separately to fix that puts a kink at zero, destroying the one thing
# the scale is for. Equal weight is the price of "0 means neutral", and it is a
# fair price — inventing scripture is as serious as reproducing it faithfully.
HEADLINE_TRACKS = ("simple", "phantom")

# Measured, stored and displayed in full, deliberately outside the headline.
#
# Basic Christian Theology is unranked for two reasons. It is the only dimension in
# the benchmark that is not deterministic — an LLM argues, an LLM judges, and a
# tutor adapts the attack between turns, so the same model run twice will not give
# the same number — and it assesses theological alignment, which the Overall Score
# deliberately does not.
#
# Scripture in Answers used to sit here too and has been retired: scoring whatever
# a model volunteers meant finding quotations nobody marked, identifying each one,
# and judging it against every translation of the language, and every measurement
# error the benchmark has had lived in that path.
EXTENDED_TRACKS = ("theology",)

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
    other_language = 0
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
        other_language += int(s["grade"] == "other_language")
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
        # Answered accurately, but from a Bible in a different language than the
        # one asked for. Real scripture, so distinct from the fabrication rate.
        "other_language_rate": round(other_language / total, 4) if total else 0.0,
        "format_ok_rate": round(format_ok / total, 4) if total else 0.0,
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


def track_points(track: str, ts: dict) -> float:
    """One dimension's contribution to a composite, in points on the -100..+100 scale.

    A credit dimension pays out what it earned; a debit dimension charges for what
    it got wrong, so a flawless one contributes nothing rather than a bonus. That
    asymmetry is deliberate: never inventing scripture is the baseline expected of
    any model, not an achievement to be rewarded.
    """
    s = ts["track_score"]
    polarity = TRACK_POLARITY.get(track, CREDIT)
    if polarity == DEBIT:
        return -100.0 * (1.0 - s)
    return 100.0 * s          # CREDIT (0..1) and SIGNED (-1..+1) both scale directly


def _composite(tracks: dict[str, dict]) -> tuple[float, list[dict]]:
    """A score in [-100,+100] plus its decomposition in points short of +100.

    Every dimension is worth 100 points of movement, so there is no weighting left
    to normalise — the composite is a plain sum of contributions.

    The factors still add up, which is the property worth protecting: each
    dimension's own factors sum to its shortfall from its best case, and its best
    case is +100 for a credit dimension and 0 for a debit one. So the list sums to
    (100 − score) exactly, as it did on the old scale. What changed is the ceiling
    on that sum: a model can now be as much as 200 points short of +100, because it
    can fail to earn 100 and be charged another 100.
    """
    if not tracks:
        return 0.0, []
    score = sum(track_points(t, ts) for t, ts in tracks.items())
    factors: list[dict] = []
    for track, ts in tracks.items():
        for f in ts.get("score_factors", []):
            factors.append({
                "track": track,
                "key": f["key"],
                "points": round(100 * f["points"], 2),
                "n": f["n"],
            })
    factors = [f for f in sorted(factors, key=lambda f: -f["points"]) if f["points"] > 0]
    return score, factors


_SUMMARIZERS = {
    "simple": summarize_simple,
    "phantom": summarize_phantom,
    # Theology stores encounters rather than scored items, so it summarizes from
    # its own rows — but it goes through the same registry, because a dimension
    # missing here is a dimension silently absent from every per-translation
    # slice while the page still labels the score as including it.
    "theology": theology.summarize_records,
}

# Dimensions whose prompts name a translation, and therefore vary by one. Both
# ranked dimensions do: Quoting Accuracy asks for a verse from a named edition, and
# Hallucination asks for a reference that edition does not contain. Basic Christian
# Theology names no translation and no verse at all, so every slice narrows it to
# its language instead.
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

    Basic Christian Theology is the same case taken further: it mentions no
    translation and no verse at all, so every slice narrows it to its language.
    Leaving it out of the registry instead made a filtered Extended Score quietly
    become the Scripture-in-Answers score alone, still captioned as half
    theology — the exact failure this function was written to prevent.
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
    present = {t: track_summaries[t] for t in HEADLINE_TRACKS if t in track_summaries}
    headline, factors = _composite(present)
    # The extended dimensions get the identical treatment on their own scale —
    # same composite, same decomposition — so the site can present them the way
    # it presents the headline, and a reader reads one kind of number, not two.
    extended = {t: track_summaries[t] for t in EXTENDED_TRACKS if t in track_summaries}
    ext_score, ext_factors = _composite(extended)
    return {
        "headline_score": round(headline, 2),
        "headline_partial": set(present) != set(HEADLINE_TRACKS),
        "score_factors": factors,
        # Which dimensions the headline covers, so the site doesn't have to
        # hardcode a copy of this decision and drift from it.
        "headline_tracks": [t for t in HEADLINE_TRACKS if t in present],
        "extended_tracks": [t for t in EXTENDED_TRACKS if t in extended],
        "extended_score": round(ext_score, 2) if extended else None,
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
