"""Generation must FAIL FAST: one exhausted-retry model call aborts the run.

A partially-generated pass cannot produce a valid benchmark result — failed calls
reach the scorers as "no attempt", which deflates the quote tracks and *inflates*
hallucination resistance (an empty response reads as "declined to quote"). So a
failed call must abort, never be recorded as a hole.
"""

import asyncio

import pytest

from bible_bench.dataset import BenchmarkItem
from bible_bench.llm import LlmResponse
from bible_bench.phantom import PhantomItem
from bible_bench.runner import (
    EvaluationError,
    generate_phantom,
    generate_simple,
    generate_topical,
)
from bible_bench.topical import TopicalItem


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


def _topical_item(i: int) -> TopicalItem:
    return TopicalItem(
        id=f"t-{i}", track="topical", language_tag="eng", version_id=1,
        version_abbrev="FAKE", topic_id="anxiety", topic_name="anxiety",
        elicitation_level="L1", sensitive=False, prompt="What does the Bible say?",
    )


def _phantom_item(i: int) -> PhantomItem:
    return PhantomItem(
        id=f"p-{i}", track="phantom", language_tag="eng", version_id=1,
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


def test_topical_generation_aborts_on_failed_call():
    items = [_topical_item(i) for i in range(4)]
    with pytest.raises(EvaluationError) as ei:
        asyncio.run(generate_topical(items, BoomClient(fail_on=0), concurrency=1))
    assert "topical item" in str(ei.value)


def test_phantom_generation_aborts_on_failed_call():
    items = [_phantom_item(i) for i in range(4)]
    with pytest.raises(EvaluationError) as ei:
        asyncio.run(generate_phantom(items, BoomClient(fail_on=0), concurrency=1))
    assert "phantom item" in str(ei.value)


def test_failure_midway_still_aborts_not_partially_recorded():
    """A late failure must abort too — the danger case is a run that mostly
    succeeded, because its numbers look plausible."""
    items = [_topical_item(i) for i in range(6)]
    with pytest.raises(EvaluationError):
        asyncio.run(generate_topical(items, BoomClient(fail_on=4), concurrency=1))


def test_clean_run_returns_all_records():
    items = [_topical_item(i) for i in range(3)]
    recs = asyncio.run(generate_topical(items, BoomClient(fail_on=-1), concurrency=2))
    assert len(recs) == 3
    assert all(r["error"] is None for r in recs)
