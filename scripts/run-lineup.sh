#!/usr/bin/env bash
# Run the benchmark across the launch lineup, one model per provider, into a
# results store. Edit MODELS below to set exact model IDs and labels.
#
#   scripts/run-lineup.sh <run-version> [--gcs-bucket BUCKET | --local-dir DIR] [extra bible-bench args]
#
# Optional convenience for running the whole board at once. Export each
# provider's key in your shell first (a local .env is sourced if present):
#
#   export OPENAI_API_KEY=… ANTHROPIC_API_KEY=… GEMINI_API_KEY=… OPENROUTER_API_KEY=…
#
# A provider is skipped (with a note) if its key isn't set, so partial lineups
# just work. All models use the same run-version, so they share the verse sample
# and are comparable. Nothing is published — review each run, then
# `bible-bench publish --run-version <v> --model <id>` the ones you want live.
set -euo pipefail

RUN_VERSION="${1:?usage: run-lineup.sh <run-version> [store args...]}"; shift || true
STORE_ARGS=("$@")
[ ${#STORE_ARGS[@]} -eq 0 ] && STORE_ARGS=(--gcs-bucket biblelabs-bible-bench-results-beta)

# provider -> OpenAI-compatible base URL and the .env var holding its key
declare -A BASE=(
  [openai]="https://api.openai.com/v1"
  [anthropic]="https://api.anthropic.com/v1"
  [gemini]="https://generativelanguage.googleapis.com/v1beta/openai/"
  [openrouter]="https://openrouter.ai/api/v1"
  [xai]="https://api.x.ai/v1"
  [deepseek]="https://api.deepseek.com"
)
declare -A KEYVAR=(
  [openai]="OPENAI_API_KEY" [anthropic]="ANTHROPIC_API_KEY" [gemini]="GEMINI_API_KEY"
  [openrouter]="OPENROUTER_API_KEY" [xai]="XAI_API_KEY" [deepseek]="DEEPSEEK_API_KEY"
)

# Launch lineup: "provider|model-id|Display Label". Read off the run manifests of
# the last published board, so these are the IDs that actually answered.
# Set MODELS_FILTER to a comma-separated list of model ids to run a subset.
MODELS=(
  "openai|gpt-5.6-terra|GPT-5.6 Terra"
  "anthropic|claude-sonnet-5|Claude Sonnet 5"
  "gemini|gemini-3.6-flash|Gemini 3.6 Flash"
  "openrouter|x-ai/grok-4.5|Grok 4.5"
  "openrouter|deepseek/deepseek-v4-pro|DeepSeek V4 Pro"
  "openrouter|z-ai/glm-5.2|GLM-5.2"
  "openrouter|qwen/qwen3.7-max|Qwen3.7 Max"
  "openrouter|tencent/hy3|Tencent Hy3"
  "openrouter|minimax/minimax-m3|MiniMax M3"
)

set -a; [ -f .env ] && . ./.env; set +a

for entry in "${MODELS[@]}"; do
  IFS='|' read -r provider model label <<< "$entry"
  if [ -n "${MODELS_FILTER:-}" ] && [[ ",${MODELS_FILTER}," != *",${model},"* ]]; then
    continue
  fi
  keyvar="${KEYVAR[$provider]}"
  if [ -z "${!keyvar:-}" ]; then
    echo ">> skip ${label} (${keyvar} not set)"; continue
  fi
  echo ">> run  ${label}  (${provider}:${model})"
  bible-bench run \
    --base-url "${BASE[$provider]}" \
    --api-key-env "$keyvar" \
    --model "$model" --label "$label" \
    --run-version "$RUN_VERSION" \
    "${STORE_ARGS[@]}"
done

echo ">> Done. Review each run, then:"
echo ">>   bible-bench publish --run-version $RUN_VERSION --model <model-id> ${STORE_ARGS[*]}"
