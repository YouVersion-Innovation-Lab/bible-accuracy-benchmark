"""Empty-reply handling in the LLM client.

An empty reply caused by hitting the output-token cap is a truncated
measurement, not the model's answer — it must retry, then abort the run. Every
other empty reply is a real (if unhelpful) observation and is passed through to
be scored as a zero, so the benchmark stays interpretable: one rule, "no text
earns no credit", with no scoring special cases.
"""

import asyncio
import types

import pytest

from bible_bench.config import LlmEndpointConfig
from bible_bench.llm import LlmClient, _is_truncated


def _fake_api_response(text: str, finish_reason: str, completion_tokens: int = 0):
    """Minimal stand-in for an OpenAI-compatible SDK response object."""
    msg = types.SimpleNamespace(content=text, refusal=None)
    choice = types.SimpleNamespace(message=msg, finish_reason=finish_reason)
    usage = types.SimpleNamespace(
        prompt_tokens=10, completion_tokens=completion_tokens,
        completion_tokens_details=None,
    )
    return types.SimpleNamespace(
        choices=[choice], usage=usage, model="m", id="resp-1",
        system_fingerprint=None, model_dump=lambda mode=None: {},
    )


def _client(responses, max_retries=3):
    """LlmClient whose transport yields the given canned responses in order."""
    cfg = LlmEndpointConfig(base_url="https://example.test/v1", api_key="k",
                            model="m", label="M")
    c = LlmClient(cfg, max_retries=max_retries)
    seq = list(responses)
    calls = {"n": 0}

    async def create(**kwargs):
        calls["n"] += 1
        return seq[min(calls["n"] - 1, len(seq) - 1)]

    c._client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )
    c.calls = calls
    return c


def test_is_truncated_matches_provider_spellings():
    assert _is_truncated("length")
    assert _is_truncated("MAX_TOKENS")
    assert _is_truncated("max_output_tokens")
    assert not _is_truncated("stop")
    assert not _is_truncated("content_filter: RECITATION")
    assert not _is_truncated(None)


def test_empty_and_truncated_retries_then_raises():
    c = _client([_fake_api_response("", "length", completion_tokens=8192)])
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(c.complete([{"role": "user", "content": "hi"}]))
    # Retried the full budget, then surfaced the real reason.
    assert c.calls["n"] == 3
    assert "truncated" in str(ei.value).lower() or "TruncatedResponseError" in str(ei.value)


def test_empty_and_truncated_recovers_if_a_retry_returns_text():
    c = _client([
        _fake_api_response("", "length", completion_tokens=8192),
        _fake_api_response("For God so loved the world", "stop", completion_tokens=7),
    ])
    out = asyncio.run(c.complete([{"role": "user", "content": "hi"}]))
    assert out.text == "For God so loved the world"
    assert c.calls["n"] == 2


def test_empty_from_content_filter_is_returned_not_retried():
    """A provider block is a real observation — pass it through to score as 0.
    Retrying wouldn't help, and aborting would make such a model unbenchmarkable."""
    c = _client([_fake_api_response("", "content_filter: RECITATION")])
    out = asyncio.run(c.complete([{"role": "user", "content": "hi"}]))
    assert out.text == ""
    assert out.finish_reason == "content_filter: RECITATION"
    assert c.calls["n"] == 1


def test_empty_with_stop_is_returned_not_retried():
    c = _client([_fake_api_response("", "stop")])
    out = asyncio.run(c.complete([{"role": "user", "content": "hi"}]))
    assert out.text == ""
    assert c.calls["n"] == 1


def test_nonempty_truncated_response_is_kept():
    """Truncation only matters when it left us with nothing; a long-but-cut-off
    answer is still gradeable."""
    c = _client([_fake_api_response("In the beginning God", "length", 8192)])
    out = asyncio.run(c.complete([{"role": "user", "content": "hi"}]))
    assert out.text == "In the beginning God"
    assert c.calls["n"] == 1
