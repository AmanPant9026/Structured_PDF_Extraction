#!/usr/bin/env bash
# =============================================================================
# check_ollama.sh — verify Ollama is installed, running, and the model is ready.
# Pulls the model automatically if it is missing.
# =============================================================================
set -euo pipefail

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
MODEL="${OLLAMA_MODEL:-qwen2.5:32b}"

echo "[OLLAMA] Checking Ollama command..."
if ! command -v ollama >/dev/null 2>&1; then
  echo "[ERROR] Ollama is not installed."
  echo "        Install:  curl -fsSL https://ollama.com/install.sh | sh"
  exit 1
fi

echo "[OLLAMA] Checking server at $OLLAMA_URL ..."
if ! curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "[ERROR] Ollama server is not reachable at $OLLAMA_URL."
  echo "        Start it in another terminal:  ollama serve"
  exit 1
fi

echo "[OLLAMA] Checking model: $MODEL"
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fxq "$MODEL"; then
  echo "[OLLAMA] Model '$MODEL' not found locally. Pulling now (this can take a while)..."
  ollama pull "$MODEL"
fi

echo "[OLLAMA] Ready: $MODEL  @  $OLLAMA_URL"
