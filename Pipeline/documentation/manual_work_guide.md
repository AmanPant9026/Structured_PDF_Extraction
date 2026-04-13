# Manual Work Guide

> This framework automates the pipeline, the AI calls, the caching, the repair, and the output formatting. What it cannot automate is **understanding the document**. That knowledge has to come from you. This guide covers everything you personally must do.

---

## The Core Split

```
YOU DO                                    FRAMEWORK DOES
──────────────────────────────────        ──────────────────────────────────
Understand the document structure    →    Evidence store construction
Express that understanding in              from your inputs
config + adapter files               →    Retrieval scoring (once aliases
Test and iterate on bad extractions         and hints are configured)
                                     →    AI prompt construction and calling
                                     →    Response parsing and type coercion
                                     →    Repair rule execution
                                     →    Validation
                                     →    Template filling
                                     →    Caching
                                     →    Logging
```

The framework removes all the boilerplate engineering. But it cannot study a document for you. The config and adapter files are where you write down your document understanding in a form the framework can act on.

---

## MANUAL WORK REQUIRED

---

### Null Template

```
□ Design every field name — must match what the adapter will produce
□ Design the nesting structure — Header, Body, Footer, etc.
□ Decide on list slot counts — if the document always has ≤24 items,
    name them "Item1", "Item 2", ... "Item 24" explicitly
□ Identify if any slots have extra fields — e.g. "Item 24" may have
    additional fields that "Item1" through "Item 23" do not
```

**How:** Design the template to match what your downstream system needs. The template is the contract — output will match this shape exactly.

---

### Config File

#### Page section ranges

```
□ Open the real document alongside its OCR markdown output
□ Count pages manually
□ Write down which pages contain: header, items, footer, T&C
□ Translate into (start_page, end_page) tuples, 0-indexed
```

```python
"page_sections": {
    "row_wise_table": (0, 1),   # schedule on pages 0-1
    "details":        (2, 13),  # items on pages 2-13
    "tc":             (14, 19), # T&C from page 14 onward → strip
}
```

**What breaks if wrong:** Setting T&C start too early strips real content. Setting details end too low means some items are never parsed.

---

#### Column index maps

```
□ Open the HTML table in the raw markdown (search for <table>)
□ Count <td> elements left to right, starting from 0
□ Write the index for every field you want to extract
□ If column count varies across pages, write one map per variant
□ Name them by column count: col_map_10, col_map_8
```

```python
# Page 0: 10-column table (col 2 is a merged/empty cell)
"rowwise_col_map_10": {
    "ShipNo":    0,
    "ShipRef":   1,
    # col 2 = empty — skip
    "ShipMode":  3,
    "CustOrderNo": 4,
}

# Page 1: 8-column table (no empty column)
"rowwise_col_map_8": {
    "ShipNo":    0,
    "ShipRef":   1,
    "ShipMode":  2,   # shifted by 1 vs 10-col
    "CustOrderNo": 3,
}
```

**What breaks if wrong:** Off-by-one errors produce wrong field values silently — the framework won't complain, it will just extract the wrong column.

---

#### Row/header skip values

```
□ Run the table parser once (or print what it produces)
□ Look for garbage rows — header rows, totals rows, blank rows
□ Copy the text from the first cell of each garbage row
□ Add that text to the skip set
```

```python
"rowwise_header_values": {
    "",                  # blank first cell
    "ship no.",          # column header row
    "ship no",
    "total quantity:",   # totals row
    "article no.",       # sub-header row
}
```

---

#### Regex patterns for text-based fields

```
□ Copy raw text from the document that surrounds each field
□ Write a regex that captures just the value, not the label
□ Test it with re.search() before putting it in the config
□ Check it works across all sample documents
```

```python
"footer_patterns": {
    # Capture everything after "Payment Terms:" up to HTML or newline
    "PaymentTerms":   r"Payment Terms:\s*([^<\n]+)",

    # Capture up to the next label (Certificate:) or end of string
    "MarkingOfGoods": r"Marking on Goods[:\s]+([^<]+?)(?=Certificate:|$)",

    # Capture single date value
    "ShipmentTime":   r"Shipment Time:\s*([^<\n]*?)(?=Payment|$)",
}
```

**Common patterns:**

| Situation | Pattern |
|---|---|
| `Label: Value` (to end of line) | `r"Label:\s*([^<\n]+)"` |
| `Label: Value` before next label | `r"Label:\s*(.+?)(?=NextLabel:|$)"` |
| Date in text | `r"(\d{2}-[A-Z]{3}-\d{4})"` |
| Quantity with unit | `r"([\d,]+\.?\d*\s*(?:PCS\|CTN\|KGM))"` |
| Reference code | `r"([A-Z]{2,}[\d\-/]+)"` |

---

#### Fixed expected values

```
□ Note any values that should always be the same across documents
□ These are used as fallbacks and cross-checks in finalize()
```

```python
"expected_article_no": "11012401",
"expected_unit_price": "USD1.9400",
"expected_incoterm":   "FOB",
```

---

### Adapter File

#### Boilerplate stripping (`preprocess_markdown`)

```
□ Read the raw markdown of your document carefully
□ Find every piece of text that appears on every page but
    carries no useful information
□ Write one regex per boilerplate type
□ Verify: does stripping accidentally remove real content?
```

Common boilerplate types:

| Type | Example | Regex |
|---|---|---|
| Page numbers | `P. 11 / 14` | `r"P\.\s*\d+\s*/\s*\d+"` |
| Running headers | `Li & Fung — PO Memo` | `r"Li & Fung.{0,30}Memo"` |
| Watermarks | `CONFIDENTIAL` | `r"CONFIDENTIAL"` |
| Decorative lines | `--------------------` | `r"^-{10,}$"` |
| Copyright footers | `© 2025 Company Ltd` | `r"©\s*\d{4}.{0,60}"` |

---

#### Field aliases (`get_field_aliases`)

```
□ For every field in your schema, find every alternative label
    the document uses for it
□ Search the raw markdown:
    grep -i "seller\|exporter\|from:\|shipper" myfile.md
□ Note every label variant (check across all sample documents)
□ Add all of them to the alias list
```

```python
"SellerName": ["FROM", "SELLER", "EXPORTER", "SOLD BY", "SHIPPER", "MANUFACTURER"]
```

**Signs of missing aliases:**
- Field is null when you know the value exists in the document
- Running `grep "field_value" myfile.md` finds it but extraction returns null

**This is the highest-impact manual step.** Wrong or missing aliases = wrong evidence retrieved = wrong or null values. Always add more than you think you need.

---

#### Section hints (`get_section_hints`)

```
□ For each field, check if there's a consistent section heading
    that appears near it in the document
□ Only add a hint if: (a) the heading is reliable, and
    (b) it doesn't appear elsewhere with a different meaning
```

```python
"Supplier":    ["Supplier", "SUPPLIER DETAILS"],
"PMNo":        ["P/M No.", "PLACEMENT MEMORANDUM"],
"PaymentTerms":["Payment Terms"],
# Don't add "DETAILS" — too generic, appears everywhere
```

---

#### Which lists to parse with rules vs AI

```
□ Look at each list in your schema
□ Ask: does this list come from a fixed-structure table?
    YES → rule-based (faster, 100% accurate, free)
    NO  → leave it to the AI
```

| Use rule-based when | Use AI when |
|---|---|
| Table has fixed column positions | Content is free-form text |
| Same layout across all documents | Layout varies unpredictably |
| You can verify 100% accuracy | Some variation is acceptable |
| Table has many rows (performance) | Table has few rows |

---

#### Layout variant classification

```
□ Go through every page of the structured section
□ For each page, count columns in the main data table
□ Note: do any pages have a different column count?
□ For each distinct column count, write detection logic
    and the corresponding extraction code
```

**Example — 5 layout variants in purchase_order_adapter.py:**

```
Page 2:  7 cols → Layout A: all fields in separate cells
Page 3:  5 cols → Layout B: dates embedded in header row
Page 4:  5 cols → Layout D: qty/price in combined data row
Page 7:  6 cols → Layout E: single date column only
Page 10: 2 cols → Layout C: everything compressed into one cell
```

Detection code:
```python
if n >= 7:      # Layout A
    ...
elif n == 6:    # Layout E
    ...
elif n == 5:
    if re.search(r"\d[\d,]+\s*PCS", data_c[2]):
        ...     # Layout D
    else:
        ...     # Layout B
else:
    ...         # Layout C (2-4 cols)
```

This is the hardest part of adapter writing. You need to study every page, understand why layouts differ, and write code that handles all variants correctly.

---

#### Regex for embedded fields in compound cells

```
□ Find cells that contain multiple fields packed together
□ Write a regex per field to extract just that field's value
□ Test against real cell content from the document
```

```python
# Cell content: "11012401  FC Reference No: MARPEX/2023  Incoterm: FOB  Ship Ref.: 12345"
fc_ref   = re.search(r"FC Reference No\s*:\s*([\w/]+)", full_info)
incoterm = re.search(r"Incoterm\s*:\s*(\w+)", full_info)
ship_ref = re.search(r"Ship Ref\.\s*:\s*([\d]+)", full_info)
```

---

#### Custom repair rules

```
□ Run extractions on your sample documents
□ Look at the output for systematic errors:
    - Values that include the label prefix ("Supplier: ABC Ltd")
    - Values with inconsistent formats ("SEA", "OCEAN FREIGHT", "FCL")
    - Empty strings where null is expected
□ Write one RepairRule subclass per systematic error
```

```python
class ShipModeNormalizer(RepairRule):
    def applies_to(self, field, value):
        return "shipmode" in field.name.lower().replace("_","") and isinstance(value, str)

    def repair(self, field, value):
        v = value.strip().upper()
        if "AIR" in v: return "AIR"
        if any(t in v for t in ("SEA","OCEAN","FCL","LCL")): return "SEA"
        return v
```

---

#### Which built-in repair rules to exclude

```
□ Check each built-in rule against your document's expected output format
□ DateNormalizer converts DD-MON-YYYY → YYYY-MM-DD
    Exclude if your downstream system expects DD-MON-YYYY
□ NumberStripper removes currency symbols from number fields
    Exclude if fields like UnitPrice must stay as "USD1.9400"
```

```python
def get_custom_repair_engine(self):
    return RepairEngine(rules=[
        TruncateWhitespace(),
        EmptyStringToNull(),
        # NumberStripper()  ← excluded: UnitPrice must stay "USD1.9400"
        # DateNormalizer()  ← excluded: dates must stay DD-MON-YYYY
        BooleanNormalizer(),
        ShipModeNormalizer(),   # custom
    ])
```

---

#### Final assembly priority in `finalize()`

```
□ For each section, decide: which source wins?
    Option A: rule-based result only
    Option B: AI result only
    Option C: rule-based first, AI as fallback
    Option D: AI first, rule-based as fallback
□ Footer fields typically use Option C:
    regex patterns first, AI as fallback
□ Structured tables use Option A: rule-based only
□ Free-text header fields use Option B: AI only
```

```python
# Footer: rule-based first, AI as fallback
footer_data = {
    "PaymentTerms":   regex_result.get("PaymentTerms")
                      or ai_result.get("PaymentTerms"),
    "ShipmentTime":   regex_result.get("ShipmentTime")
                      or ai_result.get("ShipmentTime"),
}
```

---

## Iteration Workflow

```
Run extraction
      ↓
Check output with fill_rate_report()
      ↓
Find null or wrong fields
      ↓
Diagnose:
  Field null?    → missing aliases, wrong page range, wrong section hint
  Wrong value?   → postprocess_field, repair rules, DateNormalizer
  Bad list row?  → col_map wrong, skip values incomplete
      ↓
Fix config or adapter
      ↓
Re-run (cache means only unfixed fields re-call the AI)
      ↓
Repeat until fill rate is acceptable (aim for >80%)
```

---

## Summary Checklist

### Null Template
```
□ Every output field has a null slot
□ Nesting structure reflects document sections
□ List prototype row covers all item-level fields
□ Fixed-count lists have named slots (Item1, Item 2, ...)
□ Slot variants identified (e.g. Item 24 has extra fields)
```

### Config File
```
□ page_sections — correct (start, end) tuples for every section
□ Column maps — verified against actual table HTML, 0-indexed
□ Row skip values — all header/totals row identifiers listed
□ Regex patterns — written and tested for all text-based fields
□ Fixed expected values — noted for cross-checking
```

### Adapter File
```
□ preprocess_markdown — boilerplate stripped with regex per type
□ get_field_aliases — 2-4 alternatives per field, all verified in docs
□ get_section_hints — major sections covered, no false matches
□ postprocess_list — rule-based parsers for structured tables
□ Layout variants — all page types studied and handled
□ Compound cell regex — per embedded field, tested on real content
□ Repair rules — one per systematic bad value pattern
□ Built-in rule exclusions — DateNormalizer, NumberStripper as needed
□ finalize() — all template sections filled, correct priority order
```


