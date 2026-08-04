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

- A run is identified by **(`--model` id, `--run-version`)** — no run-id. `--label` is a required display name, stored in the result for the website. The
  result is stored at `runs/{run-version}--{model-slug}/`; **re-running the same
  model + version overwrites it** (a fresh run, not a resume).
- All three dimensions (simple, hallucination, and the creed pair) always run — there is
  no track selection. The adversarial track is paused this round (code retained,
  not wired into a run).
- `--run-version` also **seeds the verse sample**, so every model at a given
  version is tested on the identical set — directly comparable.
- `--scale <0..1>` shrinks per-tier counts for a quick pilot. `--dummy` runs
  without any model API (echo mode) for plumbing tests. `--local-dir DIR` writes
  to a local folder instead of GCS.
- Generation and scoring are separate passes, and there are exactly two operations:
  `run` does everything including the model calls, `score` does everything except
  them. Re-score without re-querying:
  `bible-bench score --run-version v0.5 --model gpt-5.6-terra --gcs-bucket …`
  (~5 minutes per run). There is no lighter path on purpose — a shortcut that
  re-aggregates without re-scoring is how some records in a run end up older than
  others while every figure is presented as one measurement.

## Review, then publish

A run is not on the leaderboard until published. Review the run's `summary.json`
and a sample of `items*.jsonl` first, then (identify the run by version + model):

```bash
bible-bench publish   --run-version v0.1 --model gpt-5.2 --gcs-bucket biblelabs-bible-bench-results-beta
bible-bench unpublish --run-version v0.1 --model gpt-5.2 --gcs-bucket biblelabs-bible-bench-results-beta
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
  concurrent calls; large versions (whole-Bible reverse-index build) are the
  slowest step. Let it finish; it's cached in-memory for the rest of the run.
- **Leaderboard didn't update after publish** — the site caches for 5 minutes.

## Fast runs

A fast pass runs ~10% of the items and finishes in minutes rather than hours.
Use it to get every model on the board quickly, or to check a change end to end
before spending a full sweep.

```bash
bible-bench run --base-url https://openrouter.ai/api/v1 \
  --model x-ai/grok-4.5 --label "Grok 4.5" \
  --api-key-env OPENROUTER_API_KEY --fast
bible-bench publish --model x-ai/grok-4.5 --run-version v0.5-fast
```

Two properties make the results usable rather than merely quick:

* **Its own generation.** A fast run records `run_version = v0.5-fast`, so it
  never mixes with full results — the board shows one generation at a time and
  offers both in its selector.
* **The same questions.** The item draw is seeded by the plain version, so a fast
  run's references are a strict *subset* of the full run's. A fast score and a
  full score therefore disagree only by coverage, not by sample.

Items are thinned **within each language**, never as a prefix of the list. The
item lists are built language by language, so a naive `items[:10%]` would cover
English and Spanish and nothing else — and since track scores macro-average over
languages, that would report a two-language result as eleven. A fast run keeps
all 11 languages and all 18 translations; it asks fewer questions of each.

Roughly, per model: ~260 Quoting Accuracy + ~35
Hallucination ≈ 415 calls, against ~4,240 for a full run.

`--scale` still works and overrides what `--fast` would choose, e.g.
`--fast --scale 0.25` for a bigger fast pass. `score` addresses a
fast run with `--run-version v0.5-fast`.
