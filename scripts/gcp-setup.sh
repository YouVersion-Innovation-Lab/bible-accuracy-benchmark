#!/usr/bin/env bash
# One-time GCP setup for keyless CI/CD to Cloud Run. Idempotent — safe to
# re-run. Run by an owner of the project. See docs/GITHUB_CICD.md.
set -euo pipefail

PROJECT=biblelabs-222720
PROJNUM=424554024955
REGION=us-central1
REPO=YouVersion-Innovation-Lab/bible-accuracy-benchmark
CI_SA=bible-bench-ci-deploy@${PROJECT}.iam.gserviceaccount.com

echo ">> Enabling APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com --project "$PROJECT"

echo ">> Artifact Registry repo"
gcloud artifacts repositories create bible-bench \
  --project "$PROJECT" --location "$REGION" --repository-format docker \
  --description "Bible Accuracy Benchmark images" 2>/dev/null || true

echo ">> Results buckets"
for ENV in beta release; do
  gcloud storage buckets create "gs://biblelabs-bible-bench-results-${ENV}" \
    --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access 2>/dev/null || true
done

echo ">> CI deploy service account + roles"
gcloud iam service-accounts create bible-bench-ci-deploy \
  --project "$PROJECT" --display-name "Bible Bench CI deploy" 2>/dev/null || true
# SA creation is eventually consistent; wait so the bindings below don't race.
for i in $(seq 1 10); do
  gcloud iam service-accounts describe "$CI_SA" --project "$PROJECT" >/dev/null 2>&1 && break
  sleep 2
done
for ROLE in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.writer roles/storage.admin roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${CI_SA}" --role "$ROLE" --condition=None >/dev/null
done

# Cloud Build runs as the Compute Engine default SA; the CI SA must be allowed
# to act as it to submit builds.
BUILD_SA=${PROJNUM}-compute@developer.gserviceaccount.com
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" \
  --project "$PROJECT" --member "serviceAccount:${CI_SA}" \
  --role roles/iam.serviceAccountUser >/dev/null

echo ">> Runtime service accounts + roles"
for ENV in beta release; do
  RT=bible-bench-web-${ENV}@${PROJECT}.iam.gserviceaccount.com
  gcloud iam service-accounts create bible-bench-web-${ENV} \
    --project "$PROJECT" --display-name "Bible Bench web ${ENV}" 2>/dev/null || true
  gcloud storage buckets add-iam-policy-binding \
    "gs://biblelabs-bible-bench-results-${ENV}" \
    --member "serviceAccount:${RT}" --role roles/storage.objectViewer >/dev/null
  gcloud iam service-accounts add-iam-policy-binding "$RT" \
    --project "$PROJECT" --member "serviceAccount:${CI_SA}" \
    --role roles/iam.serviceAccountUser >/dev/null
done

echo ">> Workload Identity Federation provider (new, repo-pinned)"
gcloud iam workload-identity-pools providers create-oidc bible-bench \
  --project "$PROJECT" --location global --workload-identity-pool github-pool \
  --display-name "bible-accuracy-benchmark" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition "assertion.repository=='${REPO}' && (assertion.ref=='refs/heads/beta' || assertion.ref=='refs/heads/release')" \
  2>/dev/null || echo "   (provider already exists)"

gcloud iam service-accounts add-iam-policy-binding "$CI_SA" \
  --project "$PROJECT" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJNUM}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${REPO}" >/dev/null

echo ">> Done."
