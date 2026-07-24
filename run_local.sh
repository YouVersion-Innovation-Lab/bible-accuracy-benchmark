#!/usr/bin/env bash
# Run the Bible Accuracy Benchmark site locally on http://127.0.0.1:8100
#
# One FastAPI process serves both the JSON API (reading published runs from
# ./results) and the built React site from web/dist.
#
#   ./run_local.sh              # build the web app, then start the server
#   SKIP_BUILD=1 ./run_local.sh # skip the rebuild (faster; serves the last build)
#
# The backend auto-reloads on Python edits. Frontend edits need a rebuild
# (re-run without SKIP_BUILD) and a browser refresh.
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "==> Building web frontend (SKIP_BUILD=1 to skip)…"
  npm --prefix web run build
fi

echo "==> Serving on http://127.0.0.1:8100  (Ctrl-C to stop)"
export BENCH_LOCAL_DIR=results WEB_DIST=web/dist CACHE_TTL_SECONDS=0
exec .venv/bin/python -m uvicorn bible_bench.api.app:create_app --factory \
  --host 127.0.0.1 --port 8100 --reload --reload-dir src
