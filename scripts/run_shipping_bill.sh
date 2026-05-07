#!/usr/bin/env bash
# =============================================================================
# run_shipping_bill.sh — Stage 2 extraction for the Shipping Bill sample.
#
# Override any of these via env vars:
#   MD_PATH, JSON_PATH, OUTPUT_PATH, OLLAMA_MODEL, OLLAMA_URL, EXTRA_ARGS
# =============================================================================
set -euo pipefail

export DOC_TYPE="shipping_bill"
export MD_PATH="${MD_PATH:-data/sample/merged_shipping_bill.md}"
export JSON_PATH="${JSON_PATH:-data/sample/merged_shipping_pages.json}"
export OUTPUT_PATH="${OUTPUT_PATH:-output/shipping_bill_result.json}"

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_stage2.sh"
