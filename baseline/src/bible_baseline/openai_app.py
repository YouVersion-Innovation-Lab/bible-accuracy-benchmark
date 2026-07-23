"""ASGI entry point: jittle's full harness app + the OpenAI-compatible routes.

    uvicorn bible_baseline.openai_app:app

``create_chat_app`` builds jittle's complete pipeline (engine, corpus, optional
Platform overlay, grounding, and the injected generation client) and stashes the
``Chatbot`` on ``app.state``; we only add the OpenAI request/response shims. All
configuration comes from ``baseline/.env`` (loaded here so it works from any CWD).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load baseline/.env before building the app so jittle's lifespan sees JOT_CORPUS,
# JOT_YVP_KEY, CANTOR, etc. (load_dotenv does not override already-exported vars).
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

from jotchat.api import create_chat_app  # noqa: E402 — must follow load_dotenv

from .llm_client import OpenAICompatLLMClient  # noqa: E402
from .routes import register_openai_routes  # noqa: E402


def _build_llm() -> OpenAICompatLLMClient | None:
    """Configured generation client, or None to let jittle run keyless (Tier A +
    refusals still work; topical answers use jittle's safe no-synthesis fallback)."""
    base_url = os.environ.get("BASELINE_LLM_BASE_URL")
    api_key = os.environ.get("BASELINE_LLM_API_KEY")
    model = os.environ.get("BASELINE_LLM_MODEL")
    if not (base_url and api_key and model):
        return None
    return OpenAICompatLLMClient(base_url=base_url, api_key=api_key, model=model)


app = create_chat_app(llm=_build_llm())
register_openai_routes(app)
