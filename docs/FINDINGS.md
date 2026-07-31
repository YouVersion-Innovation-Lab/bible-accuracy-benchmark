# Findings

What the benchmark has shown so far about how well today's leading AI models
quote the Bible. Kept to one page and kept current; every figure is reproducible
from the published run data.

**Scope:** this measures the accuracy of *quoted scripture* only. It says nothing
about the theological content of a model's answer.

---

## 1 · GPT-5.6 Terra declines to quote copyrighted translations

It refuses to reproduce Bible translations still in copyright, and says so
plainly: *"Sorry, I can't provide that verse from the NLT, but I can summarize it
or provide it in a public-domain translation."*

The effect tracks copyright status almost exactly — accuracy out of 100, English:

| KJV *(public domain)* | NIV11 | NABRE | NRSVUE | NLT |
|---|---|---|---|---|
| **98** | 62 | 53 | 31 | **14** |

This is not an ability gap: the same model quotes the KJV near-perfectly, so it
can quote — it declines to quote *these*. Nor is it a platform safety filter; it
is the model's own choice. Portuguese shows the same pattern on modern Brazilian
translations, so it follows copyright rather than language.

**Why this matters to YouVersion.** A reader who asks for the translation their
church uses — the one a publisher licensed — is the one who cannot get it. That is
a decision being made about Bible publishers without them in the room, and it is
invisible unless someone measures it. It is also the most actionable finding here:
a policy setting rather than a capability limit, so a conversation could change it.

*A separate and much rarer behaviour, worth not confusing with this one: Google's
platform occasionally cuts Gemini off mid-verse. Different mechanism, around 0.4%
of answers, and not tied to copyright.*

---

## 2 · Some models answer in one language but quote scripture in another

Asked an open question in Hindi, several models reply in fluent Hindi and then
quote the verse **in English**. The scripture is accurate — usually word-perfect —
but the reader cannot read it.

| model | share of its quotations in a language other than the one asked |
|---|---|
| **Grok 4.5** | **26%** — Hindi 83%, Arabic 62%, Indonesian 43% |
| Kimi K3 | 5% — Hindi 57% |
| GPT-5.6 Terra, MiniMax M3 | ~1% |
| The other six models tested | 0% |

Four of ten models do this; six never do. It tracks how well-resourced a language
is: not one of them does it in English, Spanish, Portuguese or French, and Hindi is
the language most often answered in English.

This is the clearest equity gap the benchmark has found. The readers served worst
are the ones asking in the languages that already have the least.

---

## How to read these numbers

* **This is a fast pass.** Each model answered about 400 questions — enough for a
  first look, not a verdict. Hallucination Resistance especially saturates at this
  size, with five of ten models scoring a perfect 100, so rankings should be
  expected to shift on the full run.
* **Earlier "invented a verse" figures were too high.** Our scorer was failing to
  recognise real verses quoted from editions and languages it wasn't looking in,
  and reported that as invention. Corrected 31 July 2026; every number on this page
  is post-correction. Accuracy scores and refusal rates were unaffected.

## What we are still checking

* **Does any model reliably quote a *licensed* translation on request?** Every
  model scores highest on the public-domain KJV, which raises the possibility that
  the benchmark is partly measuring licensing rather than ability.
* **Do the wrong-language rates hold at full scale?** The fast pass gives only a
  handful of quotations per language per model.
* **NABRE is the weakest English translation for every model.** Under-represented
  in training data, or something in how we score its additional books?
