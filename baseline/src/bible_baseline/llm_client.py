"""A thin LLMClient for jittle over any OpenAI-compatible endpoint.

Implements jittle's ``jotchat.llm.LLMClient`` Protocol (``complete`` + ``classify``
+ ``model_id``) by forwarding to the OpenAI Python SDK against a configurable
``base_url`` / ``api_key`` / ``model``. This is protocol glue only — it adds no
Scripture/domain logic; all generation, routing, and verification behavior lives
in jittle. It exists so jittle's generation can run against whatever
OpenAI-compatible model the operator configures in ``baseline/.env``.
"""

from __future__ import annotations

import json

from openai import OpenAI


def _to_text(content: object) -> str:
    """Coerce an Anthropic-style message ``content`` (str or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _strip_fences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


class OpenAICompatLLMClient:
    """jittle ``LLMClient`` backed by an OpenAI-compatible Chat Completions endpoint.

    The configured model is always used; jittle's per-tier model hints (which are
    Claude-specific) are ignored so any endpoint works. Calls are synchronous —
    jittle invokes them inside a threadpool.
    """

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 120.0):
        self._model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    @property
    def model_id(self) -> str:
        return self._model

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> str:
        oa_messages: list[dict] = []
        if system:
            oa_messages.append({"role": "system", "content": system})
        for m in messages:
            oa_messages.append(
                {"role": m.get("role", "user"), "content": _to_text(m.get("content", ""))}
            )
        resp = self._client.chat.completions.create(
            model=self._model, messages=oa_messages, max_tokens=max_tokens
        )
        return resp.choices[0].message.content or ""

    def classify(
        self,
        *,
        system: str,
        text: str,
        schema: dict,
        model: str | None = None,
        max_tokens: int = 1024,
    ) -> dict:
        instruction = (
            (system + "\n\n" if system else "")
            + "Respond with ONLY a single JSON object that conforms to this JSON Schema. "
            "Emit no prose and no markdown fences.\nSchema:\n"
            + json.dumps(schema)
        )
        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": text},
        ]
        raw = self._chat_json(messages, max_tokens)
        try:
            return json.loads(_strip_fences(raw))
        except json.JSONDecodeError:
            # One repair retry, mirroring jittle's own AnthropicClient.classify. If it
            # still fails, the exception propagates and jittle's classify() falls back
            # to its deterministic rules (fail toward flagging) — safe by design.
            repair = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That was not valid JSON. Reply with ONLY the JSON object."},
            ]
            return json.loads(_strip_fences(self._chat_json(repair, max_tokens)))

    def _chat_json(self, messages: list[dict], max_tokens: int) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception:  # noqa: BLE001 — endpoint may not support response_format; retry plain
            resp = self._client.chat.completions.create(
                model=self._model, messages=messages, max_tokens=max_tokens
            )
        return resp.choices[0].message.content or ""
