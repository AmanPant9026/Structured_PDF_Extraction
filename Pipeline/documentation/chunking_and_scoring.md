# Chunking & Scoring Strategy

> How the framework breaks a document into searchable pieces, and how it decides which pieces are most relevant for each field being extracted.

---

## The Problem Being Solved

The AI model cannot read the entire document at once — context windows have limits, and feeding everything for every field would be slow and expensive. Instead, for each field (say `PortOfDischarge`), the framework needs to find the 5-6 most relevant pieces of the document and send only those to the AI.

That requires two things:
1. **Chunking** — break the document into small, searchable units
2. **Scoring** — rank those units by relevance to the field being extracted

---

## Part 1 — Chunking

### Two Inputs, Two Strategies

The framework receives a JSON file and a markdown file. Each is chunked differently.

---

### JSON Input — Pre-chunked by OCR

The OCR engine already decided where each block starts and ends, based on visual layout on the page. Each block has a label:

```
label == "table"                  →  becomes TABLE block
"title" in native_label           →  becomes TITLE block
everything else                   →  becomes TEXT block
```

#### The Table Explosion — The Key Insight

Every TABLE block is also split into individual rows:

```
One HTML table with 24 rows
         ↓
1  ×  TABLE block      (full HTML — used when extracting a list)
24 ×  TABLE_ROW blocks (each row as "cell1 | cell2 | cell3")
              (used when scoring for scalar fields like PortOfDischarge)
```

**Why both?** Two zoom levels for two different needs:
- Full TABLE → AI needs the whole table to extract all rows of a list
- Individual TABLE_ROW → retriever can find a specific row like `"1 | SEA | Ile-de-France | Maersk"` for a scalar field

---

### Markdown Input — Split by Structure

The markdown doesn't come pre-chunked. The framework applies two levels:

**Level 1 — Split on `<table>` tags:**
```
"text before table"  →  MD_TEXT block
"<table>...</table>" →  MD_TABLE block
"text after table"   →  MD_TEXT blocks (split further)
```

**Level 2 — Split remaining text on double newlines:**
```
"Supplier: ABC Ltd\n\nDate: 15-MAR-2025"
    ↓
MD_TEXT: "Supplier: ABC Ltd"
MD_TEXT: "Date: 15-MAR-2025"
```

---

### Chunking Comparison

| Property | This Framework | Typical RAG System |
|---|---|---|
| Chunk boundary | Natural document structure | Fixed token count (e.g. 512 tokens) |
| Overlap | None | 10–20% overlap |
| Table granularity | Two levels (whole + rows) | Single level |
| Chunk size | Variable (follows document) | Fixed |

**Why no overlap?** Standard RAG uses overlap to avoid losing context at arbitrary cut points. Here the boundaries are natural (table rows, paragraphs) so overlap would just duplicate content without adding information.

---

### What the Evidence Store Looks Like

For a 14-page purchase order:

```
From JSON:
  ~14  TEXT blocks        paragraphs and label text
  ~8   TITLE blocks       section headings
  ~6   TABLE blocks       full HTML tables
  ~120 TABLE_ROW blocks   individual table rows

From Markdown:
  ~8   MD_TABLE blocks    embedded HTML tables
  ~20  MD_TEXT blocks     text paragraphs

────────────────────────────────
Total: ~176 blocks in the store
```

---

## Part 2 — Scoring

When the pipeline needs to extract a field, it scores **every block** in the store against that field. The top-K scores win.

### The Formula

```
total_score = keyword_score
            + section_score
            + type_bonus
            + extra_scorer_scores
```

All components are additive. Higher = more relevant.

---

### Component 1 — Keyword Score

```
keyword_score = count of (field name + aliases) in block text
                × 1.5 per hit
                capped at 6.0 per keyword
```

Counts exact string matches (case-insensitive). The cap prevents one very repetitive block from dominating.

**Example — field `PMNo` with aliases `["P/M No.", "P/M NO", "PM NO"]`:**

```
Block A: "P/M No. 04-22-01-024-2601  Date: 15-MAR-2025"
  "p/m no." → 1 hit → 1.5
  "p/m no"  → 1 hit → 1.5
  keyword_score = 3.0

Block B: "ShipNo | SEA | Ile-de-France | Maersk"
  no hits
  keyword_score = 0.0

Block C: "P/M No. 04-22  P/M No. (Revised)"
  "p/m no." → 2 hits → min(3.0, 6.0) = 3.0
  "p/m no"  → 2 hits → min(3.0, 6.0) = 3.0
  keyword_score = 6.0  ← capped
```

---

### Component 2 — Section Score

```
section_score = 3.0  if block contains a section heading hint
              = 0.0  otherwise
```

The adapter provides section hints per field. These are known headings that appear near each field in the document.

**Example — hints configured as `{"Supplier": ["Supplier", "SUPPLIER DETAILS"]}`:**

```
Block: "SUPPLIER DETAILS\nABC Textiles Ltd\nMumbai, India"
  "SUPPLIER DETAILS" found  →  section_score = 3.0

Block: "PAYMENT TERMS\nAs per Buyer payment terms"
  no match                  →  section_score = 0.0
```

**Why 3.0?** Calibrated to equal roughly 2 keyword hits (2 × 1.5 = 3.0). A block in the right section but without keyword matches is treated as equivalent to a block with 2 keyword matches but in the wrong section.

---

### Component 3 — Type Bonus

```
For list fields (RowWiseTable, LineItems):
  TABLE or MD_TABLE block  →  +4.0
  TABLE_ROW block          →  +2.0
  anything else            →   0.0

For scalar fields (Supplier, PMNo, Date):
  TEXT, MD_TEXT, TITLE     →  +1.0
  anything else            →   0.0
```

**Why?** Scalar values live in text blocks. List values live in tables. This bonus ensures the right block type is prioritised regardless of keyword overlap.

The 4.0 bonus for TABLE + list field is intentionally large — even if a text block has strong keyword matches, the full table should still win for list extraction.

---

### Component 4 — Extra Scorers

```
extra_scorers = adapter-injected functions (none used currently)
              = open extension point for custom scoring logic
```

Adapters can inject additional scoring functions via `get_extra_scorers()`. Each function takes `(EvidenceBlock, FieldNode)` and returns a float score delta.

Examples of what could be added:
```python
# Prefer blocks from page 0 for header fields
def page_zero_for_headers(block, field):
    if "Header" in field.path and block.page == 0:
        return 2.0
    return 0.0

# Prefer blocks containing a date pattern for date fields
def date_pattern_bonus(block, field):
    if "date" in field.name.lower():
        if re.search(r"\d{2}-[A-Z]{3}-\d{4}", block.plain_text()):
            return 2.5
    return 0.0
```

This is also the extension point for **embedding-based semantic search** — replace the keyword scorer with cosine similarity against a sentence embedding, and the rest of the pipeline is unchanged.

---

### Full Worked Example

**Field:** `PortOfDischarge`
**Aliases:** `["PORT OF DISCHARGE", "DISCHARGE PORT", "POD"]`
**Section hint:** `{"PortOfDischarge": ["PORT OF DISCHARGE"]}`

| Block | Type | Keyword | Section | Type Bonus | **Total** |
|---|---|---|---|---|---|
| `"Supplier: ABC Textiles Ltd  Date: 15-MAR-2025"` | TEXT | 0.0 | 0.0 | 1.0 | **1.0** |
| `"1 \| SEA \| PORT OF DISCHARGE: Le Havre"` | TABLE_ROW | 1.5 | 3.0 | 0.0 | **4.5** |
| Full schedule HTML table | MD_TABLE | 4.5 | 3.0 | 0.0 | **7.5** ✅ |
| `"PORT OF DISCHARGE DETAILS"` | TITLE | 1.5 | 3.0 | 1.0 | **5.5** |
| `"shipped to the port of discharge as agreed"` | TEXT | 1.5 | 0.0 | 1.0 | **2.5** |

**Result (top_k = 5):** All 5 blocks sent to AI, in score order. The full schedule table (7.5) comes first — the AI sees the most relevant evidence at the top of the prompt.

---

### Retrieval for Lists vs Scalars

There are two different retrieval strategies:

**For scalar fields** → use scoring. Top-K blocks by score.

**For list fields** → bypass scoring entirely. Return all TABLE + MD_TABLE blocks directly.

```python
def retrieve_for_list(self, list_root):
    # Return all table blocks — no scoring needed
    table_blocks = [b for b in store.blocks if b.kind in (TABLE, MD_TABLE)]
    if table_blocks:
        return table_blocks[:top_k]
    # Fall back to TABLE_ROW blocks
    row_blocks = [b for b in store.blocks if b.kind == TABLE_ROW]
    ...
```

**Why bypass scoring for lists?** For `RowWiseTable`, the question "which block is relevant?" has an obvious answer: the shipment schedule table. Scoring individual blocks against the field name adds noise, not signal. Just return all tables directly.

---

### Evidence Text Truncation

Before evidence is sent to the AI, blocks are concatenated up to **4,000 characters**:

```python
def _build_evidence_text(blocks, max_chars=4000):
    parts, total = [], 0
    for block in blocks:
        txt = block.plain_text()
        if total + len(txt) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                parts.append(txt[:remaining] + "…")
            break
        parts.append(txt)
        total += len(txt)
    return "\n\n".join(parts)
```

The highest-scoring block is always first — truncation only cuts the least relevant evidence from the end.

---

## What Scoring Does NOT Do

| Limitation | Effect | Workaround |
|---|---|---|
| No semantic understanding | A synonym not in aliases scores 0 | Add more aliases in `get_field_aliases()` |
| No position weighting | Page 14 block scores same as page 1 | Add page-proximity scorer via `get_extra_scorers()` |
| No IDF weighting | Common words not penalised | Not a real problem — field names are domain-specific |
| No re-ranking | Top-K by score go straight to AI | Add extra scorers for edge cases |
