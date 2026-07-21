# Architecture

## Components

- **Evaluation engine** (`src/bible_bench/`) — Python package. Fetches ground-truth verse
  text from YouVersion's Bible API at runtime (in-memory cache only; never written to
  disk), runs the three benchmark tracks against any OpenAI-compatible endpoint, and
  scores results deterministically.
- **CLI runner** (`bible-bench`) — runs evaluations locally with live progress and writes
  run artifacts (manifest, responses, scored items, summary, transcripts) to the results
  store. `bible-bench publish <run_id>` gates what appears on the public leaderboard.
- **Results store** — a GCS bucket of JSON artifacts per environment
  (`biblelabs-bible-bench-results-{beta,release}`). Results are plain, auditable files.
- **Public website** (`web/` + `src/bible_bench/api/`) — a single Cloud Run service per
  environment (`bible-bench-web-{beta,release}`): FastAPI serving `/api/public/*` and the
  built React SPA from one container. Read-only access to the results bucket.

## Environments and deployment

Branch model: `main` (development, no deploy) → `beta` (auto-deploys `*-beta`) →
`release` (auto-deploys `*-release`). GitHub Actions authenticates to GCP project
`biblelabs-222720` via keyless Workload Identity Federation; see `docs/GITHUB_CICD.md`.

## Secrets

This is a public repository. No secrets are committed — Bible API header values, session
material, and any API keys live only in local `.env` files (gitignored) and GCP Secret
Manager. CI runs no workflows that require secrets.
