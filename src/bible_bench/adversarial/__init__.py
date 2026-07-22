"""Adversarial track: an attacker LLM tries to induce scripture misquotes.

The attacker (a pinned harness model) generates prompts; the target model
under test responds; a fully deterministic judge (the QuoteAuditor) decides
whether a misquote was produced. No LLM judges any score — the attacker only
generates attacks.
"""
