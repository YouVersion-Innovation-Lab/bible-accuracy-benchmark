"""Async OpenAI-compatible LLM client with usage/cost capture.

Adapted from the llmloadtest GOAL LlmWrapper (retries, timeout, robust JSON
extraction), rewritten to add token/cost accounting and drop all hard-coded
credentials — every endpoint arrives via config.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

from .config import LlmEndpointConfig

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cost_usd: float | None = None

    def add(self, prompt: int, completion: int) -> None:
        self.input_tokens += prompt
        self.output_tokens += completion
        self.calls += 1


@dataclass
class LlmResult:
    text: str
    input_tokens: int
    output_tokens: int


def extract_json(text: str) -> dict | list:
    """Best-effort parse of a JSON object/array from model output."""
    m = _JSON_FENCE.search(text)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()
    # Narrow to the outermost bracket pair if there's surrounding prose.
    start = min(
        (i for i in (candidate.find("{"), candidate.find("[")) if i != -1),
        default=-1,
    )
    if start > 0:
        candidate = candidate[start:]
    for parser in (json.loads, ast.literal_eval):
        try:
            result = parser(candidate)
            if isinstance(result, (dict, list)):
                return result
        except (ValueError, SyntaxError):
            continue
    raise ValueError(f"Could not extract JSON from: {text[:200]!r}")


class LlmClient:
    """One OpenAI-compatible endpoint. Uses temperature 0 for determinism.

    We deliberately do NOT send an API `seed`: it's supported unevenly across
    OpenAI-compatible providers (Gemini's compat layer rejects it), so relying
    on it would make determinism all-or-nothing per provider. temperature=0 is
    the uniform, portable setting every model honors.
    """

    def __init__(
        self,
        cfg: LlmEndpointConfig,
        *,
        dummy: bool = False,
        max_retries: int = 4,
        timeout: float = 120.0,
    ):
        self.cfg = cfg
        self.dummy = dummy
        self.max_retries = max_retries
        self.timeout = timeout
        self.usage = Usage()
        self._client = (
            None if dummy else AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        return_json: bool = False,
    ) -> str:
        if self.dummy:
            await asyncio.sleep(0)
            return self._dummy(messages, return_json)

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                kwargs: dict = {
                    "model": self.cfg.model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                resp = await asyncio.wait_for(
                    self._client.chat.completions.create(**kwargs), timeout=self.timeout
                )
                text = resp.choices[0].message.content or ""
                if resp.usage:
                    self.usage.add(resp.usage.prompt_tokens, resp.usage.completion_tokens)
                if return_json:
                    extract_json(text)  # validate; caller re-parses
                return text
            except Exception as e:  # noqa: BLE001 — retry all transient failures
                last_err = e
                await asyncio.sleep(min(2**attempt, 30))
        raise RuntimeError(
            f"LLM call to {self.cfg.model} failed after {self.max_retries} attempts"
        ) from last_err

    def _dummy(self, messages: list[dict[str, str]], return_json: bool) -> str:
        self.usage.add(0, 0)
        if return_json:
            return '{"affirmed": "false"}'
        return f"[DUMMY] {messages[-1].get('content', '')[:80]}"


# Token pricing per 1M tokens, USD. Optional — unknown models report tokens
# with cost_usd = None rather than a misleading 0.
_PRICING: dict[str, tuple[float, float]] = {}


def estimate_cost(usage: Usage, model: str) -> float | None:
    price = _PRICING.get(model)
    if price is None:
        return None
    return (usage.input_tokens * price[0] + usage.output_tokens * price[1]) / 1_000_000
