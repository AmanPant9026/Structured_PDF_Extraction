#!/usr/bin/env bash
# =============================================================================
# clean.sh — Reset the project to a clean state.
#
# Removes:
#   - .venv (and any custom $VENV_DIR)
#   - the legacy garbage directory '{core,adapters,...'
#   - __pycache__ trees
#   - egg-info dirs from editable installs
#
# Does NOT touch:
#   - your input PDFs / sample data
#   - Pipeline/output/  or  Pipeline/logs/
#   - Md_JSON_Extraction/outputs/ (Stage 1 OCR results)
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"

echo "[CLEAN] Project root: $ROOT_DIR"

if [ -d "$VENV_DIR" ]; then
  echo "[CLEAN] Removing venv: $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

GARBAGE='Pipeline/{core,adapters,configs,helpers,plugins,schemas,data'
if [ -d "$GARBAGE" ]; then
  echo "[CLEAN] Removing legacy garbage dir: $GARBAGE"
  rm -rf "$GARBAGE"
fi

echo "[CLEAN] Removing __pycache__ trees..."
find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

echo "[CLEAN] Removing *.egg-info..."
find . -type d -name '*.egg-info' -prune -exec rm -rf {} + 2>/dev/null || true

echo "[CLEAN] Done."
