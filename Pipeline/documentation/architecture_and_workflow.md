# Architecture & Workflow

> A plain-English explanation of how this framework is designed and exactly what happens from the moment you hand over your files to the moment the final JSON lands on disk.

---

## What This System Does — In One Sentence

You give it a PDF document (already converted to text), a blank output template, and it fills that template with the correct values extracted from the document — using a local AI model and rule-based parsing.

---

## The Big Picture — Think of It as a Factory

The framework is like a **factory assembly line**. Raw material (your document) goes in one end, finished product (filled JSON) comes out the other. Each station on the line does one job and passes the result to the next.

```
┌──────────────────────────────────────────────────────────────────┐
│                         YOUR INPUTS                              │
│                                                                  │
│  merged_purchase_order.md   ──────────────────────┐             │
│  merged_pages.json          ──────────────────────┤ 3 files in  │
│  purchase_order_v1_null_template.json  ────────────┘             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      ASSEMBLY LINE                               │
│                                                                  │
│   Station 1:  Read and clean the document                        │
│   Station 2:  Break it into searchable chunks                    │
│   Station 3:  For each field, find the relevant chunks           │
│   Station 4:  Ask AI for the value (or parse table directly)     │
│   Station 5:  Fix any bad values                                 │
│   Station 6:  Validate everything                                │
│   Station 7:  Pour it all into the blank template                │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      FINAL OUTPUT                                │
│                                                                  │
│  output/purchase_order_result.json                               │
│  (exact shape of your null template, all values filled in)       │
└──────────────────────────────────────────────────────────────────┘
```

---

## How the Code Is Organised

The framework has a clean separation. The core pipeline is **generic** — it never knows anything about purchase orders or shipping bills. All document-specific knowledge lives in two files per document type.

```
framework/
│
├── run.py                        ← The front door. You run this.
│
├── core/                         ← THE GENERIC ENGINE (never changes)
│   ├── pipeline.py               ← Orchestrates all steps in order
│   ├── evidence.py               ← Breaks document into searchable chunks
│   ├── retriever.py              ← Finds relevant chunks per field
│   ├── extractor.py              ← Builds prompts, parses AI responses
│   ├── ollama_extractor.py       ← Calls the local Qwen2.5 AI model
│   ├── assembler.py              ← Puts extracted values into a dict
│   ├── repair.py                 ← Fixes bad values (dates, numbers, etc.)
│   ├── validator.py              ← Checks types and required fields
│   ├── cache.py                  ← Saves AI responses so they aren't repeated
│   └── logger.py                 ← Writes timestamped logs
│
├── adapters/                     ← DOCUMENT-SPECIFIC LOGIC (you write this)
│   ├── base_adapter.py           ← Template with 11 overridable hooks
│   ├── purchase_order_adapter.py ← All PO-specific logic
│   └── shipping_bill_adapter.py  ← All SB-specific logic
│
├── configs/                      ← DOCUMENT-SPECIFIC SETTINGS (you write this)
│   ├── base_config.py            ← Default settings
│   ├── purchase_order_config.py  ← PO page ranges, column maps, regex
│   └── shipping_bill_config.py   ← SB row/col positions
│
├── plugins/
│   └── registry.py               ← Maps "purchase_order" → adapter + config
│
├── loaders/                      ← Reads your input files
│   ├── merged_md_loader.py       ← Reads the .md file
│   ├── merged_pages_loader.py    ← Reads the .json file
│   └── template_loader.py        ← Reads and fills the null template
│
├── schemas/                      ← Your null templates live here
└── data/sample/                  ← Sample input files for testing
```

### The key design rule

> Adding a new document type = add adapter + config + register. **Zero changes to any core file.**

---

## The Three Input Files — What Each One Is

### File 1 — The Markdown (`merged_purchase_order.md`)

The document as readable text, split into pages by markers:

```
<!-- PAGE 1: page_0001.md -->
## PLACEMENT MEMORANDUM
Supplier: ABC Textiles Ltd
P/M No. 04-22-01-024-2601
Date: 15-MAR-2025
...

<!-- PAGE 2: page_0002.md -->
<table>
  <tr><td>1</td><td>SEA</td><td>Ile-de-France</td></tr>
</table>
...

<!-- PAGE 15: page_0015.md -->
GENERAL TERMS AND CONDITIONS OF PURCHASE
1. The buyer reserves the right to...   ← this gets stripped
```

### File 2 — The OCR JSON (`merged_pages.json`)

The same document but richer — each text block also knows its **position on the page** (bounding box), its **type** (is it a table? a title? plain text?), and **which page** it came from. This lets the framework treat tables and paragraphs differently.

```json
{
  "pages": [{
    "page_number": 0,
    "data": {
      "json_result": [[
        {"label": "table", "content": "<table>...</table>", "bbox_2d": [50,100,800,400]},
        {"label": "text",  "content": "Supplier: ABC Textiles Ltd", "bbox_2d": [50,420,400,445]}
      ]],
      "markdown_result": "## PLACEMENT MEMORANDUM\n..."
    }
  }]
}
```

### File 3 — The Null Template (`purchase_order_v1_null_template.json`)

A filled-out form with every answer blank. This is the **contract** — the output will match this shape exactly, nothing more, nothing less.

```json
{
  "Header": {
    "Supplier": null,
    "Buyer":    null,
    "PMNo":     null,
    "Date":     null
  },
  "RowWiseTable": [
    { "ShipNo": null, "ShipMode": null, "PortOfDischarge": null }
  ],
  "Details": {
    "Item1":   { "Item": { "No": null, ... }, "Quantity": null },
    "Item 24": { "Item": { "No": null, ... }, "Quantity": null }
  },
  "Footer": {
    "PaymentTerms": null,
    "ShipmentTime": null
  }
}
```

---

## The Full Workflow — Step by Step

### Step 1 — You Run the Command

```bash
python run.py \
  --doc-type purchase_order \
  --md   data/sample/merged_purchase_order.md \
  --json data/sample/merged_pages.json
```

`run.py` wakes up and does four things immediately:
1. Looks up `"purchase_order"` in the registry → gets `PurchaseOrderAdapter` + `PurchaseOrderConfig`
2. Resolves the template path → `schemas/purchase_order_v1_null_template.json`
3. **Auto-generates a schema from the template** — walks the template, finds every `null` slot, registers each one as a field the AI should extract. No separate schema file needed. The template IS the field list.
4. Kicks off the pipeline

---

### Step 2 — Loading the Markdown File

The markdown loader reads the file, finds all `<!-- PAGE N -->` markers, splits into pages, and **throws away T&C pages** (pages 15+ for purchase orders — configured in the config file).

The remaining 14 pages are joined with a separator and returned as one combined string.

---

### Step 3 — Loading the JSON File

The JSON loader reads the file and unwraps the block data for each page. There's one important detail: the OCR tool double-wraps the blocks (`[[blocks]]` not `[blocks]`). The loader unwraps this correctly.

Returns: per-page lists of OCR blocks, each block having its content, type label, and bounding box.

---

### Step 4 — The Adapter Cleans the Inputs

Before anything else, the **adapter** (the document specialist) gets a chance to clean up:

**Cleaning the JSON blocks:**
- Drops all pages with index ≥ 14 (T&C pages — again, belt-and-suspenders)
- Removes noise blocks (text blocks with ≤ 3 characters — OCR garbage)

**Cleaning the markdown:**
- Splits into per-page list and stores as `self._md_pages` — needed later for rule-based table parsing
- Strips page number markers like `"P. 11 / 14"`
- Strips decorative dash lines like `"--------------------"`

---

### Step 5 — Building the Evidence Store (Chunking)

Both inputs are merged into one unified collection of **EvidenceBlocks** — searchable chunks.

**From the JSON blocks:**
Every block becomes a chunk. Tables get **double-chunked**: one full TABLE block (the entire HTML) + one TABLE_ROW block per row. A table with 24 rows becomes 25 blocks.

**From the markdown:**
Split on `<table>` tags first (each table → one MD_TABLE block), then split remaining text on double newlines (each paragraph → one MD_TEXT block).

A 14-page purchase order ends up with roughly **176 blocks** in the evidence store.

---

### Step 6 — Parsing the Schema + Injecting Aliases

The auto-generated schema is parsed into a tree of `FieldNode` objects. Then the adapter's `get_field_aliases()` is called and aliases are injected into each node:

```
Before:  FieldNode("PMNo", aliases=[])
After:   FieldNode("PMNo", aliases=["P/M No.", "P/M NO", "PM NO"])
```

Now when the retriever searches for `PMNo`, it also looks for all three aliases.

---

### Step 7 — Extracting Scalar Fields (One Field at a Time)

For each scalar field (Supplier, PMNo, Date, etc.), the pipeline runs this loop:

#### 7a. Retrieve the top-6 most relevant evidence blocks

Every block gets scored (see the Chunking & Scoring document for details). Top 6 win.

#### 7b. Check the cache

Cache key = `sha256("purchase_order" + "Header.PMNo" + evidence_text)`. If a match exists on disk, return it instantly — no AI call.

#### 7c. Build a prompt and call the AI

```
Document type: purchase_order
Target field: PMNo
This field may also appear as: P/M No., P/M NO, PM NO.
Extract the value from the evidence below.
Return ONLY: {"value": <extracted_value>}
If not found, return: {"value": null}

--- EVIDENCE ---
P/M No. 04-22-01-024-2601
Date: 15-MAR-2025
...
--- END EVIDENCE ---
```

AI (Qwen2.5:32b running locally via Ollama) responds: `{"value": "04-22-01-024-2601"}`

Response is saved to cache. Value is parsed and stored.

#### 7d. Adapter post-processes the value

For `PMNo`: strips any label prefix the AI might have included (`"P/M No. 04-22"` → `"04-22"`).

Repeats for every scalar field. Each field = one AI call (or a cache hit if run before).

---

### Step 8 — Extracting List Fields (Tables)

For structured tables like `RowWiseTable` (the shipment schedule):

The AI is asked for the list — but the adapter **completely ignores the AI's answer** and runs a rule-based HTML table parser instead.

Why? Because the schedule table has perfectly fixed column positions. Exact indexing is 100% accurate. The AI is unnecessary here.

The rule-based parser:
- Reads pages 0-1 from `self._md_pages`
- Finds all `<table>` HTML blocks
- Detects whether each row has 10 or 8 columns (two layout variants exist)
- Uses the correct column map from config for each variant
- Skips header rows and totals rows (identified by first-cell values from config)
- Normalizes known typos (`"Ille-de-France"` → `"Ile-de-France"`)

---

### Step 9 — Assembly

The assembler takes all collected values (from both AI extraction and rule-based parsing) and builds a nested draft dictionary:

```json
{
  "Header": {"Supplier": "ABC Textiles Ltd", "PMNo": "04-22-01-024-2601", ...},
  "RowWiseTable": [{"ShipNo": "1", "ShipMode": "SEA", ...}, ...],
  ...
}
```

---

### Step 10 — Repair

A chain of rules runs over every field to fix systematic problems:

| Rule | What It Fixes | Example |
|---|---|---|
| `TruncateWhitespace` | Extra spaces | `"  ABC  "` → `"ABC"` |
| `EmptyStringToNull` | Empty strings | `""` → `null` |
| `NumberStripper` | Currency in number fields | `"$1,234.56"` → `1234.56` |
| `ShipModeNormalizer` | Variant ship mode labels | `"OCEAN FREIGHT"` → `"SEA"` |
| `PMNoNormalizer` | Label prefix in PM number | `"P/M No. 04-22"` → `"04-22"` |

Note: `DateNormalizer` (which converts to ISO-8601) is **excluded** for purchase orders because the downstream system expects `DD-MON-YYYY` format. The adapter explicitly removes it.

---

### Step 11 — Validation

Checks every field: required fields are not null, strings are strings, numbers are numbers, lists are lists. Returns a report with warnings. Any type errors or missing required fields mark the output as invalid.

---

### Step 12 — Finalize (The Final Assembly)

The adapter's `finalize()` method is the last step. It:

1. Loads the null template fresh
2. Fills the **Header** section from AI-extracted values
3. Fills the **RowWiseTable** by replicating the null prototype row for each parsed row
4. Fills **Details items** (pages 2-13) by running the rule-based detail parser across 5 table layout variants (the document uses different layouts on different pages)
5. Fills the **Footer** — regex patterns first, AI fallback if regex finds nothing
6. Calls `fill_template()` which enforces the critical rule: **only keys already in the template can appear in the output**. No extra keys ever sneak in.
7. Adds metadata (`_meta`, `schema_version`, `source`)

---

### Step 13 — Save

Result is written to `output/purchase_order_result.json`. The console prints a summary:

```
════════════════════════════════════════════════════════
  Extraction complete
  Valid          : True
  Validation     : VALID (1 warning)
  Elapsed        : 47.3s
  Output         : output/purchase_order_result.json
  Fields filled  : 34/42 (81%)
════════════════════════════════════════════════════════
```

---

## What the Final JSON Looks Like

```json
{
  "schema_version": "purchase_order_v1",
  "source": { "document_type": "purchase_order", "format": "pdf" },
  "Header": {
    "Supplier": "ABC Textiles Ltd",
    "Buyer":    "XYZ Retail Group",
    "PMNo":     "04-22-01-024-2601",
    "Date":     "15-MAR-2025",
    "Dept":     "HOME01",
    "FtyNo":    null
  },
  "RowWiseTable": [
    { "ShipNo": "1", "ShipMode": "SEA", "PortOfDischarge": "Ile-de-France", "Forwarder": "Maersk" },
    { "ShipNo": "2", "ShipMode": "AIR", "PortOfDischarge": "Paris CDG", "Forwarder": "DHL" }
  ],
  "Details": {
    "Item1": {
      "Item": { "No": "1", "PortOfLoading": "MUNDRA", "FinalDestination": "ECHT",
                "ShipMode": "SEA", "DeliveryDate": "15-JUN-2025" },
      "Quantity": "2,500 PCS",
      "UnitPrice": "USD1.9400",
      "NoOfCartons": "625 CTN"
    },
    "Item 2": { "..." : "..." }
  },
  "Footer": {
    "PaymentTerms":  "As per Buyer payment terms",
    "ShipmentTime":  "60 days after approval of samples",
    "MarkingOfGoods":"Each article must be marked with country of origin",
    "Certificate":   "To be supplied by the Supplier at his expense"
  },
  "_meta": { "doc_type": "purchase_order", "framework_version": "2.0" }
}
```

Every `null` that had data in the document → filled. Every `null` where the document genuinely had no value → stays `null`. The shape is identical to the null template — guaranteed.

---

## Summary of All Steps

| Step | What Happens | Who Does It |
|---|---|---|
| 1 | Parse CLI flags, auto-generate schema from template | `run.py` |
| 2 | Load markdown, strip T&C pages, split by page markers | `merged_md_loader` |
| 3 | Load JSON, unwrap OCR blocks per page | `merged_pages_loader` |
| 4 | Strip noise blocks and boilerplate text | `Adapter` |
| 5 | Chunk both inputs into ~176 searchable blocks | `evidence.py` |
| 6 | Parse schema, inject field aliases | `schema_parser` + `Adapter` |
| 7 | Per scalar field: retrieve → cache? → AI → postprocess → store | `retriever` + `OllamaExtractor` + `Adapter` |
| 8 | Per list field: retrieve tables → Adapter replaces AI with rule parser | `Adapter` |
| 9 | Build draft JSON from all collected values | `assembler` |
| 10 | Fix bad values (whitespace, dates, ship modes, etc.) | `repair.py` |
| 11 | Check types and required fields | `validator` |
| 12 | Fill null template section by section, enforce output shape | `Adapter.finalize()` + `template_loader` |
| 13 | Save JSON to output folder | `pipeline` |
