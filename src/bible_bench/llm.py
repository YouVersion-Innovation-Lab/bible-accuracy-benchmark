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


def _is_openai(base_url: str) -> bool:
    """True for OpenAI's own API — its newer models require `max_completion_tokens`
    instead of `max_tokens`."""
    host = (urlparse(base_url).hostname or "").lower()
    return host == "api.openai.com" or host.endswith(".openai.azure.com")


# One flat output cap for every call. Large enough that no scripture answer (even
# multi-verse topical plus a reasoning model's hidden reasoning) is truncated, and
# small enough that every model we target accepts it (Claude/Gemini cap output near
# here; higher 400s on some). No grow-and-retry — if a reply ever truncates, the
# stored finish_reason == "length" will surface it.
MAX_OUTPUT_TOKENS = 8192


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
class LlmResponse:
    """A model reply plus the metadata we persist so any oddity (refusals,
    content filters, truncation, which upstream served it) is drillable later."""
    text: str
    finish_reason: str | None = None
    refusal: str | None = None
    model: str | None = None              # model the API reported serving
    response_id: str | None = None
    system_fingerprint: str | None = None
    provider: str | None = None           # OpenRouter upstream, when present
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int | None = None
    raw: dict | None = None               # full response payload, nothing dropped


def _to_response(resp) -> "LlmResponse":
    """Pull our standardized fields out of an OpenAI-compatible response while
    keeping the full raw payload, so provider-specific extras survive."""
    choice = resp.choices[0] if getattr(resp, "choices", None) else None
    msg = getattr(choice, "message", None) if choice else None
    usage = getattr(resp, "usage", None)
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    try:
        raw = resp.model_dump(mode="json")
    except Exception:  # noqa: BLE001 — metadata capture must never break a call
        raw = None
    return LlmResponse(
        text=(getattr(msg, "content", None) or "") if msg else "",
        finish_reason=getattr(choice, "finish_reason", None) if choice else None,
        refusal=getattr(msg, "refusal", None) if msg else None,
        model=getattr(resp, "model", None),
        response_id=getattr(resp, "id", None),
        system_fingerprint=getattr(resp, "system_fingerprint", None),
        provider=(raw or {}).get("provider"),
        prompt_tokens=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
        completion_tokens=(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        reasoning_tokens=getattr(details, "reasoning_tokens", None) if details else None,
        raw=raw,
    )


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
    """One OpenAI-compatible endpoint.

    Evaluation calls send NO `temperature` — each model samples at its own
    default, which is part of what we measure and sidesteps the newest "thinking"
    models rejecting an explicit temperature. Callers may still pass one (the
    adversarial harness does). We also send no `seed` (unsupported unevenly).
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
        # OpenAI's newer models want `max_completion_tokens`; everyone else takes
        # `max_tokens`. Decided once, up front, from the host — no runtime probing.
        self._max_tokens_param = (
            "max_completion_tokens" if _is_openai(cfg.base_url) else "max_tokens"
        )
        self._client = (
            None if dummy else AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        return_json: bool = False,
    ) -> LlmResponse:
        """Call the model once (with retries) and return the reply + metadata.

        `temperature` is omitted unless explicitly passed — evaluation calls send
        none. `max_tokens` defaults to MAX_OUTPUT_TOKENS and is sent under the
        host-correct param name."""
        if self.dummy:
            await asyncio.sleep(0)
            return self._dummy(messages, return_json)

        cap = MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                kwargs: dict = {
                    "model": self.cfg.model,
                    "messages": messages,
                    self._max_tokens_param: cap,
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature
                # OpenRouter-only: pin upstream routing (provider/quantization).
                # Never sent to native endpoints — their OpenAI-compat layers
                # reject unknown body fields (Gemini especially).
                if self.cfg.provider_routing and _is_openrouter(self.cfg.base_url):
                    kwargs["extra_body"] = {"provider": self.cfg.provider_routing}
                resp = await asyncio.wait_for(
                    self._client.chat.completions.create(**kwargs), timeout=self.timeout
                )
                out = _to_response(resp)
                self.usage.add(out.prompt_tokens, out.completion_tokens)
                if return_json and out.text.strip():
                    extract_json(out.text)  # validate; caller re-parses
                return out
            except Exception as e:  # noqa: BLE001 — retry all transient failures
                last_err = e
                await asyncio.sleep(min(2**attempt, 30))
        raise RuntimeError(
            f"LLM call to {self.cfg.model} failed after {self.max_retries} attempts"
        ) from last_err

    def _dummy(self, messages: list[dict[str, str]], return_json: bool) -> LlmResponse:
        self.usage.add(0, 0)
        text = ('{"affirmed": "false"}' if return_json
                else f"[DUMMY] {messages[-1].get('content', '')[:80]}")
        return LlmResponse(text=text, finish_reason="stop", model="dummy")


# Token pricing per 1M tokens, USD. Optional — unknown models report tokens
# with cost_usd = None rather than a misleading 0.
_PRICING: dict[str, tuple[float, float]] = {}


def estimate_cost(usage: Usage, model: str) -> float | None:
    price = _PRICING.get(model)
    if price is None:
        return None
    return (usage.input_tokens * price[0] + usage.output_tokens * price[1]) / 1_000_000
