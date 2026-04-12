"""
examples/add_new_doc_type.py
-----------------------------
GUIDE: How to add a brand-new document type (e.g. "Commercial Invoice")
without modifying any core pipeline or existing adapter code.

Steps
-----
1. Create a config  → subclass ExtractionConfig, override fields you need
2. Create an adapter → subclass BaseDocumentAdapter, override needed hooks
3. Register          → registry.register("commercial_invoice", Adapter, Config)
4. Run               → pipeline.run("commercial_invoice", json_pages, md, schema)

That is literally it.  Zero core changes.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# ── Make sure framework root is on sys.path ───────────────────────────────── #
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.base_adapter import BaseDocumentAdapter
from configs.base_config import ExtractionConfig
from core.pipeline import ExtractionPipeline
from plugins.registry import DocumentRegistry


# ════════════════════════════════════════════════════════════════════════════ #
# STEP 1 — Config
# Only override what differs from the sensible defaults in ExtractionConfig.
# ════════════════════════════════════════════════════════════════════════════ #

@dataclass
class CommercialInvoiceConfig(ExtractionConfig):
    doc_type: str = "commercial_invoice"
    version: str = "1.0"
    retrieval_top_k: int = 5
    extra: Dict[str, Any] = field(default_factory=lambda: {
        "invoice_number_pattern": r"INV[\/\-]?\w+",
        "total_label": "GRAND TOTAL",
    })


# ════════════════════════════════════════════════════════════════════════════ #
# STEP 2 — Adapter
# Override ONLY the hooks you need.  Everything else falls through to no-ops.
# ════════════════════════════════════════════════════════════════════════════ #

class CommercialInvoiceAdapter(BaseDocumentAdapter):
    """Commercial Invoice adapter — minimal hook overrides."""

    def get_field_aliases(self) -> Dict[str, List[str]]:
        return {
            "invoice_no":    ["INVOICE NUMBER", "INV NO", "INVOICE #"],
            "invoice_date":  ["DATE", "INVOICE DATE"],
            "seller_name":   ["SELLER", "FROM", "EXPORTER", "SOLD BY"],
            "buyer_name":    ["BUYER", "TO", "BILL TO", "IMPORTER"],
            "total_amount":  ["GRAND TOTAL", "TOTAL AMOUNT", "TOTAL DUE"],
            "payment_terms": ["TERMS", "PAYMENT TERMS", "CONDITIONS"],
            "description":   ["GOODS DESCRIPTION", "ITEM", "COMMODITY"],
            "quantity":      ["QTY", "PCS", "NOS"],
            "unit_price":    ["UNIT PRICE", "RATE", "PRICE"],
        }

    def get_section_hints(self) -> Dict[str, List[str]]:
        return {
            "invoice_no":   ["INVOICE", "REFERENCE"],
            "seller_name":  ["FROM", "SELLER", "SHIPPER"],
            "buyer_name":   ["TO", "BUYER", "BILL TO"],
            "total_amount": ["GRAND TOTAL", "TOTAL"],
        }

    def postprocess_list(
        self, path: str, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove rows where quantity is zero or missing."""
        if "line_items" not in path:
            return items
        return [
            r for r in items
            if r.get("quantity") not in (None, "", "0", 0)
        ]

    def finalize(self, data: Dict[str, Any], schema) -> Dict[str, Any]:
        data["_meta"] = {
            "doc_type": "commercial_invoice",
            "framework_version": self.config.version,
        }
        return data


# ════════════════════════════════════════════════════════════════════════════ #
# STEP 3 — Schema  (normally loaded from schemas/commercial_invoice_schema.json)
# ════════════════════════════════════════════════════════════════════════════ #

INVOICE_SCHEMA = {
    "document_type": "commercial_invoice",
    "version": "1.0",
    "fields": {
        "invoice_no":    {"type": "string", "required": True,  "description": "Invoice number"},
        "invoice_date":  {"type": "string", "required": True,  "description": "Invoice date"},
        "seller_name":   {"type": "string", "required": True,  "description": "Seller name"},
        "buyer_name":    {"type": "string", "required": True,  "description": "Buyer name"},
        "currency":      {"type": "string", "required": False, "description": "Currency code"},
        "total_amount":  {"type": "number", "required": False, "description": "Total invoice amount"},
        "payment_terms": {"type": "string", "required": False, "description": "Payment terms"},
        "line_items": {
            "type": "list",
            "list_root": True,
            "required": False,
            "description": "Invoice line items",
            "items": {
                "description": {"type": "string", "required": True},
                "quantity":    {"type": "number",  "required": True},
                "unit_price":  {"type": "number",  "required": False},
                "total_value": {"type": "number",  "required": False},
            }
        }
    }
}


# ════════════════════════════════════════════════════════════════════════════ #
# STEP 4 — Register + Run
# ════════════════════════════════════════════════════════════════════════════ #

def run_invoice_example():
    # Start from the default registry (shipping_bill + purchase_order already in)
    registry = DocumentRegistry.with_defaults()

    # Register the new type — ONE line, no core code touched
    registry.register(
        "commercial_invoice",
        CommercialInvoiceAdapter,          # pass the CLASS, not an instance
        CommercialInvoiceConfig(),
    )

    print("Registered document types:", registry.registered_types())

    # Pipeline is unchanged — it works for any registered type
    pipeline = ExtractionPipeline(registry=registry)

    # ── Minimal sample data ────────────────────────────────────────────── #
    sample_json_pages = [[
        {
            "index": 0, "label": "text",
            "bbox_2d": [50, 50, 500, 80],
            "content": "COMMERCIAL INVOICE\nInvoice No: INV-2025-0042",
            "native_label": "paragraph_title",
            "polygon": [[50,50],[50,80],[500,80],[500,50]],
        },
        {
            "index": 1, "label": "text",
            "bbox_2d": [50, 90, 500, 150],
            "content": (
                "From: Global Exports Ltd, Mumbai\n"
                "To: Euro Imports GmbH, Berlin\n"
                "Date: 15-MAR-2025"
            ),
            "native_label": "text",
            "polygon": [[50,90],[50,150],[500,150],[500,90]],
        },
    ]]
    sample_markdown = (
        "# COMMERCIAL INVOICE\n\n"
        "Invoice No: INV-2025-0042  \nDate: 15-MAR-2025\n\n"
        "**From:** Global Exports Ltd, Mumbai  \n"
        "**To:** Euro Imports GmbH, Berlin  \n\n"
        "Total Amount: USD 12,500.00"
    )

    # ── Dry-run: verify registry + evidence without hitting the LLM ────── #
    from core.evidence import build_evidence_store
    from core.schema_parser import parse_schema_dict

    store  = build_evidence_store(sample_json_pages, sample_markdown)
    parsed = parse_schema_dict(INVOICE_SCHEMA)

    print(f"\n[DRY RUN] Evidence blocks built : {len(store)}")
    print(f"[DRY RUN] Schema leaves         : {sum(1 for _ in parsed.all_leaves())}")
    print(f"[DRY RUN] List roots            : {[lr.name for lr in parsed.list_roots]}")
    print("\nTo run the full LLM extraction:")
    print("  result = pipeline.run(")
    print("      'commercial_invoice',")
    print("      json_pages   = sample_json_pages,")
    print("      markdown     = sample_markdown,")
    print("      schema       = INVOICE_SCHEMA,")
    print("      output_path  = 'output/commercial_invoice_result.json',")
    print("  )")
    print("  print(result.to_json())")


if __name__ == "__main__":
    run_invoice_example()
