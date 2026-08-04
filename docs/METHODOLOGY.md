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
  verdicts, never re-judge them. Only a full `run` produces fresh ones.
- Encounters the referee cannot decide are **excluded from the rates** and reported
  as a referee error — our fault, named as ours, never scored against the model.

No language model appears anywhere in the two ranked dimensions — not even to
generate prompts. Re-running the scorer on the same responses and the same Bible
text always yields the same scores.

There is deliberately **no scoring-version stamp**. A stored score is only ever read
next to the code that produced it: if scoring changes, the answer is a complete
re-score of every run, not a version number that lets some records in a run be older
than others while every figure is presented as one measurement. Two operations exist
and the distinction between them is unambiguous — `run` does everything including the
model calls, `score` does everything except them.

Every prompt that asks for a quote names a specific Bible version, and every
result record carries its language and version, so all tracks — and the headline
— can be sliced by both.

Overall Score = Quoting Accuracy (0…+100) + Hallucination (−100…0), on a −100…+100 scale.

The creed pair is reported separately, as the Extended Benchmark, and is not
part of the headline.

Full methodology is being written alongside the implementation. It will cover:

- The two ranked dimensions, the unranked creed pair, and the ledger scale
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
- The creed harness: pinned open-weight referee, published prompts, stored transcripts
- How to audit published results
