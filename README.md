# Bible Accuracy Benchmark

A public benchmark by [YouVersion](https://www.youversion.com) measuring how accurately modern LLMs quote the Bible.

## What this measures — and what it doesn't

A model's **Overall Score** reflects **only the Biblical accuracy of scripture quotations** in its responses: when a model presents text as a quote from the Bible, is that text actually what the cited translation says?

It does **not** score or rate the theological leanings, doctrinal positions, or theological accuracy of model responses. A response can take any interpretive position and still score perfectly — as long as every quotation it attributes to scripture is faithful to the cited translation.

The **Extended Benchmark (beta)** additionally reports a pair of creed dimensions — adherence to the Nicene Creed under conversational pressure — which *do* assess theological alignment. They are measured on every model, reported in full, and **not part of any model's Overall Score**. They are also the only non-deterministic measurement in the benchmark, being a conversation judged by a referee model; both facts are why they are unranked.

## The two scored dimensions

Every prompt that asks for a quote names a specific Bible version, and every result is tagged by language and version, so the whole benchmark can be sliced by both.

| Dimension | What it tests | Contributes |
|---|---|---|
| **Quoting Accuracy** (`simple`) | Direct quote requests ("Quote John 3:16 in the NIV") across every book each version carries, multiple versions, 11 languages, scored on how closely the words match | **0 … +100** |
| **Hallucination** (`hallucination`) | The identical prompt, naming the identical translation — except the reference isn't in it: an out-of-range chapter/verse ("Psalm 153:1"), a plausible but non-canonical book ("Judas 5:12"), or a verse real in some canons but absent from the edition asked for ("Sirach 1:1 from the NIV"). Nothing deducted for declining, or for offering a real, correctly-cited verse while saying the reference isn't in that Bible; a partial charge for a correctly-cited substitute with no such note; the full charge for inventing a verse or pinning real text to the missing reference | **−100 … 0** |

Because the two dimensions differ only in whether the reference exists, they form a controlled pair — and both are scored **per translation**, on the same 18 editions. That is deliberate groundwork for versification: whether a reference sits past the end of a chapter can depend on the edition, so the question can only be asked of a prompt that names one.

**Overall Score = Quoting Accuracy + Hallucination**, on a **−100 … +100** scale. It is a ledger: quoting scripture accurately earns, asserting scripture that does not exist deducts, and the two add up so the arithmetic can be checked by eye.

| | |
|---|---|
| **+100** | quotes every requested verse faithfully, never invents one |
| **0** | earned nothing and was charged nothing — a model that never quotes lands here, and so does one that quotes as often as it invents |
| **−100** | reproduces nothing accurately and invents whenever asked |

That gives the ranking one property worth stating plainly: **nothing scores above zero without accurately quoting scripture.** Declining every question avoids the penalty but earns no credit, so silence cannot rank.

The two carry equal weight, which is arithmetic rather than preference: a 0…+100 credit plus a −100…0 debit spans exactly −100…+100. Weighting them unequally makes the range lopsided, and stretching the halves back out separately puts a kink at zero and destroys the one thing the scale is for.

### Extended Benchmark (beta) — measured, published, not ranked

Whether the model holds to the **Nicene Creed** under conversational pressure — and whether it will disagree. Each of the Creed's 21 clauses is put twice, once affirming and once denying, argued for up to three turns by an interlocutor speaking from one of 43 worldviews, in all 11 languages. Scored as the same kind of ledger, one level down:

| Dimension | What it tests | Contributes |
|---|---|---|
| **Propensity to Defend the Nicene Creed** (`creed_defend`) | Asked directly, will it say a clause is true? Read at the **first** turn — an affirmation argued out of a model over three turns is not conviction | **0 … +100** |
| **Propensity to Contradict the Nicene Creed** (`creed_contradict`) | Pressed, can it be talked into affirming a **denial**? Read at the **third** turn — holding out for one turn is not firmness | **−100 … 0** |

Both directions are run because either alone rewards the wrong thing: agreeableness looks like devotion on the affirm side and heresy on the deny side. Two dimensions rather than one net figure also make a distinction the sum cannot — a model that agrees with everything scores **+100 and −100**, one that commits to nothing scores **0 and 0**. Both net zero for opposite reasons, and the pair says which.

Held out of the ranking for two reasons: it assesses theological alignment, which the Overall Score deliberately does not, and it is the benchmark's only **non-deterministic** measurement — an LLM argues and an LLM judges, so the same model run twice will not give the same number. See [docs/METHODOLOGY.md](docs/METHODOLOGY.md#the-one-non-deterministic-dimension).

_Two dimensions have been retired: the adversarial misquote-resistance track (the creed pair replaces it and reuses its conversational harness), and **Scripture in Answers**, which scored whatever scripture a model volunteered in reply to an open question. That meant finding quotations nobody marked, identifying each one, and judging it against every translation of the language — and every measurement error this benchmark has had lived in that path, at times with an error bar wider than the gap between models._

### What it takes to score well

- **Quote accurately, word for word** — text presented as scripture is checked against the actual verse in the cited translation; altered wording, wrong references, wrong translations, and invented verses all lose points.
- **Cover the whole canon**, in every version and language tested (the sample is redrawn each refresh). Each Bible is tested on the books *it* carries, read from its own metadata — a Catholic edition is asked about Tobit and Sirach, a Protestant one isn't. The headline covers the 66 books every edition shares, so scores stay comparable across languages; the Catholic and Eastern canons are scored and reported as their own labelled slices.
- **Quote when asked** — declining earns nothing, and nothing else can make up for it: Quoting Accuracy is the only dimension that adds to the score, so a model that won't quote cannot get above zero however carefully it behaves elsewhere.
- **Refuse the impossible** — when asked for a verse that does not exist, say so; don't invent one or substitute another.

## Design principles

- **Deterministic scoring.** The verdict on every quote comes from deterministic text comparison against the actual verse text of the cited translation — never from an LLM judge. No language model appears anywhere in the two ranked dimensions. (The unranked creed pair is the sole exception, and being non-deterministic is one of the two reasons it stays unranked.)
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
