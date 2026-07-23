"""Pure, mechanical mapping between the OpenAI Chat Completions wire format and
jittle's ``ChatRequest`` / ``ChatResponse``.

No Scripture, translation, or routing logic lives here — the request side hands
jittle the user's text verbatim (jittle detects the requested version itself), and
the response side serializes whatever jittle returned into a single text field.
"""

from __future__ import annotations

from jotchat.contracts import MAX_MESSAGE_CHARS, ChatRequest, ChatResponse


def _content_to_text(content: object) -> str:
    """OpenAI message ``content`` may be a string or a list of parts; flatten to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return "" if content is None else str(content)


def last_user_message(messages: list[dict] | None) -> str:
    """The text of the last ``user`` turn. jittle is stateless and single-message,
    so the latest user turn is the query; other turns and system prompts are not
    injected (jittle supplies its own system prompt / safety constitution)."""
    for message in reversed(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return _content_to_text(message.get("content"))
    return ""


def system_instructions(messages: list[dict] | None) -> str:
    """Concatenated text of any ``system`` turns, in order (empty if none)."""
    return "\n\n".join(
        _content_to_text(m.get("content"))
        for m in (messages or [])
        if isinstance(m, dict) and m.get("role") == "system"
    ).strip()


def to_chat_request(body: dict) -> ChatRequest:
    """Map an OpenAI request body to a jittle ``ChatRequest``.

    jittle has no separate system-prompt field (it supplies its own safety
    constitution), so an OpenAI ``system`` message is forwarded by prepending it to
    the user's message — the only channel jittle exposes. This keeps the mapping
    mechanical while letting a caller's instructions reach jittle's generation; they
    are treated as ordinary input, fully subject to jittle's routing, verified-
    citation loop, and output lint (they cannot override any of them)."""
    messages = body.get("messages")
    user = last_user_message(messages)
    system = system_instructions(messages)
    combined = f"{system}\n\n{user}".strip() if system else user
    return ChatRequest(message=combined[:MAX_MESSAGE_CHARS])


def render_content(resp: ChatResponse) -> str:
    """Serialize a jittle ``ChatResponse`` into one assistant-message string.

    jittle keeps verse text in ``passages`` (not in ``answer_markdown``), so both
    are emitted; positions (Tier C range), refusal/handoff, clarify, and crisis
    resources are appended when jittle populated them. This is a faithful dump of
    jittle's user-facing output — it makes no editorial decisions.
    """
    parts: list[str] = []

    if resp.answer_markdown and resp.answer_markdown.strip():
        parts.append(resp.answer_markdown.strip())

    for p in resp.passages:
        block = f'{p.reference} ({p.translation})\n"{p.text}"'
        if p.attribution:
            block += f"\n{p.attribution}"
        parts.append(block)

    for pos in resp.positions:
        line = pos.label
        if pos.traditions:
            line += f" [{', '.join(pos.traditions)}]"
        if pos.summary:
            line += f"\n{pos.summary}"
        if pos.citation:
            line += f"\n{pos.citation}"
        parts.append(line)

    if resp.refusal:
        if resp.refusal.message:
            parts.append(resp.refusal.message)
        if resp.refusal.handoff:
            parts.append(resp.refusal.handoff)

    if resp.clarify and resp.clarify.question:
        parts.append(resp.clarify.question)

    if resp.crisis and resp.crisis.surfaced:
        lines = [resp.crisis.message]
        for r in resp.crisis.resources:
            entry = f"- {r.get('name', '')}: {r.get('detail', '')} {r.get('url', '')}".strip()
            if entry != "-":
                lines.append(entry)
        parts.append("\n".join(lines))

    return "\n\n".join(part for part in parts if part and part.strip())


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def to_completion(
    resp: ChatResponse,
    *,
    model_id: str,
    created: int,
    request_id: str,
    prompt_text: str,
) -> dict:
    """Build an OpenAI ``chat.completion`` object from a jittle ``ChatResponse``.

    ``usage`` counts are a documented approximation (~chars/4): jittle does not
    surface token usage. jittle's own provenance (engine + generation model) rides
    on ``system_fingerprint`` for auditability; standard clients ignore it.
    """
    content = render_content(resp)
    prompt_tokens = _approx_tokens(prompt_text)
    completion_tokens = _approx_tokens(content)
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": created,
        "model": model_id,
        "system_fingerprint": f"jot;engine={resp.engine_version};gen={resp.model}",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
