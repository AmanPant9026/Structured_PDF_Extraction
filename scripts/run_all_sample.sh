#!/usr/bin/env bash
# =============================================================================
# run_all_sample.sh — One-shot: env setup + both sample documents.
#
# Skip the env step (e.g. you already ran setup_env.sh):
#   SKIP_SETUP=1 ./scripts/run_all_sample.sh
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_SETUP="${SKIP_SETUP:-0}"

if [ "$SKIP_SETUP" != "1" ]; then
  "$ROOT_DIR/scripts/setup_env.sh"
fi

"$ROOT_DIR/scripts/run_purchase_order.sh"
"$ROOT_DIR/scripts/run_shipping_bill.sh"

echo
echo "[DONE] Sample purchase order and shipping bill runs completed."
echo "[DONE] Outputs are in: $ROOT_DIR/Pipeline/output/"
ls -la "$ROOT_DIR/Pipeline/output/" 2>/dev/null || true
