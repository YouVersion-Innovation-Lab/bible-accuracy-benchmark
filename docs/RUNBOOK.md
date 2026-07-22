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

## Prefetch Bible text (required before any run)

Evaluations run **offline against the local cache** — `run` and `score` never
fetch from the Core API and have no in-memory fallback. If the cache is missing
or empty they **fail fast** (exit 2) telling you to prefetch. Fetch it once and
every run reuses it:

```bash
export BENCH_CACHE_DIR=./bible-cache      # or pass --cache-dir to each command
bible-bench prefetch                      # ~61 versions, ~72k chapters
```

Full prefetch is ~10 minutes and ~440 MB on disk, one time (idempotent/resumable
— re-running skips what's cached). Then point runs at the same cache:

```bash
bible-bench run … --cache-dir ./bible-cache      # or set BENCH_CACHE_DIR
```

The cache is a local operator convenience only — it is gitignored (`bible-cache/`),
never committed, and never used by the deployed website. (The client still
supports an in-memory-only mode with no cache dir — used by tests and the
`prefetch`/`build-dataset` tools — but `run` and `score` require the cache.)

## Run an evaluation

```bash
# Env var holds the key — never pass it as a bare CLI arg.
export TARGET_API_KEY=sk-...
bible-bench run \
  --base-url https://api.openai.com/v1 \
  --api-key-env TARGET_API_KEY \
  --model gpt-5.2 --label "GPT-5.2" \
  --run-version v0.1 \
  --gcs-bucket biblelabs-bible-bench-results-beta
```

- A run is identified by **(model label, `--run-version`)** — no run-id. The
  result is stored at `runs/{run-version}--{model-slug}/`; **re-running the same
  model + version overwrites it** (a fresh run, not a resume).
- All three tracks (simple, topical, adversarial) always run — there is no track
  selection.
- `--run-version` also **seeds the verse sample**, so every model at a given
  version is tested on the identical set — directly comparable.
- `--scale <0..1>` shrinks per-tier counts for a quick pilot. `--dummy` runs
  without any model API (echo mode) for plumbing tests. `--local-dir DIR` writes
  to a local folder instead of GCS.
- Generation and scoring are separate passes. Re-score without re-querying:
  `bible-bench score --run-version v0.1 --label "GPT-5.2" --gcs-bucket …`
  (picks up a new `SCORING_VERSION`).

## Review, then publish

A run is not on the leaderboard until published. Review the run's `summary.json`
and a sample of `items*.jsonl` first, then (identify the run by version + label):

```bash
bible-bench publish   --run-version v0.1 --label "GPT-5.2" --gcs-bucket biblelabs-bible-bench-results-beta
bible-bench unpublish --run-version v0.1 --label "GPT-5.2" --gcs-bucket biblelabs-bible-bench-results-beta
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

Each leaderboard refresh uses a new `--run-version`, which draws a fresh
simple-track sample from the public spec (the version string seeds the sample),
so models can't memorize a fixed list. Run all models in a refresh with the
**same `--run-version`** for a fair head-to-head, then publish. Bump the version
(e.g. `v0.1` → `v0.2`) for the next refresh.

## Common issues

- **`ConfigError: Missing required env var(s)`** — the Bible API values aren't in
  the environment; check `.env`.
- **A run stalls on one language** — the Bible API politeness ceiling is 8
  concurrent calls; large versions (reverse-index build for topical) are the
  slowest step. Let it finish; it's cached in-memory for the rest of the run.
- **Leaderboard didn't update after publish** — the site caches for 5 minutes.
