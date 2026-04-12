"""
configs/purchase_order_config.py
---------------------------------
Purchase Order (Li & Fung Placement Memorandum) extraction configuration.

All document-specific tweaks live here.
The pipeline + core never need to change.
"""

from dataclasses import dataclass, field
from typing import Any, Dict

from .base_config import ExtractionConfig


@dataclass
class PurchaseOrderConfig(ExtractionConfig):
    doc_type: str = "purchase_order"
    version: str = "2.0"

    # ── LLM ──────────────────────────────────────────────────────────── #
    max_tokens_per_call: int = 1200
    retrieval_top_k: int = 6

    # ── Schema ───────────────────────────────────────────────────────── #
    extra: Dict[str, Any] = field(default_factory=lambda: {

        # ── Input format ─────────────────────────────────────────────── #
        # Page index ranges for each logical section of the document
        # (merged_pages.json has 20 pages, 0-indexed)
        "page_sections": {
            "row_wise_table": (0, 1),    # shipment schedule rows
            "details":        (2, 13),   # per-item detail blocks
            "footer":         (2, 13),   # footer text is on detail pages
            "tc":             (14, 19),  # General T&C — strip entirely
        },

        # ── Header field patterns ─────────────────────────────────────── #
        "pm_number_pattern":          r"P/M\s*No\.?\s*([\w\-]+)",
        "date_pattern":               r"\d{2}-[A-Z]{3}-\d{4}",
        "dept_pattern":               r"Dept\.\s*([A-Z0-9]+)",

        # ── RowWiseTable: column indices inside the schedule table ──── #
        # Page 0 rows have 10 columns (empty description span at col 2 and trailing col 9):
        # col 0=ShipNo  col 1=ShipRef  col 2=empty  col 3=ShipMode
        # col 4=CustOrderNo  col 5=ReSchSchDly  col 6=ReSchDate
        # col 7=PortOfDischarge  col 8=Forwarder  col 9=empty
        "rowwise_col_map_10": {
            "ShipNo":          0,
            "ShipRef":         1,
            "ShipMode":        3,
            "CustOrderNo":     4,
            "ReSchSchDly":     5,
            "ReSchDate":       6,
            "PortOfDischarge": 7,
            "Forwarder":       8,
        },

        # Page 1 rows have 8 columns (no empty description column):
        # col 0=ShipNo  col 1=ShipRef  col 2=ShipMode  col 3=CustOrderNo
        # col 4=ReSchSchDly  col 5=ReSchDate  col 6=PortOfDischarge  col 7=Forwarder
        "rowwise_col_map_8": {
            "ShipNo":          0,
            "ShipRef":         1,
            "ShipMode":        2,
            "CustOrderNo":     3,
            "ReSchSchDly":     4,
            "ReSchDate":       5,
            "PortOfDischarge": 6,
            "Forwarder":       7,
        },

        # Minimum cell count for a row to be treated as a data row
        "rowwise_min_cols": 7,

        # Values in ShipNo column that indicate a header/separator row
        "rowwise_header_values": {
            "", "ship no.", "ship no", "article no.", "no",
            "total quantity:", "total quantity"
        },

        # ── Details: column indices in detail item tables ────────────── #
        # Each detail block has rows like:
        #   row A: [No. Port of Loading] [Final Destination] [DC] [ShipMode] [DeliveryDate] [ShipDate] [Quantity]
        #   row B: [ItemNo PortCode]      [Destination]       [DC]  [ShipMode]  ...
        #   row C: [ArticleNo]  [FC Ref / Incoterm / ShipRef / etc.]   [Qty PCS]  [UnitPrice]
        "details_col_map": {
            "No":                  0,    # item number
            "PortOfLoading":       0,    # same cell: "20 MUNDRA"
            "FinalDestination":    1,
            "DistributionCentre":  2,
            "ShipMode":            3,
            "DeliveryDate":        4,
            "ShipDate":            5,
            "Quantity_outer":      6,    # outer quantity (previous row's qty)
        },

        # Fields extracted from the "detail info" row (ArticleNo row)
        "detail_info_fields": [
            "FCReferenceNo", "Incoterm", "ShipRef",
            "OurItemNo", "CustomerItemNo", "PoNo",
            "CountryOfOriginRegion", "ProductionCountryRegion",
        ],

        # Quantity and UnitPrice column indices in the detail info row
        "detail_qty_col":   4,
        "detail_price_col": 5,

        # ── Footer patterns ──────────────────────────────────────────── #
        "footer_patterns": {
            # Stop before HTML tags (<) to avoid table cell bleed-through
            "PaymentTerms":  r"Payment Terms:\s*([^<\n]+)",
            "MarkingOfGoods": r"Marking on Goods[:\s]+([^<]+?)(?=Certificate:|$)",
            "Certificate":   r"Certificate:\s*([^<\n]+)",
            "SupplierNote":  r"The Supplier acknowledges[^<]+",
            "ShipmentTime":  r"Shipment Time:\s*([^<\n]*?)(?=Payment|$)",
        },

        # ── Validation ───────────────────────────────────────────────── #
        # Expected fixed values to cross-check
        "template_path":        "schemas/purchase_order_v1_null_template.json",
        "expected_article_no":  "11012401",
        "expected_unit_price":  "USD1.9400",
        "expected_incoterm":    "FOB",
        "expected_fc_ref":      "MARPEX/20230620/0",
    })
