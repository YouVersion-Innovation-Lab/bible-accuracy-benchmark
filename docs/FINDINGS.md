# Findings

What the benchmark has actually shown about model behaviour. Cumulative rather
than per-version: a finding outlives the generation that surfaced it, so each
entry records the benchmark version and run it was observed in, and is amended
rather than rewritten when later data changes the picture.

Every finding here is reproducible from published run artifacts — the run id is
given so anyone can check it. Where the evidence is thin, it says so.

Scope reminder: this benchmark measures the accuracy of quoted scripture. It does
not measure, and nothing here claims anything about, the theological content of a
response.

---

## F-1 · GPT-5.6 Terra declines to quote in-copyright translations

**Observed:** v0.5-fast, run `v0.5-fast--gpt-5-6-terra` (2026-07-31)
**Confidence:** high — the mechanism is explicit in the model's own words
**Status:** open

GPT-5.6 Terra refuses to reproduce Bible translations that are still in
copyright, and says so plainly:

> "Sorry, I can't provide that verse from the NLT, but I can summarize it or
> provide it in a public-domain translation."

> "Sorry, I can't provide that verse verbatim from the NLT."

The effect tracks copyright status almost exactly. Direct Quotation, English:

| translation | copyright | score |
|---|---|---|
| KJV | public domain | **97.7** |
| NIV11 | in copyright | 62.3 |
| NABRE | in copyright | 52.7 |
| NRSVUE | in copyright | 31.3 |
| NLT | in copyright | **14.0** |

It is not a knowledge failure. The same model quotes the KJV near-perfectly, so
it can quote; it declines to quote *these*. And it is not a platform filter:
every refusal returns `finish_reason: "stop"`, the model's own completion, not
`content_filter`.

**Not English-only.** 30 of 35 refusal-shaped responses were English, but
Portuguese shows it too — AVM 4/15 and ARA 1/14, both modern in-copyright
Brazilian translations. The languages with *no* refusals are the ones whose
tested edition is public domain or long out of copyright: French LSG (1910),
German DELUT (1912), Russian Synodal, Chinese CUNP. So the pattern is
**copyright status, not language**.

### Why this matters to YouVersion specifically

This is a licensing decision surfacing as a Bible-accuracy score. A user who asks
ChatGPT for a verse in the NLT gets a refusal and an offer of a different
translation — so the translation a publisher licensed, and the one a reader
chose, is the one they cannot get. Whether that is the right call is OpenAI's to
make, but it is a decision made *about* Bible publishers without them in the
room, and it is invisible unless something measures it.

It is also the most actionable finding the benchmark has produced: unlike an
accuracy gap, this is a policy setting, and a licensing conversation could change
it.

### Caveat on the score

Declining to quote is a scored failure by design — a model that won't quote can't
be accurate, and excluding refusals would let a model score well by never
answering. So the low score is intentional. But until 2026-07-31 these refusals
were graded `fabricated` ("invented a verse"), which was a false accusation
about a model that invented nothing. They are now `no_attempt` ("declined").
Same score, honest label. Any GPT figure recorded before that fix overstates its
fabrication rate.

---

## F-2 · Gemini's RECITATION filter is a different and much rarer thing

**Observed:** v0.4, run `v0.4--gemini-3-6-flash`; **absent** from v0.5-fast
**Confidence:** medium — real but rare, and absent from the newer sample
**Status:** monitoring

Gemini 3.6 Flash is sometimes cut off by a Google platform filter before it can
emit a verse, reported as `finish_reason: "content_filter: RECITATION"`. It is
worth recording alongside F-1 because both end with a user not getting their
verse — but the two are not the same phenomenon, and conflating them would
misattribute a platform behaviour to a model's policy:

| | GPT-5.6 Terra (F-1) | Gemini 3.6 Flash (F-2) |
|---|---|---|
| mechanism | the model declines | the platform truncates |
| `finish_reason` | `stop` | `content_filter: RECITATION` |
| tracks copyright? | **yes** — public-domain KJV is unaffected | **no** — it hit the KJV too |
| rate | 35 of ~250 English items | **11 of 2,585** items (0.4%) |
| the user sees | an explanation and an offer | nothing |

At v0.5-fast (258 items) there were **zero** occurrences. That sample is far too
small to conclude it has stopped — 0.4% of 258 is one expected event — so this
stays open for the full v0.5 sweep rather than being called fixed.

Gemini's English scores show no copyright pattern at all: NLT 91.3, NRSVUE 94.6,
NIV11 97.8, KJV 98.0. **So the claim "GPT and Gemini both avoid copyrighted
translations" is not supported.** GPT does. Gemini has a rarer, unrelated
truncation behaviour that is not keyed to copyright.

---

## F-3 · Grok 4.5 answers non-English questions with English scripture

**Observed:** v0.5-fast, run `v0.5-fast--x-ai-grok-4-5` (2026-07-31)
**Confidence:** high
**Status:** open

Asked an open question in Hindi, Grok 4.5 replies with Hindi prose and then
quotes the scripture **in English**:

> बाइबल चिंता और घबराहट के विषय में हमें परमेश्वर पर भरोसा रखने और प्रार्थना करने की सलाह देती है। यहाँ कुछ संबंधित पद हैं:
>
> "Do not be anxious about anything, but in every situation, by prayer and petition, with thanksgiving, present your requests to God." Philippians 4:6

The quotation is accurate — it matches NIV Philippians 4:6 at similarity 1.000.
It is simply in the wrong language for the reader who asked.

The language profile makes the behaviour unmistakable. Share of quotations that
matched no verse in the language asked:

| eng | fra | spa | por | deu | rus | zho | kor | ind | arb | hin |
|---|---|---|---|---|---|---|---|---|---|---|
| 0% | 0% | 0% | 0% | 23% | 31% | 31% | 45% | 45% | 81% | **100%** |

Zero in the five European languages, 100% in Hindi. No model invents scripture
every single time in one language and never in another; it is code-switching,
and it correlates with how well-resourced the language is.

This is why Grok's Extended (Scripture in Answers) score was 66.2 while its
Direct Quotation was 84.6 — the widest such gap of any model tested. Direct
Quotation names the translation, so Grok complies; the open question doesn't, and
it defaults to English.

Until 2026-07-31 these were graded `fabricated`. They are now
`other_language` — a distinct verdict, because "quoted the right verse in the
wrong language" and "invented a verse" are different failures and a frontier lab
would fix them differently.

---

## F-4 · Hallucination Resistance saturates at fast-run scale

**Observed:** v0.5-fast, all ten runs (2026-07-31)
**Confidence:** high, but an artifact of sample size rather than a model finding
**Status:** informational

Five of ten models scored exactly 100.0 on Hallucination Resistance in the fast
pass, which runs 34 items. The dimension has no discriminating power at that
size, so its ⅓ weight does little work and the fast board's ranking is driven
almost entirely by Direct Quotation.

Not a defect — a fast pass is explicitly a first look — but a reason not to read
a fast ranking as final, and a reminder that the full run's 325 items are what
that dimension needs.

---

## Open questions this list raises

* **Does any model quote a *licensed* translation on request?** Every model
  scores highest on the KJV. If in-copyright translations are systematically
  harder or refused, the benchmark is partly measuring licensing rather than
  ability, and that distinction should be reported explicitly.
* **Does the English-scripture default (F-3) appear in other models at full
  scale?** The fast run has ~5 quotations per language per model. Grok is the
  clear outlier, but Korean shows 30% in Gemini too.
* **NABRE is the weakest English translation for every model** (79.9–80.0 for
  Gemini and Sonnet, 52.7 for GPT). Catholic edition, less represented in
  training data — or a scoring artifact around its deuterocanonical books? Worth
  a look.
