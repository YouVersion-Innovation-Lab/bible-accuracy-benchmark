"""OpenAI-compatible HTTP routes, registered onto jittle's own FastAPI app.

Two endpoints: ``GET /v1/models`` and ``POST /v1/chat/completions`` (with optional
SSE streaming). Each request is mapped to jittle's ``Chatbot.respond`` and its
result mapped back — no domain logic here. jittle's security middleware (headers,
content-length cap, optional org token) already wraps every ``/v1/*`` route.
"""

from __future__ import annotations

import json
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from .adapter import last_user_message, render_content, to_chat_request, to_completion


def _error(message: str, status: int, err_type: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": err_type}}, status_code=status)


def register_openai_routes(app: FastAPI) -> None:
    model_id = os.environ.get("BASELINE_MODEL_ID", "jot-tittle")

    @app.get("/v1/models")
    async def list_models() -> dict:
        return {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "youversion/jot-and-tittle",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — malformed body -> OpenAI-shaped 400
            return _error("Request body is not valid JSON.", 400)
        if not isinstance(body, dict) or not body.get("messages"):
            return _error("'messages' is a required field.", 400)

        chatbot = getattr(request.app.state, "chatbot", None)
        if chatbot is None:
            return _error("Chat engine is not initialized.", 503, "server_error")

        chat_req = to_chat_request(body)
        resp = await run_in_threadpool(chatbot.respond, chat_req)

        created = int(time.time())
        request_id = "chatcmpl-" + uuid.uuid4().hex
        prompt_text = last_user_message(body.get("messages"))

        if body.get("stream"):
            return _stream(resp, model_id=model_id, created=created, request_id=request_id)
        return JSONResponse(
            to_completion(
                resp,
                model_id=model_id,
                created=created,
                request_id=request_id,
                prompt_text=prompt_text,
            )
        )


def _stream(resp, *, model_id: str, created: int, request_id: str) -> StreamingResponse:
    """Minimal OpenAI SSE: role delta, one content delta, stop, [DONE]. jittle
    produces a single fully-gated answer, so streaming is a presentation wrapper."""
    content = render_content(resp)

    def _chunk(delta: dict, finish_reason=None) -> str:
        payload = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def gen():
        yield _chunk({"role": "assistant"})
        yield _chunk({"content": content})
        yield _chunk({}, finish_reason="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
