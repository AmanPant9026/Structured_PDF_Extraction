#!/usr/bin/env bash
# =============================================================================
# setup_env.sh — Auto-profile environment setup.
#
# Behavior
#   - Detects your Python version.
#   - Python 3.10+ -> installs the FULL stack (Stage 1 + Stage 2 + Frontend).
#   - Python 3.8/3.9 -> installs Stage 2 + Frontend only (no transformers/torch).
#   - Always installs the Streamlit frontend deps (version-pinned per Python).
#   - Cleans up the legacy garbage directory if present.
#   - Idempotent: safe to re-run.
#
# Usage
#   ./scripts/setup_env.sh                          # auto-detect
#   STAGE=2     ./scripts/setup_env.sh              # force Stage 2 + Frontend
#   STAGE=full  ./scripts/setup_env.sh              # force full (needs Py 3.10+)
#   PYTHON_BIN=python3.11 ./scripts/setup_env.sh    # use a specific Python
#   CLEAN=1     ./scripts/setup_env.sh              # nuke .venv first
#   NO_FRONTEND=1 ./scripts/setup_env.sh            # skip streamlit/pandas
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
STAGE="${STAGE:-auto}"            # auto | 2 | full
CLEAN="${CLEAN:-0}"
NO_FRONTEND="${NO_FRONTEND:-0}"

# --- Python presence + version --------------------------------------------- #
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[ERROR] Python interpreter '$PYTHON_BIN' not found in PATH."
  echo "        Install Python 3.8+ (3.11/3.12 recommended for the full stack)."
  echo "        Or specify a different binary, e.g.: PYTHON_BIN=python3.11 ./scripts/setup_env.sh"
  exit 1
fi

PY_VER="$("$PYTHON_BIN" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VER%%.*}"
PY_MINOR="${PY_VER##*.}"

echo "[SETUP] Project root: $ROOT_DIR"
echo "[SETUP] Python:       $PY_VER ($PYTHON_BIN)"

# --- Decide install profile ------------------------------------------------ #
if [ "$STAGE" = "auto" ]; then
  if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
    STAGE="full"
  else
    STAGE="2"
  fi
fi

case "$STAGE" in
  2|full) ;;
  *) echo "[ERROR] Unknown STAGE='$STAGE'. Use STAGE=2 or STAGE=full."; exit 1;;
esac

echo "[SETUP] Profile:      $STAGE"
echo "[SETUP] Frontend:     $([ "$NO_FRONTEND" = "1" ] && echo "skipped" || echo "yes")"

if [ "$STAGE" = "full" ] && [ "$PY_MINOR" -lt 10 ]; then
  echo "[ERROR] STAGE=full requires Python 3.10+ (you have $PY_VER)."
  echo "        Install Python 3.11 (Ubuntu deadsnakes):"
  echo "          sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update"
  echo "          sudo apt install -y python3.11 python3.11-venv python3.11-dev"
  echo "        Then re-run: PYTHON_BIN=python3.11 ./scripts/setup_env.sh"
  echo "        Or fall back to: STAGE=2 ./scripts/setup_env.sh"
  exit 1
fi

# --- Remove legacy garbage directory --------------------------------------- #
GARBAGE='Pipeline/{core,adapters,configs,helpers,plugins,schemas,data'
if [ -d "$GARBAGE" ]; then
  echo "[SETUP] Removing legacy garbage directory: $GARBAGE"
  rm -rf "$GARBAGE"
fi

# --- venv ------------------------------------------------------------------ #
if [ "$CLEAN" = "1" ] && [ -d "$VENV_DIR" ]; then
  echo "[SETUP] CLEAN=1 -> removing existing venv: $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "[SETUP] Creating virtual environment: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090,SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip setuptools wheel

# --- Install dependencies -------------------------------------------------- #
if [ "$STAGE" = "2" ]; then
  echo "[SETUP] Installing Stage 2 (Pipeline) dependencies."
  python -m pip install -r Pipeline/requirements.txt
  echo "[SETUP] Skipping editable install of Md_JSON_Extraction (its pyproject.toml requires Python 3.10+)."
else
  echo "[SETUP] Installing FULL stack from requirements.txt"
  python -m pip install -r requirements.txt

  if [ -d "$ROOT_DIR/Md_JSON_Extraction" ]; then
    echo "[SETUP] Installing Md_JSON_Extraction package (editable)..."
    python -m pip install -e "$ROOT_DIR/Md_JSON_Extraction"
  fi

  cat <<EOF

[SETUP] FULL stack installed.
        For GLM-OCR self-hosted serving you ALSO need vLLM and the latest
        transformers source build (NOT in requirements.txt):

          pip install -U vllm --torch-backend=auto \\
              --extra-index-url https://wheels.vllm.ai/nightly
          pip install git+https://github.com/huggingface/transformers.git

EOF
fi

# --- Frontend deps (Streamlit eval app) ------------------------------------ #
if [ "$NO_FRONTEND" != "1" ]; then
  if [ -f requirements-frontend.txt ]; then
    echo "[SETUP] Installing frontend deps (streamlit/pandas/openpyxl)..."
    python -m pip install -r requirements-frontend.txt
  fi
fi

cat <<EOF

[SETUP] Done. Activate the environment with:
        source $VENV_DIR/bin/activate

[NEXT]  Make sure Ollama is running in another terminal:
        ollama serve
        ollama pull qwen2.5:32b   (one-time)

        Then run a sample extraction:
        ./scripts/run_purchase_order.sh
        ./scripts/run_shipping_bill.sh
        ./scripts/run_all_sample.sh    (both)

        Or launch the Streamlit eval frontend:
        ./scripts/run_frontend.sh
EOF
