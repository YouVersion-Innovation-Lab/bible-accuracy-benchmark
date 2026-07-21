# Methodology

> **Scope disclaimer:** This benchmark scores only the Biblical accuracy of scripture
> quotations in model responses — whether text presented as a Bible quote matches the
> cited translation. It does **not** score or rate the theological leanings, doctrinal
> positions, or theological accuracy of model responses.

Full methodology is being written alongside the implementation. It will cover:

- The three tracks (simple / topical / adversarial) and the headline score formula
- The public sampling specification and per-refresh seeding (anti-gaming design)
- Text normalization and the deterministic Quote Error Rate (QER) metric
- The severity taxonomy (perfect → fabricated) and refusal handling
- The adversarial harness: pinned attacker model, deterministic judge, published transcripts
- How to audit published results
