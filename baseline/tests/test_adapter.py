"""Pure mapping tests — no jittle engine, no network, no key."""

from __future__ import annotations

from bible_baseline.adapter import (
    last_user_message,
    render_content,
    to_chat_request,
    to_completion,
)
from jotchat.contracts import (
    ChatResponse,
    Clarification,
    Outcome,
    Refusal,
    RefusalReason,
    Tier,
    VerifiedPassage,
)


def test_last_user_message_picks_last_user_turn():
    messages = [
        {"role": "system", "content": "you are..."},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "Quote John 3:16"},
    ]
    assert last_user_message(messages) == "Quote John 3:16"


def test_content_parts_are_flattened():
    messages = [{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]
    assert last_user_message(messages) == "a\nb"


def test_to_chat_request_maps_message_and_leaves_translation_to_jittle():
    req = to_chat_request({"messages": [{"role": "user", "content": "Quote John 3:16 in the ESV"}]})
    assert req.message == "Quote John 3:16 in the ESV"
    # The wrapper adds no translation logic — jittle detects the version itself.
    assert req.translation is None


def test_system_message_is_forwarded_into_the_message():
    req = to_chat_request(
        {
            "messages": [
                {"role": "system", "content": "Wrap all Bible quotes in ((double parens))."},
                {"role": "user", "content": "What does the Bible say about anxiety?"},
            ]
        }
    )
    # jittle has no system field; the instruction is prepended so it reaches jittle.
    assert "double parens" in req.message
    assert "anxiety" in req.message


def test_render_content_includes_verbatim_passage_and_attribution():
    resp = ChatResponse(
        tier=Tier.A_TEXTUAL,
        outcome=Outcome.ANSWERED,
        answer_markdown="Here is John 3:16 (KJV), shown below with its source.",
        passages=[
            VerifiedPassage(
                reference="John 3:16",
                usfm="JHN.3.16",
                translation="KJV",
                text="For God so loved the world",
                attribution="Public Domain",
                deep_link="https://www.bible.com/bible/1/JHN.3.16",
            )
        ],
    )
    out = render_content(resp)
    assert "For God so loved the world" in out
    assert "John 3:16 (KJV)" in out
    assert "Public Domain" in out


def test_render_content_refusal_uses_fixed_body_and_handoff():
    resp = ChatResponse(
        tier=Tier.D_PASTORAL,
        outcome=Outcome.REFUSED,
        refusal=Refusal(
            reason=RefusalReason.OUT_OF_SCOPE,
            message="This study tool cannot help with that.",
            handoff="A pastor is a better companion for this.",
        ),
    )
    out = render_content(resp)
    assert "This study tool cannot help with that." in out
    assert "A pastor is a better companion for this." in out


def test_render_content_clarify_returns_question():
    resp = ChatResponse(
        tier=Tier.D_PASTORAL,
        outcome=Outcome.CLARIFIED,
        clarify=Clarification(question="Which passage did you have in mind?"),
    )
    assert render_content(resp) == "Which passage did you have in mind?"


def test_to_completion_is_openai_shaped():
    resp = ChatResponse(
        tier=Tier.A_TEXTUAL,
        outcome=Outcome.ANSWERED,
        answer_markdown="hello",
        model="claude-sonnet-5",
        engine_version="jot-1",
    )
    comp = to_completion(
        resp,
        model_id="jot-tittle",
        created=123,
        request_id="chatcmpl-abc",
        prompt_text="Quote John 3:16",
    )
    assert comp["object"] == "chat.completion"
    assert comp["model"] == "jot-tittle"
    assert comp["id"] == "chatcmpl-abc"
    choice = comp["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == "hello"
    assert choice["finish_reason"] == "stop"
    usage = comp["usage"]
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    # jittle provenance travels for auditability.
    assert "engine=jot-1" in comp["system_fingerprint"]
    assert "gen=claude-sonnet-5" in comp["system_fingerprint"]
