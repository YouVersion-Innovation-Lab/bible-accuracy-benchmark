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
from urllib.parse import urlparse

from openai import AsyncOpenAI

from .config import LlmEndpointConfig

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _is_openrouter(base_url: str) -> bool:
    """True iff the endpoint is OpenRouter — the only host we send `provider` to."""
    host = (urlparse(base_url).hostname or "").lower()
    return host == "openrouter.ai" or host.endswith(".openrouter.ai")


# Ceiling for auto-growing the token cap when a reasoning model returns an empty
# completion because its hidden reasoning consumed the whole budget (finish_reason
# "length"). Bounded so a genuine runaway stays capped and we never request more
# output than a model allows.
_MAX_TOKENS_CEILING = 8192


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
        # Per-model param adaptation, discovered on the first 400 (see
        # _maybe_adapt_params) and then persisted for this client: the newest
        # "thinking" flagships reject `temperature`, and OpenAI wants
        # `max_completion_tokens` in place of `max_tokens`.
        self._max_tokens_param = "max_tokens"
        self._send_temperature = True
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
        attempts = 0
        adaptations = 0
        effective_max = max_tokens
        while attempts < self.max_retries:
            try:
                kwargs: dict = {"model": self.cfg.model, "messages": messages}
                if self._send_temperature:
                    kwargs["temperature"] = temperature
                if effective_max is not None:
                    kwargs[self._max_tokens_param] = effective_max
                # OpenRouter-only: forward upstream routing (pin provider/quantization)
                # for reproducible scoring. Never sent to native endpoints — their
                # OpenAI-compat layers reject unknown body fields (Gemini especially).
                if self.cfg.provider_routing and _is_openrouter(self.cfg.base_url):
                    kwargs["extra_body"] = {"provider": self.cfg.provider_routing}
                resp = await asyncio.wait_for(
                    self._client.chat.completions.create(**kwargs), timeout=self.timeout
                )
                choice = resp.choices[0]
                text = choice.message.content or ""
                if resp.usage:
                    self.usage.add(resp.usage.prompt_tokens, resp.usage.completion_tokens)
                # Empty output because we hit the cap (finish_reason "length") — a
                # reasoning model spent the whole budget on hidden reasoning before
                # emitting anything. That's our setting starving the output, not a
                # refusal, so grow the cap and retry (up to a safe ceiling) instead of
                # recording a blank. A *non-empty* truncation is returned as-is, so a
                # genuine runaway stays capped.
                if (not text.strip() and choice.finish_reason == "length"
                        and effective_max is not None
                        and effective_max < _MAX_TOKENS_CEILING):
                    effective_max = min(effective_max * 4, _MAX_TOKENS_CEILING)
                    continue
                if return_json:
                    extract_json(text)  # validate; caller re-parses
                return text
            except Exception as e:  # noqa: BLE001 — retry all transient failures
                last_err = e
                # Newest models reject params the benchmark sends by default
                # (temperature; or max_tokens where max_completion_tokens is required).
                # Adapt once per condition and retry immediately, without spending a
                # retry attempt — the fix persists so later calls send it correctly.
                if adaptations < 2 and self._maybe_adapt_params(e):
                    adaptations += 1
                    continue
                attempts += 1
                await asyncio.sleep(min(2**attempts, 30))
        raise RuntimeError(
            f"LLM call to {self.cfg.model} failed after {self.max_retries} attempts"
        ) from last_err

    def _maybe_adapt_params(self, err: Exception) -> bool:
        """On a 400 that rejects a default param, switch to what the model accepts:
        OpenAI's ``max_completion_tokens`` rename, and newest 'thinking' models that
        reject ``temperature``. Returns True if a parameter was changed."""
        msg = str(err).lower()
        changed = False
        if self._max_tokens_param == "max_tokens" and "max_completion_tokens" in msg:
            self._max_tokens_param = "max_completion_tokens"
            changed = True
        if self._send_temperature and "temperature" in msg and any(
            s in msg for s in (
                "deprecated", "does not support", "only the default",
                "unsupported value", "not supported", "unsupported parameter",
            )
        ):
            self._send_temperature = False
            changed = True
        return changed

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
