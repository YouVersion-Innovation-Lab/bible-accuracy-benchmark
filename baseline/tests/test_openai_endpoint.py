"""End-to-end: the OpenAI routes over jittle's real engine (fixture mini-corpus)
plus jittle's deterministic StubLLMClient. No API key, no built corpus, no network.

This exercises the whole wrapper — request mapping, Chatbot.respond, response
mapping — and proves an engine-verified quote round-trips into OpenAI JSON.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BASE = Path(__file__).resolve().parents[1]
_MINI_CORPUS = _BASE / "vendor" / "jittle" / "tests" / "fixtures" / "mini_corpus"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    if not _MINI_CORPUS.exists():
        pytest.skip("jittle submodule fixtures not present (run git submodule update --init)")

    # Keep jittle's opt-in chat-history store off the real private-store/ path.
    os.environ["JOT_CHAT_HISTORY_DB"] = str(tmp_path_factory.mktemp("hist") / "h.db")

    from jot.corpus.build import build_db
    from jot.corpus.db import Corpus
    from jot.engine import Engine
    from jotchat.api import create_chat_app
    from jotchat.context_corpus import ContextCorpus
    from jotchat.llm import StubLLMClient

    from bible_baseline.routes import register_openai_routes

    corpus_db = tmp_path_factory.mktemp("corpus") / "mini.db"
    build_db(_MINI_CORPUS, corpus_db)
    engine = Engine(Corpus.open(corpus_db))

    app = create_chat_app(engine=engine, context_corpus=ContextCorpus.load(), llm=StubLLMClient())
    register_openai_routes(app)
    with TestClient(app) as c:
        yield c


def test_models_lists_the_baseline_id(client):
    body = client.get("/v1/models").json()
    assert body["object"] == "list"
    assert body["data"] and body["data"][0]["object"] == "model"


def test_direct_quote_round_trips_verbatim(client):
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "jot-tittle", "messages": [{"role": "user", "content": "Quote John 3:16 from the KJV."}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object"] == "chat.completion"
    content = body["choices"][0]["message"]["content"]
    # jittle serves the engine-verified verse text (KJV or its BSB fallback in the
    # mini corpus); the distinctive phrase is present in both.
    assert "loved the world" in content.lower()
    assert body["usage"]["total_tokens"] > 0


def test_missing_message_field_is_a_400(client):
    resp = client.post("/v1/chat/completions", json={"model": "jot-tittle"})
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "invalid_request_error"


def test_streaming_emits_sse_and_done(client):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "jot-tittle",
            "stream": True,
            "messages": [{"role": "user", "content": "Quote John 3:16 from the KJV."}],
        },
    )
    assert resp.status_code == 200
    text = resp.text
    assert "chat.completion.chunk" in text
    assert "data: [DONE]" in text
