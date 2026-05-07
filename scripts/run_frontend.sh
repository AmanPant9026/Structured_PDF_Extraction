#!/usr/bin/env bash
# =============================================================================
# run_frontend.sh — Launch the Streamlit OCR-quality-check eval frontend.
#
# The app needs to be launched from Md_JSON_Extraction/ so that
# `from eval_backend import ...` resolves correctly. This script handles that.
#
# Optional env vars:
#   PORT          8501       (default Streamlit port)
#   HOST          localhost
#   HEADLESS      0          (set 1 for SSH/headless boxes — no auto-open browser)
#   VENV_DIR      .venv      (auto-activated if present)
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OCR_DIR="$ROOT_DIR/Md_JSON_Extraction"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

PORT="${PORT:-8501}"
HOST="${HOST:-localhost}"
HEADLESS="${HEADLESS:-0}"

if [ ! -d "$OCR_DIR" ]; then
  echo "[ERROR] Md_JSON_Extraction directory not found: $OCR_DIR"
  exit 1
fi
if [ ! -f "$OCR_DIR/frontend/app.py" ]; then
  echo "[ERROR] Frontend app not found: $OCR_DIR/frontend/app.py"
  exit 1
fi

if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1090,SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "[WARN] No virtual env at $VENV_DIR. Using system Python."
  echo "       Run ./scripts/setup_env.sh first if Streamlit is not installed."
fi

if ! command -v streamlit >/dev/null 2>&1; then
  echo "[ERROR] Streamlit is not installed in this environment."
  echo "        Run: ./scripts/setup_env.sh   (installs streamlit/pandas/openpyxl)"
  echo "        Or:  pip install -r requirements-frontend.txt"
  exit 1
fi

cd "$OCR_DIR"

CMD=(streamlit run frontend/app.py
     --server.port "$PORT"
     --server.address "$HOST")

if [ "$HEADLESS" = "1" ]; then
  CMD+=(--server.headless true)
fi

echo "[FRONTEND] Launching: ${CMD[*]}"
echo "[FRONTEND] Open in browser:  http://$HOST:$PORT"
"${CMD[@]}"
