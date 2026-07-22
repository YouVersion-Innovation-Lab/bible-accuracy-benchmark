# Runbook

Operational guide for running the benchmark and publishing results.

## Prerequisites

- Python 3.12+, `pip install -e ".[api,dev]"`.
- A local `.env` (copy `.env.example`) with the Bible API access values
  (`YV_API_BASE_URL`, `YV_API_HEADERS`) — provided out-of-band; never committed.
- For adversarial runs: `HARNESS_*` (the pinned attacker model, e.g. an
  open-weight model via OpenRouter).
- To write to the live buckets: `gcloud auth application-default login` as a
  principal with `storage.objectAdmin` on the results bucket.

## Prefetch Bible text (recommended before local runs)

The topical track builds a whole-Bible reverse index per language, so a cold run
fetches a lot from the Core API. Fetch it once into a local cache and every run
reuses it:

```bash
export BENCH_CACHE_DIR=./bible-cache      # or pass --cache-dir to each command
bible-bench prefetch                      # all tracks: ~61 versions, ~72k chapters
# scope it if you like:
bible-bench prefetch --tracks topical --cache-dir ./bible-cache
```

Full prefetch is ~10 minutes and ~440 MB on disk, one time (idempotent/resumable
— re-running skips what's cached). Then point runs at the same cache:

```bash
bible-bench run … --cache-dir ./bible-cache      # or set BENCH_CACHE_DIR
```

The cache is a local operator convenience only — it is gitignored (`bible-cache/`),
never committed, and never used by the deployed website. With no cache dir set,
the client stays in-memory-only and writes nothing to disk.

## Run an evaluation

```bash
# Env var holds the key — never pass it as a bare CLI arg.
export TARGET_API_KEY=sk-...
bible-bench run \
  --base-url https://api.openai.com/v1 \
  --api-key-env TARGET_API_KEY \
  --model gpt-5.2 --label "GPT-5.2" \
  --tracks simple,topical,adversarial \
  --seed 2026-Q3 \
  --gcs-bucket biblelabs-bible-bench-results-beta
```

- `--tracks` selects any subset. `--scale <0..1>` shrinks per-tier counts for a
  quick pilot. `--dummy` runs without any model API (echo mode) for plumbing tests.
- `--local-dir DIR` writes to a local folder instead of GCS (development).
- Runs are **resumable**: re-run with the same `--run-id` to continue after an
  interruption (already-completed items are skipped).
- Generation and scoring are separate passes. Re-score without re-querying:
  `bible-bench score <run_id> --gcs-bucket …` (picks up a new `SCORING_VERSION`).

## Review, then publish

A run is not on the leaderboard until published. Review the run's `summary.json`
and a sample of `items*.jsonl` first, then:

```bash
bible-bench publish   <run_id> --gcs-bucket biblelabs-bible-bench-results-beta
bible-bench unpublish <run_id> --gcs-bucket biblelabs-bible-bench-results-beta
```

Publish/unpublish rebuilds `leaderboard.json`. The public site serves published
runs only; its cache TTL is 5 minutes.

## Deploy the site

Merge `main` → `beta` (staging) or `beta` → `release` (production). GitHub
Actions builds and deploys automatically (see `docs/GITHUB_CICD.md`). Current
beta URL:

```bash
gcloud run services describe bible-bench-web-beta \
  --project biblelabs-222720 --region us-central1 --format='value(status.url)'
```

## Refresh cadence (leaderboard)

Each leaderboard refresh draws a fresh simple-track sample from the public spec
with a new published seed (`--seed`), so models can't memorize a fixed list.
Run all models in a refresh with the **same seed** for a fair head-to-head, then
publish. Ad-hoc runs between refreshes should reuse the current refresh's seed to
stay comparable.

## Common issues

- **`ConfigError: Missing required env var(s)`** — the Bible API values aren't in
  the environment; check `.env`.
- **A run stalls on one language** — the Bible API politeness ceiling is 8
  concurrent calls; large versions (reverse-index build for topical) are the
  slowest step. Let it finish; it's cached in-memory for the rest of the run.
- **Leaderboard didn't update after publish** — the site caches for 5 minutes.
