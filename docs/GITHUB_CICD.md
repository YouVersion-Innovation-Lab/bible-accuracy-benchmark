# GitHub CI/CD → Cloud Run (keyless)

Deployment mirrors the `patton` repo: GitHub Actions authenticates to GCP with
keyless Workload Identity Federation (no service-account keys, no GitHub
secrets), then builds with Cloud Build and deploys to Cloud Run.

- Project: `biblelabs-222720`, region `us-central1`
- Branch model: `main` (dev, no deploy) → `beta` (→ `bible-bench-web-beta`) →
  `release` (→ `bible-bench-web-release`)
- One image (`Dockerfile`) serves `/api/*` + the built React SPA.
- Published results live in GCS: `gs://biblelabs-bible-bench-results-{beta,release}`.

## One-time GCP setup

Run once by an owner of `biblelabs-222720` (script is idempotent — safe to
re-run). Also available as `scripts/gcp-setup.sh`.

```bash
PROJECT=biblelabs-222720
PROJNUM=424554024955
REGION=us-central1
REPO=YouVersion-Innovation-Lab/bible-accuracy-benchmark
CI_SA=bible-bench-ci-deploy@${PROJECT}.iam.gserviceaccount.com

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com --project "$PROJECT"

# Artifact Registry (Container Registry / gcr.io is shut down)
gcloud artifacts repositories create bible-bench \
  --project "$PROJECT" --location "$REGION" --repository-format docker \
  --description "Bible Accuracy Benchmark images" || true

# Results buckets (uniform bucket-level access; public site reads only)
for ENV in beta release; do
  gcloud storage buckets create "gs://biblelabs-bible-bench-results-${ENV}" \
    --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access || true
done

# CI deploy service account
gcloud iam service-accounts create bible-bench-ci-deploy \
  --project "$PROJECT" --display-name "Bible Bench CI deploy" || true
for ROLE in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.writer roles/storage.admin roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${CI_SA}" --role "$ROLE" --condition=None
done

# Cloud Build runs as the Compute Engine default SA; the CI SA must act as it.
gcloud iam service-accounts add-iam-policy-binding \
  "${PROJNUM}-compute@developer.gserviceaccount.com" \
  --project "$PROJECT" --member "serviceAccount:${CI_SA}" \
  --role roles/iam.serviceAccountUser

# Runtime service accounts (least privilege: read only their results bucket)
for ENV in beta release; do
  RT=bible-bench-web-${ENV}@${PROJECT}.iam.gserviceaccount.com
  gcloud iam service-accounts create bible-bench-web-${ENV} \
    --project "$PROJECT" --display-name "Bible Bench web ${ENV}" || true
  gcloud storage buckets add-iam-policy-binding \
    "gs://biblelabs-bible-bench-results-${ENV}" \
    --member "serviceAccount:${RT}" --role roles/storage.objectViewer
  # CI SA must be able to deploy Cloud Run as the runtime SA
  gcloud iam service-accounts add-iam-policy-binding "$RT" \
    --project "$PROJECT" --member "serviceAccount:${CI_SA}" \
    --role roles/iam.serviceAccountUser
done

# Workload Identity Federation: a NEW provider in the existing github-pool,
# pinned to this repo + the deploy branches. (Do NOT widen patton's provider.)
gcloud iam workload-identity-pools providers create-oidc bible-bench \
  --project "$PROJECT" --location global --workload-identity-pool github-pool \
  --display-name "bible-accuracy-benchmark" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition "assertion.repository=='${REPO}' && (assertion.ref=='refs/heads/beta' || assertion.ref=='refs/heads/release')"

gcloud iam service-accounts add-iam-policy-binding "$CI_SA" \
  --project "$PROJECT" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJNUM}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${REPO}"
```

## GitHub setup

- Create GitHub Environments `beta` and `release` (Settings → Environments).
  Optionally require a reviewer on `release`.
- Protect the `beta` and `release` branches so only maintainers can push/merge.
- No GitHub Actions secrets are needed.

## Deploy

Merge `main` → `beta` to ship to the beta site; merge `beta` → `release` to ship
to production. `scripts/ci/gh-deploy.sh <env>` runs the build + deploy; the
public URL is printed at the end and via
`gcloud run services describe bible-bench-web-<env> --format='value(status.url)'`.

## Publishing results

The eval CLI writes runs to the environment's results bucket and gates the
leaderboard:

```bash
bible-bench run  --base-url … --api-key-env TARGET_API_KEY --model gpt-5.2 --label "GPT-5.2" \
  --run-version v0.1 --gcs-bucket biblelabs-bible-bench-results-beta
bible-bench publish --run-version v0.1 --model gpt-5.2 --gcs-bucket biblelabs-bible-bench-results-beta
```
