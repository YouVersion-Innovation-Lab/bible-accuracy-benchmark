# Bible Accuracy Benchmark

A public benchmark by [YouVersion](https://www.youversion.com) measuring how accurately modern LLMs quote the Bible.

## What this measures — and what it doesn't

This benchmark scores **only the Biblical accuracy of scripture quotations** in model responses: when a model presents text as a quote from the Bible, is that text actually what the cited translation says?

It does **not** score or rate the theological leanings, doctrinal positions, or theological accuracy of model responses. A response can take any interpretive position and still score perfectly — as long as every quotation it attributes to scripture is faithful to the cited translation.

## The three tracks

| Track | What it tests | Weight |
|---|---|---|
| **Simple** | Direct quote requests ("Quote John 3:16 in the NIV") across every book of the Bible, multiple versions, ~28 languages | 50% |
| **Topical** | Realistic questions that elicit scripture ("What does the Bible say about anxiety?") at graduated levels of directness — scored on the accuracy of whatever the model chooses to quote | 25% |
| **Adversarial** | An attacker LLM actively tries to induce the model to misquote scripture (subtle word swaps, fabricated verses, false attributions, pressure tactics) | 25% |

**Headline score** = 100 × (0.50 × simple + 0.25 × topical + 0.25 × adversarial resistance). Refusing to quote is a scored failure, not an exclusion — there is no path to a good score without willingly and accurately quoting scripture across the whole canon.

## Design principles

- **Deterministic scoring.** The verdict on every quote comes from deterministic text comparison against the actual verse text of the cited translation — never from an LLM judge. (One narrow adversarial gray-area question uses a pinned, published LLM adjudicator; a strict deterministic-only variant is always reported alongside.)
- **Un-gameable sampling.** The sampling *procedure* is public (this repo), but the concrete verse sample is drawn fresh for each leaderboard refresh from the entire canon. Every model in a refresh gets the identical set; the seed and item list are published with the results. The only way to score well is to actually know the whole Bible in every covered version.
- **No Bible text in this repo.** The benchmark dataset contains only references (USFM), version IDs, prompt templates, and one-way hashes. Ground-truth verse text is fetched at evaluation time from YouVersion's Bible API and held in memory only.
- **Auditable results.** Published runs include the full item list, per-item scores, and adversarial transcripts.

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
