# Adding a New Document Type — Step-by-Step Guide

> Everything you need to create a fully working extraction pipeline for a brand-new document type. Zero changes to any core file. Four additions only.

---

## What You Will Create

```
schemas/commercial_invoice_v1_null_template.json   ← output shape
configs/commercial_invoice_config.py               ← settings
adapters/commercial_invoice_adapter.py             ← logic
plugins/registry.py                               ← +1 line
```

That is it. Nothing in `core/` changes.

---

## Before You Write a Single Line of Code

### 1. Get real sample documents

You need at least 3–5 real documents of this type. One is not enough — layouts vary even within the same document type across different vendors or software versions.

### 2. Produce the OCR outputs

Run your samples through the OCR pipeline to get:
- `merged_<doctype>.md` — the markdown text
- `merged_<doctype>_pages.json` — the structured OCR blocks

### 3. Inspect the files

```bash
# See what the framework will see
python run.py --doc-type purchase_order --md myfile.md --inspect
```

Or directly in Python:
```python
from loaders.merged_md_loader import inspect_merged_md
inspect_merged_md("myfile.md")
# PAGE   1 | chars=  842 | tables=2 | '## COMMERCIAL INVOICE...'
# PAGE   2 | chars= 1203 | tables=3 | '<table>...'

from loaders.merged_pages_loader import inspect_merged_pages
inspect_merged_pages("myfile.json")
# page  0 | blocks= 12 {'table': 3, 'text': 8, 'title': 1} | md=1203 chars
```

### 4. Answer these questions before writing code

```
□ Total page count?
□ Which pages contain which sections? (header, items, footer, T&C)
□ Which pages should be discarded entirely?
□ For each table: how many columns? Does column count vary across pages?
□ For each field you want: what exact label does the document use?
□ What alternative labels exist? (check across all sample docs)
□ Is there a section heading near each field?
□ What boilerplate appears on every page? (page numbers, watermarks)
```

---

## Step 1 — Design the Null Template

The null template defines your output shape. Design it **before writing any code**.

Every `null` is a slot to fill. Lists need one prototype row with all fields set to null.

**Create:** `schemas/commercial_invoice_v1_null_template.json`

```json
{
  "schema_version": null,
  "source": {
    "document_type": null,
    "format": null
  },
  "Header": {
    "InvoiceNo":     null,
    "InvoiceDate":   null,
    "SellerName":    null,
    "SellerAddress": null,
    "BuyerName":     null,
    "BuyerAddress":  null,
    "Currency":      null,
    "PaymentTerms":  null
  },
  "LineItems": [
    {
      "Description": null,
      "HSCode":      null,
      "Quantity":    null,
      "UnitPrice":   null,
      "TotalValue":  null
    }
  ],
  "Totals": {
    "SubTotal":   null,
    "Tax":        null,
    "GrandTotal": null
  }
}
```

**Verify it:**
```python
from loaders.template_loader import load_template, introspect_template
template = load_template("schemas/commercial_invoice_v1_null_template.json")
introspect_template(template)
# Template top-level keys: ['schema_version', 'source', 'Header', 'LineItems', 'Totals']
# Header fields:           ['InvoiceNo', 'InvoiceDate', ...]
# LineItems prototype:     ['Description', 'HSCode', 'Quantity', ...]
```

---

## Step 2 — Create the Config

The config holds all fixed, non-code knowledge about the document structure. Fill it in after studying the real documents.

**Create:** `configs/commercial_invoice_config.py`

```python
from dataclasses import dataclass, field
from typing import Any, Dict
from .base_config import ExtractionConfig


@dataclass
class CommercialInvoiceConfig(ExtractionConfig):
    doc_type: str = "commercial_invoice"
    version:  str = "1.0"

    max_tokens_per_call: int = 1200
    retrieval_top_k:     int = 6

    extra: Dict[str, Any] = field(default_factory=lambda: {

        # ── Path to the null template ─────────────────────────────────
        "template_path": "schemas/commercial_invoice_v1_null_template.json",

        # ── Which pages belong to which section ──────────────────────
        # Fill these after studying the document manually
        "page_sections": {
            "header":   (0, 0),   # invoice header info is on page 0
            "items":    (0, 2),   # line items table spans pages 0-2
            "totals":   (2, 2),   # totals section is on last page
            "tc":       (3, 9),   # T&C pages — strip these
        },

        # ── Column map for the line items table ───────────────────────
        # Count columns left-to-right in the actual HTML table, 0-indexed
        "line_items_col_map": {
            "Description": 0,
            "HSCode":      1,
            "Quantity":    2,
            "UnitPrice":   3,
            "TotalValue":  4,
        },

        # ── Row values that mean "skip this row" ─────────────────────
        # Header rows and totals rows have these in their first cell
        "line_items_skip_values": {
            "", "description", "item", "goods", "total",
            "subtotal", "grand total", "no."
        },

        # ── Regex for text-based fields ───────────────────────────────
        "text_patterns": {
            "PaymentTerms": r"Payment Terms?:\s*([^\n<]+)",
            "Currency":     r"Currency:\s*([A-Z]{3})",
        },

        # ── Fixed expected values (for cross-checking) ────────────────
        "expected_currency": "USD",
    })
```

---

## Step 3 — Create the Adapter

The adapter contains all document-specific logic. Override only the hooks you need.

**Create:** `adapters/commercial_invoice_adapter.py`

```python
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from .base_adapter import BaseDocumentAdapter


class CommercialInvoiceAdapter(BaseDocumentAdapter):
    """
    Commercial Invoice adapter.
    Header fields extracted via AI.
    Line items extracted via rule-based table parser.
    """

    # ── HOOK 3: Clean the markdown ────────────────────────────────────
    def preprocess_markdown(self, markdown: str) -> str:
        """Split into pages, strip boilerplate from each page."""
        pages = markdown.split("---PAGE_BREAK---")
        self._md_pages = [p.strip() for p in pages if p.strip()]

        cleaned = []
        for page in self._md_pages:
            page = re.sub(r"Page\s+\d+\s+of\s+\d+", "", page, flags=re.IGNORECASE)
            page = re.sub(r"CONFIDENTIAL", "", page, flags=re.IGNORECASE)
            page = re.sub(r"^-{10,}$", "", page, flags=re.MULTILINE)
            cleaned.append(page)

        self._md_pages = cleaned
        return "\n\n---PAGE_BREAK---\n\n".join(cleaned)

    # ── HOOK 4a: Alternative field labels ─────────────────────────────
    def get_field_aliases(self) -> Dict[str, List[str]]:
        """Every alternative label each field might appear under."""
        return {
            "InvoiceNo":    ["INVOICE NUMBER", "INV NO", "INVOICE #", "INVOICE NO.", "REF"],
            "InvoiceDate":  ["DATE", "INVOICE DATE", "DATE OF ISSUE", "ISSUE DATE"],
            "SellerName":   ["FROM", "SELLER", "EXPORTER", "SOLD BY", "SHIPPER"],
            "BuyerName":    ["TO", "BUYER", "IMPORTER", "BILL TO", "CONSIGNEE"],
            "Currency":     ["CURRENCY", "CCY", "CURR."],
            "GrandTotal":   ["GRAND TOTAL", "TOTAL AMOUNT", "TOTAL DUE", "AMOUNT PAYABLE"],
            "PaymentTerms": ["PAYMENT TERMS", "TERMS", "CONDITIONS OF PAYMENT"],
        }

    # ── HOOK 5: Section headings near each field ──────────────────────
    def get_section_hints(self) -> Dict[str, List[str]]:
        return {
            "InvoiceNo":   ["INVOICE", "COMMERCIAL INVOICE", "REFERENCE"],
            "SellerName":  ["FROM", "SELLER", "SHIPPER", "EXPORTER"],
            "BuyerName":   ["TO", "BUYER", "CONSIGNEE", "BILL TO"],
            "GrandTotal":  ["TOTAL", "GRAND TOTAL", "AMOUNT DUE"],
            "PaymentTerms":["PAYMENT TERMS", "TERMS OF PAYMENT"],
        }

    # ── HOOK 7: Clean up individual field values ───────────────────────
    def postprocess_field(self, path: str, value: Any) -> Any:
        if value is None:
            return value
        # Strip "Invoice No: " prefix if AI included it
        if path.endswith("InvoiceNo") and isinstance(value, str):
            value = re.sub(r"^Invoice\s*No\.?\s*:?\s*", "", value, flags=re.IGNORECASE).strip()
        return value

    # ── HOOK 8: Replace AI output with rule-based parser for tables ───
    def postprocess_list(self, path: str, items: List[Dict]) -> List[Dict]:
        if "LineItems" in path:
            parsed = self._parse_line_items()
            return parsed if parsed else items
        return items

    # ── HOOK 11: Final assembly — fill the null template ──────────────
    def finalize(self, data: Dict, schema) -> Dict:
        from loaders.template_loader import load_template

        cfg      = self.config
        template = load_template(cfg.get("template_path"))
        result   = deepcopy(template)

        # Fill schema_version and source
        result["schema_version"] = "commercial_invoice_v1"
        result["source"] = {"document_type": "commercial_invoice", "format": "pdf"}

        # Fill Header
        hdr = data.get("Header", {})
        for k in result.get("Header", {}):
            result["Header"][k] = self._clean(hdr.get(k))

        # Fill LineItems — replicate the prototype row for each parsed item
        line_items = data.get("LineItems", [])
        if line_items and result.get("LineItems"):
            proto = result["LineItems"][0]
            filled = []
            for item_data in line_items:
                slot = deepcopy(proto)
                for field_name in slot:
                    if field_name in item_data:
                        slot[field_name] = item_data[field_name]
                filled.append(slot)
            result["LineItems"] = filled

        # Fill Totals
        tot = data.get("Totals", {})
        for k in result.get("Totals", {}):
            result["Totals"][k] = self._clean(tot.get(k))

        result["_meta"] = {"doc_type": "commercial_invoice", "framework_version": cfg.version}
        return result

    # ── Private: rule-based line item parser ──────────────────────────
    def _parse_line_items(self) -> List[Dict]:
        sections     = self.config.get("page_sections", {})
        start, end   = sections.get("items", (0, 0))
        col_map      = self.config.get("line_items_col_map", {})
        skip_values  = self.config.get("line_items_skip_values", set())
        pages        = self._md_pages or []

        items = []
        for page_idx in range(start, min(end + 1, len(pages))):
            tables = re.findall(r"<table[\s\S]*?</table>", pages[page_idx], re.IGNORECASE)
            for table_html in tables:
                soup = BeautifulSoup(table_html, "html.parser")
                for tr in soup.find_all("tr"):
                    cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                    if len(cells) < len(col_map):
                        continue
                    if cells[0].strip().lower() in skip_values:
                        continue
                    row = {
                        field_name: (cells[col_idx].strip() or None)
                        for field_name, col_idx in col_map.items()
                        if col_idx < len(cells)
                    }
                    items.append(row)
        return items

    @staticmethod
    def _clean(val):
        if isinstance(val, str):
            return val.strip() or None
        return val
```

---

## Step 4 — Register

Open `plugins/registry.py` and add your new type inside `default()`. This is the only existing file you touch.

```python
@classmethod
def default(cls) -> "DocumentRegistry":
    from adapters.purchase_order_adapter    import PurchaseOrderAdapter
    from adapters.shipping_bill_adapter     import ShippingBillAdapter
    from adapters.commercial_invoice_adapter import CommercialInvoiceAdapter  # ← ADD

    from configs.purchase_order_config      import PurchaseOrderConfig
    from configs.shipping_bill_config       import ShippingBillConfig
    from configs.commercial_invoice_config  import CommercialInvoiceConfig    # ← ADD

    r = cls()
    r.register("purchase_order",     PurchaseOrderAdapter,     PurchaseOrderConfig())
    r.register("shipping_bill",      ShippingBillAdapter,      ShippingBillConfig())
    r.register("commercial_invoice", CommercialInvoiceAdapter, CommercialInvoiceConfig())  # ← ADD
    return r
```

---

## Step 5 — Dry Run (No AI Calls)

Verify everything is wired up correctly before spending time on AI calls:

```bash
python run.py \
  --doc-type commercial_invoice \
  --md data/sample/my_invoice.md \
  --dry-run
```

Expected output:
```
──────────────────────────────────────────────
  DRY-RUN — no LLM calls made
──────────────────────────────────────────────
  Evidence blocks : 87
  Schema fields   : 11
  List roots      : ['LineItems']
  Model (unused)  : qwen2.5:32b @ http://localhost:11434
──────────────────────────────────────────────
  Inputs are valid. Ready to run.
```

Fix any errors here before proceeding.

---

## Step 6 — First Real Run

```bash
python run.py \
  --doc-type commercial_invoice \
  --md   data/sample/my_invoice.md \
  --json data/sample/my_invoice_pages.json
```

Check the output: `output/commercial_invoice_result.json`

---

## Step 7 — Diagnose and Iterate

First runs almost always have null fields or wrong values. Use this guide:

### Field is null

```python
# Step 1: Check if the text actually exists in the document
from loaders.merged_md_loader import load_merged_md
_, md = load_merged_md("myfile.md")
print("InvoiceNo" in md, "INVOICE NO" in md, "INV NO" in md)
# If False → the OCR didn't capture this text at all
# If True  → the retriever isn't finding it → add more aliases
```

```python
# Step 2: Check fill rate by section
import json
from helpers.schema_helpers import fill_rate_report
from loaders.template_loader import load_template
result   = json.load(open("output/commercial_invoice_result.json"))
template = load_template("schemas/commercial_invoice_v1_null_template.json")
print(fill_rate_report(result, template))
# {"Header": {"filled": 5, "total": 8, "pct": 62.5}, ...}
```

### Field has wrong value

| Symptom | Cause | Fix |
|---|---|---|
| `"Invoice No: INV-001"` instead of `"INV-001"` | AI included label | Add strip in `postprocess_field()` |
| `"2025-03-15"` instead of `"15-MAR-2025"` | `DateNormalizer` running | Use `get_custom_repair_engine()` to exclude it |
| Ship mode shows `"OCEAN FREIGHT"` | No normalizer | Add `ShipModeNormalizer` repair rule |
| List has header row included | Header text not in skip set | Add header text to skip values in config |
| List has wrong column values | Wrong column index | Fix `col_map` in config |

### Check the logs

```bash
# See every field extraction step
grep "extract_scalar" logs/pipeline_*.log

# See which fields hit the cache
grep "cache_hit" logs/pipeline_*.log

# See validation issues
grep "validation_issue" logs/pipeline_*.log
```

---

## Complete File Checklist

At the end you should have:

```
□  schemas/commercial_invoice_v1_null_template.json   (new file)
□  configs/commercial_invoice_config.py               (new file)
□  adapters/commercial_invoice_adapter.py             (new file)
□  plugins/registry.py                               (1 line added)
```

No other files changed.

---

## Testing Checklist

```
□ python run.py --list            shows "commercial_invoice"
□ python run.py ... --dry-run     completes with no errors
□ python run.py ... --inspect     shows correct page count and template shape
□ First full run completes        output JSON is created
□ fill_rate_report shows > 80%    on at least 3 real documents
□ All null fields investigated    fixed or documented as genuinely missing
□ All wrong values investigated   fixed via aliases, hints, or repair rules
□ Tested on different samples     covering all layout variants
```
