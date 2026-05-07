#!/usr/bin/env bash
# =============================================================================
# run_stage2.sh — Generic Stage-2 runner used by the per-document wrappers.
#
# Required environment variables (defaults shown):
#   DOC_TYPE     purchase_order
#   MD_PATH      data/sample/merged_purchase_order.md   (relative to Pipeline/)
#   JSON_PATH    data/sample/merged_pages.json          (relative to Pipeline/)
#   OUTPUT_PATH  ""  (empty -> let run.py auto-resolve)
#
# Optional:
#   OLLAMA_MODEL  qwen2.5:32b
#   OLLAMA_URL    http://localhost:11434
#   EXTRA_ARGS    extra flags forwarded to run.py (e.g. "--dry-run", "--inspect")
#   VENV_DIR      .venv  (project-root virtual env to auto-activate)
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIPELINE_DIR="$ROOT_DIR/Pipeline"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

DOC_TYPE="${DOC_TYPE:-purchase_order}"
MD_PATH="${MD_PATH:-data/sample/merged_purchase_order.md}"
JSON_PATH="${JSON_PATH:-data/sample/merged_pages.json}"
OUTPUT_PATH="${OUTPUT_PATH:-}"
MODEL="${OLLAMA_MODEL:-qwen2.5:32b}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

if [ ! -d "$PIPELINE_DIR" ]; then
  echo "[ERROR] Pipeline directory not found: $PIPELINE_DIR"
  exit 1
fi

if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1090,SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "[WARN] No virtual env at $VENV_DIR. Using system Python."
  echo "       Run ./scripts/setup_env.sh first if extraction fails."
fi

# Resolve input paths relative to Pipeline/ before checking existence.
abspath() {
  if [[ "$1" = /* ]]; then echo "$1"; else echo "$PIPELINE_DIR/$1"; fi
}
MD_FULL="$(abspath "$MD_PATH")"
JSON_FULL="$(abspath "$JSON_PATH")"

if [ ! -f "$MD_FULL" ]; then
  echo "[ERROR] Markdown file not found: $MD_FULL"
  echo "        Set MD_PATH to a valid file (absolute or relative to Pipeline/)."
  exit 1
fi
if [ ! -f "$JSON_FULL" ]; then
  echo "[ERROR] JSON file not found: $JSON_FULL"
  echo "        Set JSON_PATH to a valid file (absolute or relative to Pipeline/)."
  exit 1
fi

# Skip Ollama check on dry runs / inspections.
SKIP_OLLAMA=0
if [[ " $EXTRA_ARGS " == *" --dry-run "* ]] || [[ " $EXTRA_ARGS " == *" --inspect "* ]] || [[ " $EXTRA_ARGS " == *" --list "* ]]; then
  SKIP_OLLAMA=1
fi

if [ "$SKIP_OLLAMA" = "0" ]; then
  OLLAMA_URL="$OLLAMA_URL" OLLAMA_MODEL="$MODEL" "$ROOT_DIR/scripts/check_ollama.sh"
fi

cd "$PIPELINE_DIR"
mkdir -p output logs

CMD=(python run.py
     --doc-type "$DOC_TYPE"
     --md       "$MD_PATH"
     --json     "$JSON_PATH"
     --model    "$MODEL"
     --ollama-url "$OLLAMA_URL")

if [ -n "$OUTPUT_PATH" ]; then
  CMD+=(--output "$OUTPUT_PATH")
fi

# shellcheck disable=SC2206
EXTRA_ARRAY=($EXTRA_ARGS)
if [ "${#EXTRA_ARRAY[@]}" -gt 0 ]; then
  CMD+=("${EXTRA_ARRAY[@]}")
fi

echo "[RUN] cd $PIPELINE_DIR"
echo "[RUN] ${CMD[*]}"
"${CMD[@]}"
