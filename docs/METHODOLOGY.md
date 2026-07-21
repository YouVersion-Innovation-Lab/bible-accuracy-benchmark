# Methodology

> **Scope disclaimer:** This benchmark scores only the Biblical accuracy of scripture
> quotations in model responses — whether text presented as a Bible quote matches the
> cited translation. It does **not** score or rate the theological leanings, doctrinal
> positions, or theological accuracy of model responses.

## Scoring is fully deterministic

No language model ever renders or influences a score in this benchmark. Every
verdict — whether a quote is accurate, how badly it differs, whether it is the
wrong verse or the wrong translation — is produced by pure, reproducible text
comparison against the actual verse text of the cited translation, fetched from
YouVersion's Bible API.

Language models appear in exactly one place: generating the *attack prompts* in
the adversarial track (an attacker model tries to induce a misquote). The
attacker never judges the result — that verdict is deterministic too. Re-running
the scorer on the same responses and the same Bible text always yields the same
scores; the scoring version is stamped into every result record.

Full methodology is being written alongside the implementation. It will cover:

- The three tracks (simple / topical / adversarial) and the headline score formula
- The public sampling specification and per-refresh seeding (anti-gaming design)
- Text normalization and the deterministic Quote Error Rate (QER) metric
- The severity taxonomy (perfect → fabricated) and refusal handling
- The adversarial harness: pinned attacker model, deterministic judge, published transcripts
- Topical uncited-quote verification via an in-memory reverse phrase index
- How to audit published results
