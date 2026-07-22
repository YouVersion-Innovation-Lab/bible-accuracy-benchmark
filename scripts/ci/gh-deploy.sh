#!/usr/bin/env bash
# Build + deploy the public site to Cloud Run for one environment.
#
#   gh-deploy.sh beta      -> bible-bench-web-beta
#   gh-deploy.sh release   -> bible-bench-web-release
#
# Auth is provided by the caller (GitHub Actions via Workload Identity
# Federation, or a logged-in gcloud locally). No secrets are read here.
set -euo pipefail

ENV="${1:?usage: gh-deploy.sh <beta|release>}"
case "$ENV" in
  beta|release) ;;
  *) echo "environment must be 'beta' or 'release'"; exit 2 ;;
esac

PROJECT="biblelabs-222720"
REGION="us-central1"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/bible-bench/app"
SHA="$(git rev-parse HEAD)"
SERVICE="bible-bench-web-${ENV}"
BUCKET="biblelabs-bible-bench-results-${ENV}"
RUNTIME_SA="bible-bench-web-${ENV}@${PROJECT}.iam.gserviceaccount.com"

echo ">> Building ${IMAGE}:${SHA}"
gcloud builds submit --project "$PROJECT" --region "$REGION" \
  --config cloudbuild.yaml \
  --substitutions "COMMIT_SHA=${SHA},_IMAGE=${IMAGE}" .

echo ">> Deploying ${SERVICE}"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --image "${IMAGE}:${SHA}" \
  --service-account "$RUNTIME_SA" \
  --set-env-vars "BENCH_ENV=${ENV},BENCH_RESULTS_BUCKET=${BUCKET},WEB_DIST=/app/web/dist,CACHE_TTL_SECONDS=300" \
  --allow-unauthenticated \
  --port 8080 --memory 512Mi --cpu 1 \
  --min-instances 0 --max-instances 5 --concurrency 80 \
  --labels "app=bible-bench,env=${ENV},sha=${SHA:0:12}"

echo ">> Deployed ${SERVICE} at $(gcloud run services describe "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
