#!/usr/bin/env bash
# =============================================================================
# run_full_pipeline.sh — End-to-end: PDF -> OCR -> merge -> Stage 2 -> JSON.
#
# Required:
#   PDF_PATH=/abs/path/to/your.pdf
#   DOC_TYPE=purchase_order | shipping_bill | <registered type>
#
# Optional:
#   OUT_DIR              Md_JSON_Extraction/outputs        (Stage 1 output root)
#   OUTPUT_PATH          Pipeline/output/<doc>_result.json (Stage 2 final JSON)
#   OLLAMA_MODEL         qwen2.5:32b
#   OLLAMA_URL           http://localhost:11434
#   GLMOCR_OCR_API_HOST  localhost
#   GLMOCR_OCR_API_PORT  8080
#   SKIP_OCR=1           skip Stage 1 (use existing OUT_DIR/<doc>/ contents)
#   SKIP_MERGE=1         skip the merge step (use existing merged.* files)
#
# Prerequisites for full run:
#   - Python 3.11+ env (run setup_env.sh in a Py 3.11 venv)
#   - vLLM serving GLM-OCR on $GLMOCR_OCR_API_HOST:$GLMOCR_OCR_API_PORT
#   - Ollama serving qwen2.5:32b on $OLLAMA_URL
#
# Examples:
#   PDF_PATH=Md_JSON_Extraction/examples/source/MI-8937-0906\ Purchase\ Order.pdf \
#     DOC_TYPE=purchase_order ./scripts/run_full_pipeline.sh
#
#   # Skip Stage 1 (already OCR'd elsewhere — point at the merged outputs):
#   SKIP_OCR=1 SKIP_MERGE=1 \
#     MD_PATH=/abs/path/merged.md JSON_PATH=/abs/path/merged.pages.json \
#     DOC_TYPE=purchase_order ./scripts/run_full_pipeline.sh
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DIR="$ROOT_DIR/scripts"

PDF_PATH="${PDF_PATH:-}"
DOC_TYPE="${DOC_TYPE:-}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/Md_JSON_Extraction/outputs}"
OUTPUT_PATH="${OUTPUT_PATH:-}"
SKIP_OCR="${SKIP_OCR:-0}"
SKIP_MERGE="${SKIP_MERGE:-0}"

if [ -z "$DOC_TYPE" ]; then
  echo "[ERROR] DOC_TYPE is required (e.g. purchase_order or shipping_bill)."
  exit 1
fi

# --- Stage 1: OCR ---------------------------------------------------------- #
DOC_DIR=""
if [ "$SKIP_OCR" != "1" ]; then
  if [ -z "$PDF_PATH" ]; then
    echo "[ERROR] PDF_PATH is required (set SKIP_OCR=1 to skip Stage 1)."
    exit 1
  fi
  if [ ! -f "$PDF_PATH" ]; then
    echo "[ERROR] PDF not found: $PDF_PATH"
    exit 1
  fi

  echo "[FULL] Stage 1: OCR  ($PDF_PATH)"
  PDF_PATH="$PDF_PATH" OUT_DIR="$OUT_DIR" "$SCRIPTS_DIR/run_glmocr_pdf.sh"

  PDF_STEM="$(basename "$PDF_PATH" .pdf)"
  DOC_DIR="$OUT_DIR/$PDF_STEM"
  if [ ! -d "$DOC_DIR" ]; then
    # Fall back: if the OCR script created a different folder name, take the
    # newest folder in OUT_DIR.
    DOC_DIR="$(ls -1dt "$OUT_DIR"/*/ 2>/dev/null | head -1 | sed 's:/$::')"
  fi
  echo "[FULL] Stage 1 complete -> $DOC_DIR"
fi

# --- Merge ----------------------------------------------------------------- #
MD_PATH="${MD_PATH:-}"
JSON_PATH="${JSON_PATH:-}"

if [ "$SKIP_MERGE" != "1" ]; then
  if [ -z "$DOC_DIR" ] && [ -n "${DOC_DIR_OVERRIDE:-}" ]; then
    DOC_DIR="$DOC_DIR_OVERRIDE"
  fi
  if [ -z "$DOC_DIR" ]; then
    echo "[ERROR] No DOC_DIR resolved. Set SKIP_OCR=1 + DOC_DIR=... to merge an existing folder,"
    echo "        or run Stage 1 first."
    exit 1
  fi

  echo "[FULL] Merge:  $DOC_DIR"
  DOC_DIR="$DOC_DIR" "$SCRIPTS_DIR/merge_glmocr_outputs.sh"

  MD_PATH="$DOC_DIR/merged_output.md"
  JSON_PATH="$DOC_DIR/merged.pages.json"
fi

# --- Stage 2: structured extraction ---------------------------------------- #
if [ -z "$MD_PATH" ] || [ -z "$JSON_PATH" ]; then
  echo "[ERROR] MD_PATH and JSON_PATH must be set (or run merge step first)."
  exit 1
fi
if [ ! -f "$MD_PATH" ]; then
  echo "[ERROR] Markdown not found: $MD_PATH"
  exit 1
fi
if [ ! -f "$JSON_PATH" ]; then
  echo "[ERROR] JSON not found: $JSON_PATH"
  exit 1
fi

if [ -z "$OUTPUT_PATH" ]; then
  OUTPUT_PATH="output/${DOC_TYPE}_result.json"
fi

echo "[FULL] Stage 2: extract  ($DOC_TYPE)"
DOC_TYPE="$DOC_TYPE" \
MD_PATH="$MD_PATH" \
JSON_PATH="$JSON_PATH" \
OUTPUT_PATH="$OUTPUT_PATH" \
  "$SCRIPTS_DIR/run_stage2.sh"

echo
echo "[FULL] Done. Final structured JSON:"
echo "       $ROOT_DIR/Pipeline/$OUTPUT_PATH"
echo
echo "[NEXT] Launch the eval frontend to compare against ground truth:"
echo "       ./scripts/run_frontend.sh"
