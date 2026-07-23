#!/usr/bin/env bash
# Build jittle's public-domain corpus (BSB, KJV, WEB, ASV) for local runs.
#
# Downloads public-domain USFX from eBible.org and builds
# vendor/jittle/data/corpus.db. No API keys, no cost. Run once (re-run to refresh).
# Licensed versions (NIV/NLT/ESV/...) are NOT baked — they resolve live via the
# YouVersion Platform overlay when JOT_YVP_KEY is set (see baseline/.env).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # baseline/
JITTLE="$HERE/vendor/jittle"
PY="${PYTHON:-$HERE/.venv/bin/python}"

if [ ! -x "$PY" ]; then
  echo "No interpreter at $PY. Create the venv and install deps first (see README), or set PYTHON=..." >&2
  exit 1
fi

cd "$JITTLE"
echo "Fetching public-domain sources into $JITTLE/data/sources ..."
"$PY" scripts/fetch_corpus.py --dest data
echo "Building corpus.db ..."
"$PY" -m jot.corpus.build --sources data/sources --out data/corpus.db

echo
echo "Built: $JITTLE/data/corpus.db"
echo "Point JOT_CORPUS at that absolute path in baseline/.env."
