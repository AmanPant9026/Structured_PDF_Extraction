#!/usr/bin/env bash
# =============================================================================
# merge_glmocr_outputs.sh — Merge per-page GLM-OCR outputs into the two files
# Stage 2 needs:  merged_output.md  +  merged.pages.json
#
# Required:
#   DOC_DIR=Md_JSON_Extraction/outputs/<doc_folder>
#
# Optional:
#   MERGED_MD_OUT=<path>   override default ($DOC_DIR/merged_output.md)
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OCR_DIR="$ROOT_DIR/Md_JSON_Extraction"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
DOC_DIR="${DOC_DIR:-}"
MERGED_MD_OUT="${MERGED_MD_OUT:-}"

if [ -z "$DOC_DIR" ]; then
  echo "[ERROR] Provide DOC_DIR pointing to one GLM-OCR document output folder."
  echo "Example: DOC_DIR=Md_JSON_Extraction/outputs/my_pdf ./scripts/merge_glmocr_outputs.sh"
  exit 1
fi
if [ ! -d "$DOC_DIR" ]; then
  echo "[ERROR] DOC_DIR does not exist: $DOC_DIR"
  exit 1
fi

if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1090,SC1091
  source "$VENV_DIR/bin/activate"
fi

cd "$OCR_DIR"

if [ -z "$MERGED_MD_OUT" ]; then
  MERGED_MD_OUT="$DOC_DIR/merged_output.md"
fi

echo "[MERGE] Markdown -> $MERGED_MD_OUT"
python merge_md.py --doc_dir "$DOC_DIR" --output_file "$MERGED_MD_OUT"

# merge_all_docs.py is now path-independent — it accepts --doc-dir directly.
echo "[MERGE] JSON -> $DOC_DIR/merged.pages.json"
python merge_all_docs.py --doc-dir "$DOC_DIR"

echo
echo "[MERGE] Done. Pass these to Stage 2:"
echo "        MD_PATH=$MERGED_MD_OUT"
echo "        JSON_PATH=$DOC_DIR/merged.pages.json"
