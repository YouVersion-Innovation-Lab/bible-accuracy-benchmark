"""Basic Christian Theology: does a model hold to the Nicene Creed, and will it
disagree when pressed to deny it?

Replaces the retired `adversarial` track. Unlike every other dimension in this
benchmark, this one is NOT deterministic — the attacker argues live, an LLM
judges, and a tutor adapts the attack between turns. Generation and scoring
therefore cannot be separated the way they are elsewhere: the judge's verdict
feeds the tutor, which changes the next turn. Re-scoring re-aggregates stored
verdicts; it cannot re-judge without changing the conversation that produced them.
"""

from .encounter import (
    MAX_TOKENS,
    EncounterResult,
    Turn,
    VerdictError,
    is_failure,
    run_encounter,
)
from .probes import AFFIRM, CONTRADICT, CreedSpec, TheologyItem, build_items, load_spec
from .score import SCORING_VERSION, from_records, rescale, summarize, summarize_records

__all__ = [
    "AFFIRM", "CONTRADICT", "MAX_TOKENS", "SCORING_VERSION", "CreedSpec",
    "EncounterResult", "TheologyItem", "Turn", "VerdictError", "build_items",
    "from_records", "is_failure", "load_spec", "rescale", "run_encounter",
    "summarize", "summarize_records",
]
