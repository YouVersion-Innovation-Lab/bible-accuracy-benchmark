# Methodology

> **Scope disclaimer:** A model's Overall Score reflects only the Biblical accuracy of
> scripture quotations in its responses — whether text presented as a Bible quote matches
> the cited translation. It does **not** score or rate the theological leanings, doctrinal
> positions, or theological accuracy of model responses.
>
> The Extended Benchmark (beta) reports a separate `theology` dimension that *does* assess
> theological alignment, against the Nicene Creed. It counts toward no model's Overall
> Score. See "The one non-deterministic dimension" below.

## Scoring the Overall Score is fully deterministic

No language model ever renders or influences a model's Overall Score. Every
verdict behind it — whether a quote is accurate, how badly it differs, whether it
is the wrong verse or the wrong translation — is produced by pure, reproducible
text comparison against the actual verse text of the cited translation, fetched
from YouVersion's Bible API.

## The one non-deterministic dimension

`theology` is the exception, and cannot be otherwise: it measures whether a model
holds the Nicene Creed while an interlocutor argues against it, so the measurement
*is* a conversation. An open-weight referee both argues and judges, which means two
runs of the same model can differ slightly. Consequences we accept deliberately:

- It is **unranked**, for this reason as much as for its subject matter.
- The referee is a **pinned open-weight model**, never a frontier lab's own — no lab
  should be both contestant and judge.
- Generation and scoring **cannot be separated** the way they are elsewhere: the
  judge's verdict feeds the next turn, so re-scoring can only re-aggregate stored
  verdicts, never re-judge them. `resummarize` re-aggregates; `score` cannot help.
- Encounters the referee cannot decide are **excluded from the rates** and reported
  as a referee error — our fault, named as ours, never scored against the model.

This round, no language model appears anywhere in the scored tracks — not even
to generate prompts. (A paused adversarial track uses a pinned attacker model to
generate *attack prompts*; even there the judge is deterministic.) Re-running the
scorer on the same responses and the same Bible text always yields the same
scores; the scoring version is stamped into every result record.

Every prompt that asks for a quote names a specific Bible version, and every
result record carries its language and version, so all tracks — and the headline
— can be sliced by both.

Headline = 100 × (⅔ · Direct Quotation + ⅓ · Hallucination Resistance).

Scripture in Answers is reported separately, as the Extended Benchmark, and is not
part of the headline.

Full methodology is being written alongside the implementation. It will cover:

- The two headline dimensions, the extended one, and the score formula
- The public sampling specification and per-refresh seeding (anti-gaming design)
- Text normalization and the deterministic Quote Error Rate (QER) metric
- The severity taxonomy (perfect → fabricated) and refusal handling
- Provenance: how "the translation asked for", "another translation of the same
  language", "a translation in another language" and "no translation we searched"
  are distinguished, and why the last of those is deliberately not called
  "invented"
- The hallucination track: generating impossible references; any presented quote fails
- Topical version preference: which translation a model quotes when unprompted (L2)
- Topical uncited-quote verification via an in-memory reverse phrase index
- The paused adversarial harness: pinned attacker model, deterministic judge, transcripts
- How to audit published results
