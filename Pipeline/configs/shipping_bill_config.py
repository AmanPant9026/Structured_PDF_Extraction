"""
configs/shipping_bill_config.py
--------------------------------
Shipping Bill extraction configuration.

Document structure (6 pages, each a distinct PART):
  Page 1 → PART-I  SUMMARY         (sections A-J)
  Page 2 → PART-II INVOICE DETAILS (sections A-D)
  Page 3 → PART-III ITEM DETAILS
  Page 4 → PART-IV SCHEME DETAILS  (sections A-M)
  Page 5 → PART-V  REEXPORT        (section N)
  Page 6 → PART-V  DECLARATIONS
"""

from dataclasses import dataclass, field
from typing import Any, Dict

from .base_config import ExtractionConfig


@dataclass
class ShippingBillConfig(ExtractionConfig):
    doc_type: str = "shipping_bill"
    version:  str = "1.0"

    max_tokens_per_call: int = 1200
    retrieval_top_k:     int = 6

    extra: Dict[str, Any] = field(default_factory=lambda: {

        "template_path": "schemas/shipping_bill_v1_null_template.json",

        # Page index (0-based) for each logical section
        "page_sections": {
            "common":      0,
            "part_i":      0,
            "part_ii":     1,
            "part_iii":    2,
            "part_iv":     3,
            "part_v_re":   4,
            "part_v_decl": 5,
        },

        # Common header table row→col positions
        "common_row_patterns": {
            # Header table layout (0-based):
            # row0: Port Code | SB No | SB Date
            # row1: INHZA1   | 56515593 | 15-DEC-24
            # row2: IEC/Br   | 3LW3532546992 | 91
            # row3: GSTIN/TYPE | 30FRBXH... GST
            # row4: CB CODE   | TYWHG...
            # row5: TYPE | INV | ITEM | CONT
            # row6: Nos  | 8   | 1    | 8
            # row7: PKG  | 26  | G.WT | KGS | 99.32
            "port_code": (1, 0),   # "INHZA1"
            "sb_no":     (1, 1),   # "56515593"
            "sb_date":   (1, 2),   # "15-DEC-24"
            "iec":       (2, 1),
            "br":        (2, 2),
            "gstin":     (3, 1),
            "cb_code":   (4, 1),
            "nos_inv":   (6, 1),
            "nos_item":  (6, 2),
            "nos_cont":  (6, 3),
            "pkg":       (7, 1),
            "gwt_unit":  (7, 3),
            "gwt_value": (7, 4),
        },

        # Regex patterns for merged-cell port/country fields
        "regex_patterns": {
            "12.PORT OF LOADING":            r"12\.PORT OF LOADING\s*(.*?)(?=\d+\.|$)",
            "13.COUNTRY OF FINALDESTINATIO": r"13\.COUNTRY OF FINALDESTINATION\s*(.*?)$",
            "14.STATE OF ORIGIN":            r"14\.STATE OF ORIGIN\s*(.*?)(?=\d+\.|$)",
            "15.PORT OF FINAL DESTINATION":  r"15\.PORT OF FINAL DESTINATION\s*(.*?)$",
            "16.PORT OF DISCHARGE":          r"16\.PORT OF DISCHARGE\s*(.*?)(?=17\.|$)",
            "17.COUNTRY OF DISCHARGE":       r"17\.COUNTRY OF DISCHARGE\s*(.*?)$",
        },

        # Page 2 item detail column index map
        "item_detail_cols": {
            "1.ItemSNo":    0,
            "2.HS CD":      1,
            "3.DESCRIPTION":2,
            "4.QUANTITY":   3,
            "5.UQC":        4,
            "6.RATE":       5,
            "7.VALUE(F/C)": 6,
        },

        # Page 3 invoice items column map
        "invoice_item_cols": {
            "1INVSN":       0,
            "2ITEMSN":      1,
            "3.HS CD":      2,
            "4.DESCRIPTION":3,
            "5.QUANTITY":   4,
            "6UQC":         5,
            "7.RATE":       6,
            "8VALUE(F/C)":  7,
            "9.FOB (INR)":  8,
            "10.PMV":       9,
        },
    })
