"""Generation must FAIL FAST: one exhausted-retry model call aborts the run.

A partially-generated pass cannot produce a valid benchmark result — failed calls
reach the scorers as "no attempt", which deflates the quote tracks and *inflates*
hallucination resistance (an empty response reads as "declined to quote"). So a
failed call must abort, never be recorded as a hole.
"""

import asyncio

import pytest

from bible_bench.dataset import BenchmarkItem
from bible_bench.hallucination import HallucinationItem
from bible_bench.llm import LlmResponse
from bible_bench.runner import (
    EvaluationError,
    generate_hallucination,
    generate_simple,
)


class BoomClient:
    """Stands in for LlmClient once its internal retries are exhausted."""

    def __init__(self, fail_on: int = 0):
        self.calls = 0
        self._fail_on = fail_on

    async def complete(self, messages, **kwargs):
        n = self.calls
        self.calls += 1
        if n == self._fail_on:
            raise RuntimeError("LLM call to m failed after 4 attempts: APIStatusError: 402")
        return LlmResponse(text="some text", finish_reason="stop", model="m",
                           prompt_tokens=1, completion_tokens=1)


class StubBible:
    """Just enough BibleClient surface for render_simple_prompt."""

    async def version(self, version_id):
        return {"title": "Fake Version", "abbreviation": "FAKE"}

    async def human_reference(self, version_id, usfm):
        return "Genesis 1:1"


def _simple_item(i: int) -> BenchmarkItem:
    return BenchmarkItem(
        id=f"s-{i}", track="simple", language_tag="eng", language_name="English",
        version_id=1, version_abbrev="FAKE", usfm="GEN.1.1", source_usfm="GEN.1.1",
        tier="famous", template_id="quote_exact",
    )


def _hallucination_item(i: int) -> HallucinationItem:
    return HallucinationItem(
        id=f"p-{i}", track="hallucination", language_tag="eng", version_id=1,
        version_abbrev="FAKE", reference_display="Psalm 180:1",
        kind="out_of_range_chapter", prompt="Quote Psalm 180:1.",
    )


def test_simple_generation_aborts_on_failed_call():
    items = [_simple_item(i) for i in range(4)]
    with pytest.raises(EvaluationError) as ei:
        asyncio.run(generate_simple(items, StubBible(), BoomClient(fail_on=0),
                                    concurrency=1))
    assert "simple item" in str(ei.value)
    # The underlying cause is preserved for diagnosis.
    assert "402" in str(ei.value)


def test_hallucination_generation_aborts_on_failed_call():
    items = [_hallucination_item(i) for i in range(4)]
    with pytest.raises(EvaluationError) as ei:
        asyncio.run(generate_hallucination(items, BoomClient(fail_on=0), concurrency=1))
    assert "hallucination item" in str(ei.value)


def test_failure_midway_still_aborts_not_partially_recorded():
    """A late failure must abort too — the danger case is a run that mostly
    succeeded, because its numbers look plausible."""
    items = [_hallucination_item(i) for i in range(6)]
    with pytest.raises(EvaluationError):
        asyncio.run(generate_hallucination(items, BoomClient(fail_on=4), concurrency=1))


def test_clean_run_returns_all_records():
    items = [_hallucination_item(i) for i in range(3)]
    recs = asyncio.run(generate_hallucination(items, BoomClient(fail_on=-1), concurrency=2))
    assert len(recs) == 3
    assert all(r["error"] is None for r in recs)
