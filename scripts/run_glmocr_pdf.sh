#!/usr/bin/env bash
# =============================================================================
# run_glmocr_pdf.sh — Stage 1 OCR with GLM-OCR via a self-hosted vLLM server.
#
# Prerequisites
#   - Python 3.11+ environment with the FULL stack (run setup_env.sh on a box
#     where `python3 --version` is >= 3.10, or pass PYTHON_BIN=python3.11).
#   - A running vLLM server, e.g. on port 8080:
#         vllm serve zai-org/GLM-OCR \
#             --allowed-local-media-path / --port 8080 \
#             --served-model-name glm-ocr \
#             --speculative-config.method mtp \
#             --speculative-config.num_speculative_tokens 1
#
# Required (one of):
#   PDF_PATH=/abs/path/to/file.pdf
#   PDF_DIR=/abs/path/to/folder/of/pdfs
#
# Optional:
#   OUT_DIR     Md_JSON_Extraction/outputs
#   DPI         300
#   GLMOCR_MODE selfhosted
#   GLMOCR_OCR_API_HOST   localhost
#   GLMOCR_OCR_API_PORT   8080
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OCR_DIR="$ROOT_DIR/Md_JSON_Extraction"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

PDF_PATH="${PDF_PATH:-}"
PDF_DIR="${PDF_DIR:-}"
OUT_DIR="${OUT_DIR:-$OCR_DIR/outputs}"
DPI="${DPI:-300}"
MODE="${GLMOCR_MODE:-selfhosted}"
OCR_HOST="${GLMOCR_OCR_API_HOST:-localhost}"
OCR_PORT="${GLMOCR_OCR_API_PORT:-8080}"

if [ -z "$PDF_PATH" ] && [ -z "$PDF_DIR" ]; then
  echo "[ERROR] Provide PDF_PATH=/path/file.pdf  or  PDF_DIR=/path/to/pdfs"
  echo "Example:"
  echo "  PDF_PATH='Md_JSON_Extraction/examples/source/MI-8937-0906 Purchase Order.pdf' \\"
  echo "    ./scripts/run_glmocr_pdf.sh"
  exit 1
fi

if [ ! -d "$OCR_DIR" ]; then
  echo "[ERROR] Md_JSON_Extraction directory not found: $OCR_DIR"
  exit 1
fi

if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1090,SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "[WARN] No virtual env at $VENV_DIR — attempting with system Python."
fi

if ! curl -fsS "http://${OCR_HOST}:${OCR_PORT}/v1/models" >/dev/null 2>&1; then
  echo "[WARN] vLLM server not reachable at http://${OCR_HOST}:${OCR_PORT}"
  echo "       Start it in another terminal before running OCR. Continuing anyway."
fi

cd "$OCR_DIR"
mkdir -p "$OUT_DIR"

CMD=(python run_glmocr_pdf_pages.py
     --out "$OUT_DIR"
     --dpi "$DPI"
     --mode "$MODE"
     --ocr-host "$OCR_HOST"
     --ocr-port "$OCR_PORT"
     --keep-images)

if [ -n "$PDF_PATH" ]; then
  CMD+=(--pdf "$PDF_PATH")
else
  CMD+=(--pdf-dir "$PDF_DIR")
fi

echo "[OCR] ${CMD[*]}"
"${CMD[@]}"

echo
echo "[OCR] Done. Per-page outputs are in $OUT_DIR/<doc_folder>/page_*/"
echo "[OCR] Next: merge them with"
echo "      DOC_DIR=$OUT_DIR/<doc_folder> ./scripts/merge_glmocr_outputs.sh"
