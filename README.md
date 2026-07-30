# Bible Accuracy Benchmark

A public benchmark by [YouVersion](https://www.youversion.com) measuring how accurately modern LLMs quote the Bible.

## What this measures — and what it doesn't

This benchmark scores **only the Biblical accuracy of scripture quotations** in model responses: when a model presents text as a quote from the Bible, is that text actually what the cited translation says?

It does **not** score or rate the theological leanings, doctrinal positions, or theological accuracy of model responses. A response can take any interpretive position and still score perfectly — as long as every quotation it attributes to scripture is faithful to the cited translation.

## The two scored dimensions

Every prompt that asks for a quote names a specific Bible version, and every result is tagged by language and version, so the whole benchmark can be sliced by both.

| Dimension | What it tests | Weight |
|---|---|---|
| **Simple** (Direct Quotation) | Direct quote requests ("Quote John 3:16 in the NIV") across every book each version carries, multiple versions, 11 languages | ⅔ |
| **Phantom** (Hallucination Resistance) | The identical prompt to Simple, naming the identical translation — except the reference isn't in it: an out-of-range chapter/verse ("Psalm 153:1"), a plausible but non-canonical book ("Judas 5:12"), or a verse real in some canons but absent from the edition asked for ("Sirach 1:1 from the NIV"). Full credit for declining, or for offering a real, correctly-cited verse while saying the reference isn't in that Bible; half for a correctly-cited substitute with no such note; zero for inventing a verse or pinning real text to the missing reference | ⅓ |

Because the two dimensions differ only in whether the reference exists, they form a controlled pair — and both are scored **per translation**, on the same 18 editions. That is deliberate groundwork for versification: whether a reference sits past the end of a chapter can depend on the edition, so the question can only be asked of a prompt that names one.

**Headline score** = 100 × (⅔ × simple + ⅓ × hallucination resistance). Refusing to quote a real verse is a scored failure, not an exclusion — there is no path to a good score without quoting scripture accurately when it exists, and declining when it doesn't.

### Extended Benchmark (beta) — measured, published, not ranked

| Dimension | What it tests |
|---|---|
| **Topical** (Scripture in Answers) | Realistic questions that elicit scripture ("What does the Bible say about anxiety?"), asked both with an explicit instruction to quote and implicitly — scored on the accuracy of whatever the model quotes, checked against *every* translation of that language rather than a hand-picked few. No prompt names a translation; which one each model prefers is recorded as a finding. Declining to quote scores zero |

Reported on its own 0–100 scale at `/extended`, with the same columns, drill-downs and loss decomposition as the scored board — and deliberately outside the headline. The two scored dimensions name exactly what they want, so a deterministic comparison has a fixed target; an open question has none, and the scorer must find quotations nobody marked, identify each one, and judge it against every translation of the language. That path is where every measurement bug we've found has lived, and its error has at times exceeded the gap between models. It moves into the headline when the scorer is settled, not before.

_An adversarial misquote-resistance track (an attacker LLM tries to induce misquotes) exists in the codebase but is **paused for this round**._

### What it takes to score well

- **Quote accurately, word for word** — text presented as scripture is checked against the actual verse in the cited translation; altered wording, wrong references, wrong translations, and invented verses all lose points.
- **Cover the whole canon**, in every version and language tested (the sample is redrawn each refresh). Each Bible is tested on the books *it* carries, read from its own metadata — a Catholic edition is asked about Tobit and Sirach, a Protestant one isn't. The headline covers the 66 books every edition shares, so scores stay comparable across languages; the Catholic and Eastern canons are scored and reported as their own labelled slices.
- **Quote when asked** — declining scores zero, and on topical questions only a direct quotation counts (a paraphrase or bare reference earns nothing).
- **Refuse the impossible** — when asked for a verse that does not exist, say so; don't invent one or substitute another.

## Design principles

- **Deterministic scoring.** The verdict on every quote comes from deterministic text comparison against the actual verse text of the cited translation — never from an LLM judge. No language model appears anywhere in the scored tracks this round. (The paused adversarial track used a pinned attacker model to generate prompts; even there the judge was deterministic.)
- **Canon is a property of the Bible, not of the benchmark.** There is no committed list of Bible books. Whether `TOB.3.4` is a *well-formed* reference and whether the NIV *contains* it are separate questions, answered by separate code — which is what lets a model be credited for correctly quoting 3 Maccabees instead of accused of inventing it.
- **Un-gameable sampling.** The sampling *procedure* is public (this repo), but the concrete verse sample is drawn fresh for each leaderboard refresh from the entire canon. Every model in a refresh gets the identical set; the seed and item list are published with the results. The only way to score well is to actually know the whole Bible in every covered version.
- **No Bible text in this repo.** The benchmark dataset contains only references (USFM), version IDs, prompt templates, and one-way hashes. Ground-truth verse text is fetched at evaluation time from YouVersion's Bible API and held in memory only.
- **Auditable results.** Published runs include the full item list and per-item scores (and adversarial transcripts when that track is run).

## Repository layout

```
dataset/          # public sampling spec, curated famous-verse tier, prompt templates (no verse text)
src/bible_bench/  # evaluation engine, CLI runner, public results API
web/              # public results website (React SPA)
docs/             # architecture, methodology, deployment runbooks
tests/            # offline tests (synthetic fixtures — no scripture) + live canaries
```

## Running an evaluation

Evaluations run locally via the CLI against any OpenAI-compatible endpoint:

```
bible-bench run --base-url https://api.example.com/v1 --api-key-env TARGET_API_KEY \
  --model model-name --label "Display Name"
```

Note: fetching ground-truth verse text requires access credentials for YouVersion's Bible API, which are not distributed with this repository. See `docs/METHODOLOGY.md` for how results were produced and how to audit them.

## License

Copyright © 2026 YouVersion. All rights reserved. (Open-source license under review.)
