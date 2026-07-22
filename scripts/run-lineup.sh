#!/usr/bin/env bash
# Run the benchmark across the launch lineup, one model per provider, into a
# results store. Edit MODELS below to set exact model IDs and labels.
#
#   scripts/run-lineup.sh <seed> [--gcs-bucket BUCKET | --local-dir DIR] [extra bible-bench args]
#
# Reads keys from .env (see .env.example). A provider is skipped (with a note)
# if its key is not set, so partial lineups just work. Nothing is published —
# review each run, then `bible-bench publish <run_id>` the ones you want live.
set -euo pipefail

SEED="${1:?usage: run-lineup.sh <seed> [store args...]}"; shift || true
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

# Launch lineup: "provider|model-id|Display Label". Confirm exact model IDs.
MODELS=(
  "openai|gpt-5.2|GPT-5.2"
  "anthropic|claude-opus-4-8|Claude Opus 4.8"
  "gemini|gemini-3-pro|Gemini 3 Pro"
  "openrouter|meta-llama/llama-3.3-70b-instruct|Llama 3.3 70B"
  "openrouter|deepseek/deepseek-chat-v3.1|DeepSeek V3.1"
  "xai|grok-4|Grok 4"
)

set -a; [ -f .env ] && . ./.env; set +a

for entry in "${MODELS[@]}"; do
  IFS='|' read -r provider model label <<< "$entry"
  keyvar="${KEYVAR[$provider]}"
  if [ -z "${!keyvar:-}" ]; then
    echo ">> skip ${label} (${keyvar} not set)"; continue
  fi
  echo ">> run  ${label}  (${provider}:${model})"
  bible-bench run \
    --base-url "${BASE[$provider]}" \
    --api-key-env "$keyvar" \
    --model "$model" --label "$label" \
    --tracks simple,topical,adversarial \
    --seed "$SEED" \
    "${STORE_ARGS[@]}"
done

echo ">> Done. Review each run, then: bible-bench publish <run_id> ${STORE_ARGS[*]}"
