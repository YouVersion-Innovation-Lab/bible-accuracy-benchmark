# Baseline — an OpenAI-compatible endpoint over Jot & Tittle

This is a small, **independent** service that exposes YouVersion's
[`jittle`](https://github.com/youversion/jittle) ("Jot & Tittle") Scripture-quotation
accuracy harness through a standard **OpenAI Chat Completions** API. Any
OpenAI-compatible client can talk to it, including the Bible Accuracy Benchmark.

`jittle`'s `jotchat` is a Claude-powered study companion whose citation loop runs
every generated verse back through a deterministic verification engine — misquotes
are corrected from the corpus and fabrications are dropped — so text it presents as
Scripture is verbatim to the cited translation.

## Independence (on purpose)

This folder is a self-contained system. It:

- lives entirely under `baseline/`, with `jittle` vendored as a git submodule at
  `vendor/jittle`;
- is **never built into or deployed with the benchmark website** (the website image
  copies only `src/ config/ dataset/ web/dist`; the repo root `.dockerignore`
  excludes `baseline/`);
- **knows nothing about the evaluation** — `bible_baseline` imports only `jot*`
  packages; it contains no benchmark imports, prompt formats, version lists, or
  scoring logic. A test asserts `bible_bench` is not importable from here.

The wrapper is intentionally **pure protocol glue**: it maps an OpenAI request to a
`jittle` `ChatRequest`, calls `Chatbot.respond`, and maps the `ChatResponse` back.
All Bible logic — translation selection, routing, generation, verification — lives
in `jittle`. The point is simply to test `jittle`'s system.

## Layout

```
baseline/
  src/bible_baseline/
    openai_app.py     # ASGI app: create_chat_app(llm=...) + OpenAI routes
    routes.py         # GET /v1/models, POST /v1/chat/completions (+ SSE)
    adapter.py        # OpenAI <-> jittle ChatRequest/ChatResponse mapping
    llm_client.py     # OpenAICompatLLMClient — jittle LLMClient over any endpoint
  scripts/build_data.sh   # build the public-domain corpus (one-time)
  scripts/run.sh          # run the server locally
  vendor/jittle/          # git submodule
  tests/                  # offline tests (no key/corpus needed)
```

## Setup (local only)

```bash
# from the repo root
git submodule update --init baseline/vendor/jittle

cd baseline
python3.12 -m venv .venv
.venv/bin/pip install -e vendor/jittle      # jittle + its deps
.venv/bin/pip install -e .                  # this wrapper (fastapi, openai, ...)

# Build the public-domain corpus (BSB/KJV/WEB/ASV). No keys, no cost.
bash scripts/build_data.sh

# Configure the service
cp .env.example .env         # then edit .env (see below)
```

### `.env`

Copy `.env.example` to `.env` and set:

- `BASELINE_LLM_BASE_URL` / `BASELINE_LLM_API_KEY` / `BASELINE_LLM_MODEL` — the
  OpenAI-compatible endpoint jittle uses to generate topical (Tier B/C) answers.
  Default is Anthropic (`https://api.anthropic.com/v1`, `claude-sonnet-5`). Quote
  accuracy is guaranteed by the verification engine regardless of the model.
- `JOT_CORPUS` — absolute path to the `corpus.db` built above.
- `JOT_YVP_KEY` — *optional* YouVersion **Platform** key for licensed versions
  (NIV/NLT/ESV/...). Without it the service is public-domain only (BSB/KJV/WEB/ASV)
  and a request for an unreachable version falls back to BSB (jittle marks the
  substitution — it never silently swaps).

## Run

```bash
bash scripts/run.sh            # serves on :8080 (override with PORT=...)
```

```bash
curl -s localhost:8080/v1/models | jq

curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' -d '{
  "model": "jot-tittle",
  "messages": [{"role": "user", "content": "Quote John 3:16 from the KJV."}]
}' | jq -r '.choices[0].message.content'

# A reference that does not exist — jittle declines rather than inventing a verse:
curl -s localhost:8080/v1/chat/completions -H 'content-type: application/json' -d '{
  "model": "jot-tittle",
  "messages": [{"role": "user", "content": "Quote Psalm 180:1 from the KJV."}]
}' | jq -r '.choices[0].message.content'
```

## Tests

Offline, no key or corpus needed (a real `jot` engine over jittle's fixture mini-corpus
plus jittle's `StubLLMClient`, injected into the app factory):

```bash
cd baseline && .venv/bin/pytest -q
```

## Pointing the benchmark at it

From a separate shell, with the benchmark installed:

```bash
bible-bench run \
  --base-url http://localhost:8080/v1 \
  --api-key-env DUMMY \
  --model jot-tittle \
  --label "Jot & Tittle baseline"
```

## Notes

- `usage` token counts in responses are an approximation (~chars/4); jittle does not
  surface token usage. jittle's engine version and generation model ride on
  `system_fingerprint` for auditability.
- jittle enforces a 32 KB request cap and an optional `JOT_ORG_TOKEN` (unset here).
- Updating jittle: `git -C vendor/jittle pull`, then commit the submodule bump.
