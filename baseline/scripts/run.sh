#!/usr/bin/env bash
# Run the baseline OpenAI-compatible endpoint locally.
#   http://localhost:8080/v1/chat/completions  and  /v1/models
# Config comes from baseline/.env (loaded by the app). Override PORT if needed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # baseline/
PY="${PYTHON:-$HERE/.venv/bin/python}"

if [ ! -x "$PY" ]; then
  echo "No interpreter at $PY. Create the venv and install deps first (see README), or set PYTHON=..." >&2
  exit 1
fi

cd "$HERE"
exec "$PY" -m uvicorn bible_baseline.openai_app:app --host 0.0.0.0 --port "${PORT:-8080}"
