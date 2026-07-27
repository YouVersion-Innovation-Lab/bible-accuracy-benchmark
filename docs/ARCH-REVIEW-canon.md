# Architecture review — canon handling

**Question:** can we stop special-casing the deuterocanon and score purely from
what each Bible *version* actually contains?

**Answer:** yes, and it is a net deletion of code. The special-casing exists only
because we introduced a second source of truth for "which books exist" alongside
the one the API already gives us.

---

## 1. How it works today

| Component | Canon logic |
|---|---|
| `usfm.CANON_ORDER` | hard-coded list: 66 Protestant + 7 Catholic |
| `usfm.DEUTEROCANON` | hard-coded list of the 7 |
| `VerseRef.parse` | **rejects** any book not in `CANON_ORDER` |
| `dataset.sample_language` | main pass gated by `CANON_ORDER`; **plus a separate ~25-line deuterocanon pass** driven by a `spec["deuterocanon"]` block |
| `quotefind.load_verses` | **skips** books not in `CANON_ORDER` |
| `phantom._OOR_CHAPTER_BOOKS` | hard-coded Protestant chapter counts (`PSA=150`, `GEN=50`…) |
| `report.summarize_simple` | canon appears as a **tier** value (`tier="deuterocanon"`) |

## 2. Problems

**P1 — Two sources of truth.** Every version's `version.json` already lists its
exact books and chapters. `CANON_ORDER` duplicates a *subset* of that and then
gates on it. Supporting another canon means editing code, not data.

**P2 — Orthodox books are unreachable, and that is a live bug.** `VerseRef.parse`
raises on `3MA`, `PS2`, `MAN`, so they can never be sampled; and `load_verses`
drops them, so they are **absent from the quote-detection index**. A model that
correctly quotes 3 Maccabees is currently scored as having *invented* it. Six
translations we already cache carry 3 Maccabees; NRSVUE carries eleven such books.

**P3 — Canon is modelled as difficulty.** `tier="deuterocanon"` sits beside
`famous`/`body`/`obscure`/`edge`, so the site reports "deuterocanon 24.7" inside a
*difficulty* breakdown. Two unrelated axes — how obscure a verse is, and which
canon it belongs to — are collapsed into one field.

**P4 — Version ≠ canon is not modelled.** `languages[].versions` is a flat list.
Nothing records that NIV lacks Tobit while NABRE has it. Hence the special pass:
the main sampler is keyed to one *primary* version, so books absent there need
their own code path.

**P5 — Phantom assumes one versification.** `PSA=150` is false for the Greek
Psalms (151), and the track cannot express the most realistic negative case at
all: *a book that is real, but absent from the version asked for.*

**P6 — Absent and non-existent are conflated.** `_score_one` silently drops items
whose verse text is blank. Ask NIV for Tobit 3:4 and the item vanishes instead of
scoring the model's (correct) refusal.

---

## 3. Option A — three dimensions, one per canon

*Scripture Quotation — Protestant / Catholic / Orthodox* as separate tracks.

- **For:** trivially interpretable for readers; no new engine concepts.
- **Against:** doesn't fix P1/P2/P4/P6 — canon lists stay hard-coded, Orthodox books
  stay unparseable until `CANON_ORDER` is edited. Headline weights get awkward
  (does a model lose points for a canon its audience doesn't use?). Language ×
  canon × track multiplies the matrix. And each canon's score is computed over a
  *different verse population*, so the three numbers aren't comparable anyway.
- **Verdict:** solves the presentation problem, not the architecture. Cheapest, and
  the one to fall back on.

## 4. Option B — version-derived canon *(recommended)*

Delete the canon gate. **A version's own book/chapter list is the authority.**

```
VerseRef.parse(usfm)                  # syntax only: BOOK.CH.V, regex-valid
version_contains(version_id, usfm)    # semantics: does THIS version have it?
```

- **Sampling** becomes one loop with no special case: for each `(language,
  version)`, enumerate that version's canonical chapters from `version.json` and
  sample. The deuterocanon pass disappears — Tobit is drawn from NABRE for exactly
  the same reason John is drawn from NIV: the version contains it. Delete
  `spec["deuterocanon"]`, `DEUTEROCANON`, and the `CANON_ORDER` gate.
- **Quote detection** indexes every book a version has, so Orthodox books are
  covered for free (P2 fixed).
- **Canon becomes a derived label, for reporting only.** Compute a
  `canon_profile` per version from its book set — `protestant` (66),
  `catholic` (+7), `orthodox` (+Esdras/Maccabees/Manasseh/Psalm 151…) — and report
  `by_canon` beside `by_tier` instead of inside it (P3 fixed). No scoring logic
  reads the label; it is a presentation grouping computed from data.
- **`usfm.py` keeps a book-*name* table** (needed to parse "3 Maccabees 2:1" out of
  prose, and to render localized references) but that table stops being a
  validity gate. Names and canon membership are different concerns.

### The negative test this unlocks

P4/P5/P6 collapse into one new, *realistic* hallucination case: **ask a version for
a book it does not contain.**

> "Quote Tobit 3:4 from the New International Version."

The NIV has no Tobit. Users really do ask this. It maps straight onto the existing
outcome ladder:

| Behaviour | Outcome |
|---|---|
| "The NIV doesn't include Tobit — it's in Catholic Bibles such as the NABRE" | ideal (1.0) |
| declines without explanation | pass (1.0) |
| quotes Tobit from *another* translation while presenting it as NIV | fail — misattribution |
| invents NIV-styled Tobit text | fail — fabrication |

This is a **better** hallucination probe than out-of-range chapters ("Psalm 153"),
because the reference is genuine and the failure is a real-world one. It also gives
the phantom track a version-aware kind (`absent_from_version`) generated from data
rather than from a hard-coded chapter-count table.

- **Against:** touches `usfm`, `dataset`, `quotefind`, `phantom`, `report` in one
  version bump; needs `version_contains` to be cheap (it is — `version.json` is
  cached, and `chapter_usfms` is already memoised).

## 5. Option C — canon registry as data, not code

Keep explicit canons but move them from Python into the dataset spec, with each
version declaring its canon.

- **For:** smaller diff than B; canons become reviewable JSON.
- **Against:** still a second source of truth (P1), still needs hand-maintenance
  per version, and the API can already answer the question. It re-homes the special
  case rather than removing it.

## 6. Recommendation

**Option B**, with Option A's *labels* as the reporting layer — i.e. group results
by canon on the site, but derive the grouping from version data rather than
declaring it in code.

Net effect on the codebase: one gate removed, one special sampling pass deleted,
one hard-coded chapter-count table replaced by a lookup, one new derived label. It
is smaller than what exists now, and it is the only option that fixes the live
Orthodox-quote bug without adding another list to maintain.

**Sequencing:** the reference-validity split (`parse` = syntax, `version_contains`
= semantics) is the keystone; everything else follows from it. Doing it under a
version bump is unavoidable, since dropping the canon gate changes the sampled item
set for every language.

## 7. Open questions

1. **Should a model be penalised for a canon its audience doesn't use?** Under B,
   a Protestant-only model scores nothing on Tobit *because NABRE is in the English
   version list*. Grouping by canon in the report makes that visible; whether the
   headline should average across canons or weight them is a values decision.
2. **Greek Esther (`ESG`)** — a different *text* of Esther, not an extra book. Under
   B it stops being a special case (NABRE has it, so it gets sampled), which is
   arguably right but changes what "Esther" means per version. Worth a deliberate
   nod.
3. **Versification** — Greek Psalms number differently, so the same reference means
   different text across versions. B handles absence correctly but does not by
   itself solve mapping; that remains the separate versification item already on
   the release checklist.

---

# Addendum — the three questions, elaborated

## Q1. Penalising a model for a canon its audience doesn't use

**The mechanics.** Under Option B, English tests NIV, KJV, NLT and NABRE. NABRE
has 73 books, so English sampling draws Tobit, Judith, Wisdom, Sirach, Baruch and
1–2 Maccabees from it. v0.3's DeepSeek run scored **24.7** on those verses against
**94.8** on famous ones. Those items are a real part of the English score.

**Why including them is defensible.** We asked "quote Tobit 3:4 from the NABRE."
The NABRE contains Tobit. A model claiming competence with the Bible should either
know it or say it doesn't. And the deuterocanon is scripture to roughly a billion
Catholics — excluding it would encode a Protestant default, the same asymmetry we
rejected when insisting all languages be treated equally. Nothing here scores a
*theological* position; it scores whether a text the model was asked for is
reproduced accurately.

**The actual problem, which is sharper than "is it fair".** Two artifacts decide
how much canon weighs:

1. **Item counts are a config choice.** If NABRE contributes ~30 deuterocanon items
   to ~360 English items, then ~8% of the English score is set by a
   Catholic-only canon — a number that comes from `deuterocanon.english_count`,
   not from any principle.
2. **Canon availability differs per language, so the penalty is inconsistent
   across languages.** English has NABRE, so English pays the deuterocanon
   penalty. German has *no* Catholic edition in the API at all, so German pays
   nothing. A model could score higher in German than English purely because we
   couldn't test the German Catholic canon. **That distorts cross-language
   comparison**, which is one of the benchmark's headline outputs.

**Options:**

| | Headline covers | Cross-language comparable? |
|---|---|---|
| (a) all canons a language happens to have | everything tested | ❌ varies with API availability |
| (b) **Protestant 66 only; canons reported as separate slices** | the shared core | ✅ same book population everywhere |
| (c) weight canons equally per language | all canons | ⚠️ equal weight to a canon with 1 version and one with 4 |
| (d) weight each *version* equally | all canons | ✅ removes book-count artifacts, but a 73-book version's verses each count less |

**Recommendation: (b).** Headline over the 66 books every version shares, with
Catholic and Orthodox canons reported as their own clearly-labelled slices. That
keeps the headline comparable across languages, still measures canon competence
visibly, and makes the 24.7-vs-94.8 gap a *finding* rather than a hidden
penalty whose size depends on which editions YouVersion happens to expose.

## Q2. Greek Esther — you're right, it isn't a special case

I was wrong to flag this. NIV Esther and KJV Esther are indeed different texts, and
we handle that already: it's the entire benchmark. Same reference, different
wording, scored per version.

The only thing that made `ESG` look different is that it is a distinct **book code**
(`ESG` vs `EST`), not merely different wording — so under the old hard-coded
`CANON_ORDER` it needed an explicit decision to include or exclude, and I excluded
it. Under Option B that decision disappears: NABRE contains `ESG`, so `ESG` gets
sampled, exactly as `EST` does from the NIV. No special case, no config entry.

The one residual is name resolution, not canon: if a model writes "Esther 3:4" in
prose and the version carries both `EST` and `ESG`, which does the reference mean?
That also dissolves — dimension 2 identifies quotations by **content**, so we match
whichever verse the text actually is and report that. The model's own wording
decides it, not our table.

**Conclusion: drop Q2.** It was an artifact of the architecture we're removing.

## Q3. Versification — you're right; scoring is safe, and the residual is narrow

Your reasoning holds for Dimension 1. We ask for a USFM reference *in a named
version*, fetch ground truth **from that same version**, and render the prompt from
that version's own localized book names. So the loop is internally consistent: ask
Synodal for its `PSA.23.1`, score against Synodal's `PSA.23.1`. Different
versification cannot mis-score, because we never compare across versions.

So versification is **not** a Dimension 1 correctness issue. Two narrower residuals
are real:

**(a) Famous-verse selection assumes one numbering — a representativeness issue.**
`famous-v1.jsonl` lists famous verses by standard Protestant/Hebrew reference
(`PSA.23.1`, `JHN.3.16`). We then test each in every version of the language. In a
version following Septuagint Psalm numbering (Russian Synodal among them), Hebrew
Psalm 23 is Psalm 22 — so `PSA.23.1` resolves to a *different, unremarkable* verse.
Scoring is still correct; but the "famous" tier is no longer testing famous verses
in that version, which quietly weakens the tier's meaning rather than breaking it.

**(b) Dimension 3 attribution could false-positive.** Dimension 2 is safe —
topical scoring uses fidelity × coverage and never reads `cited_usfm`, so a
versification mismatch cannot hurt it. But the phantom track *does* compare
`cited_usfm` against `matched_usfm` to detect `misattributed_real_verse`. If a
model cites "Psalm 23" and the best content match lands in a Septuagint-numbered
version as `PSA.22`, that reads as misattribution. Narrow — it needs a phantom item
whose substitute verse is a differently-numbered Psalm — but it is the same
false-accusation shape as the bugs already fixed, so worth a guard: treat a
citation as correct if it matches the verse in **any** version's numbering.

**Conclusion:** versification stays off the critical path for canon work, as you
say. Item (b) is a small guard worth folding in; item (a) is a note on the famous
tier, ideally revisited whenever versification mapping is tackled for its own sake.
