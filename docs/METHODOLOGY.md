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

This round, no language model appears anywhere in the scored tracks — not even
to generate prompts. (A paused adversarial track uses a pinned attacker model to
generate *attack prompts*; even there the judge is deterministic.) Re-running the
scorer on the same responses and the same Bible text always yields the same
scores; the scoring version is stamped into every result record.

Every prompt that asks for a quote names a specific Bible version, and every
result record carries its language and version, so all tracks — and the headline
— can be sliced by both.

Headline = 100 × (0.50 · simple + 0.25 · topical + 0.25 · hallucination
resistance).

Full methodology is being written alongside the implementation. It will cover:

- The three tracks (simple / topical / hallucination) and the headline score formula
- The public sampling specification and per-refresh seeding (anti-gaming design)
- Text normalization and the deterministic Quote Error Rate (QER) metric
- The severity taxonomy (perfect → fabricated) and refusal handling
- The hallucination track: generating impossible references; any presented quote fails
- Topical version preference: which translation a model quotes when unprompted (L2)
- Topical uncited-quote verification via an in-memory reverse phrase index
- The paused adversarial harness: pinned attacker model, deterministic judge, transcripts
- How to audit published results
