#!/usr/bin/env bash
# =============================================================================
# run_purchase_order.sh — Stage 2 extraction for the Purchase Order sample.
#
# Override any of these via env vars:
#   MD_PATH, JSON_PATH, OUTPUT_PATH, OLLAMA_MODEL, OLLAMA_URL, EXTRA_ARGS
#
# Examples:
#   ./scripts/run_purchase_order.sh
#   MD_PATH=/abs/path/merged.md JSON_PATH=/abs/path/merged_pages.json \
#     ./scripts/run_purchase_order.sh
#   EXTRA_ARGS="--dry-run" ./scripts/run_purchase_order.sh
# =============================================================================
set -euo pipefail

export DOC_TYPE="purchase_order"
export MD_PATH="${MD_PATH:-data/sample/merged_purchase_order.md}"
export JSON_PATH="${JSON_PATH:-data/sample/merged_pages.json}"
export OUTPUT_PATH="${OUTPUT_PATH:-output/purchase_order_result.json}"

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_stage2.sh"
