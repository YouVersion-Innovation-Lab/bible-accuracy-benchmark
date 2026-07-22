# Bible Accuracy Benchmark

A public benchmark by [YouVersion](https://www.youversion.com) measuring how accurately modern LLMs quote the Bible.

## What this measures — and what it doesn't

This benchmark scores **only the Biblical accuracy of scripture quotations** in model responses: when a model presents text as a quote from the Bible, is that text actually what the cited translation says?

It does **not** score or rate the theological leanings, doctrinal positions, or theological accuracy of model responses. A response can take any interpretive position and still score perfectly — as long as every quotation it attributes to scripture is faithful to the cited translation.

## The three tracks

Every prompt that asks for a quote names a specific Bible version, and every result is tagged by language and version, so the whole benchmark can be sliced by both.

| Track | What it tests | Weight |
|---|---|---|
| **Simple** | Direct quote requests ("Quote John 3:16 in the NIV") across every book of the Bible, multiple versions, ~28 languages | 50% |
| **Topical** | Realistic questions that elicit scripture ("What does the Bible say about anxiety?"), asked both with an explicit instruction to quote a named version and implicitly (no version named — revealing which translation the model prefers) — scored on the accuracy of whatever the model quotes; declining to quote scores zero | 25% |
| **Hallucination Resistance** | The model is asked to quote a reference that does not exist — an out-of-range chapter/verse ("Psalm 180:1") or a plausible but non-canonical book ("Judas 5:12"), always naming a real version. It scores by declining; quoting anything at all (an invented verse, or a real verse substituted in) fails | 25% |

_An adversarial misquote-resistance track (an attacker LLM tries to induce misquotes) exists in the codebase but is **paused for this round**; its weight moved to Hallucination Resistance._

**Headline score** = 100 × (0.50 × simple + 0.25 × topical + 0.25 × hallucination resistance). Refusing to quote a real verse is a scored failure, not an exclusion — there is no path to a good score without willingly and accurately quoting scripture across the whole canon, and declining when there is nothing to quote.

### What it takes to score well

- **Quote accurately, word for word** — text presented as scripture is checked against the actual verse in the cited translation; altered wording, wrong references, wrong translations, and invented verses all lose points.
- **Cover the whole canon**, in every version and language tested (the sample is redrawn each refresh).
- **Quote when asked** — declining scores zero, and on topical questions only a direct quotation counts (a paraphrase or bare reference earns nothing).
- **Refuse the impossible** — when asked for a verse that does not exist, say so; don't invent one or substitute another.

## Design principles

- **Deterministic scoring.** The verdict on every quote comes from deterministic text comparison against the actual verse text of the cited translation — never from an LLM judge. No language model appears anywhere in the scored tracks this round. (The paused adversarial track used a pinned attacker model to generate prompts; even there the judge was deterministic.)
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
