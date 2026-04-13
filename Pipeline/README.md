<div align="center">

<!-- <img src="../Md_JSON_Extraction/frontend/assets/bosch.png" alt="Bosch Logo" width="200"/> -->
# Full Pipeline(Stage 2)
**Runs the full end to end pipeline to extracted structured JSON**
</div>

---
> **This is Stage 2 of the pipeline.** Complete [Stage 1 (Md & JSON Extraction)](../Md_JSON_Extraction/README.md) first to get your OCR outputs.

---




# PDF Extraction Framework

> A fully local, open-source pipeline that extracts structured data from PDF documents and produces schema-aligned JSON output. No proprietary APIs. No API keys. No cloud dependency.

---

## Introduction

This framework was built to solve a specific problem: commercial PDF documents — purchase orders, shipping bills, invoices — need to be read and turned into structured data automatically, at scale, without sending sensitive documents to a cloud service.

The framework combines two extraction strategies:
- **AI extraction** (Qwen2.5:32b via Ollama) for free-text fields like names, dates, and addresses
- **Rule-based parsing** for structured tables with fixed column positions — faster, 100% accurate, and free

Both strategies run inside a single unified pipeline. The pipeline is completely generic — it never knows what kind of document it is processing. All document knowledge lives in two files per document type: a config file and an adapter file.

**Two document types ship out of the box:**
- Purchase Order (Li & Fung Placement Memorandum)
- Shipping Bill (Indian Customs Shipping Bill)

---

## Folder Structure

```
framework/
│
├── run.py                          ← Single entry point for all document types
├── run_purchase_order.py           ← Legacy shim
├── run_shipping_bill.py            ← Legacy shim
├── requirements.txt
│
├── core/                           ← Generic pipeline (never changes)
│   ├── pipeline.py                 ← Orchestrates all 11 extraction steps
│   ├── evidence.py                 ← Chunks document into searchable blocks
│   ├── retriever.py                ← Scores and ranks blocks per field
│   ├── schema_parser.py            ← Parses schema into FieldNode tree
│   ├── extractor.py                ← Builds AI prompts, parses responses
│   ├── ollama_extractor.py         ← Calls Qwen2.5 via Ollama HTTP API
│   ├── assembler.py                ← Builds nested JSON from extracted values
│   ├── repair.py                   ← Rule-chain post-fix engine
│   ├── validator.py                ← Type and required-field validation
│   ├── cache.py                    ← SHA256 disk-backed response cache
│   └── logger.py                   ← Structured JSON logging
│
├── adapters/                       ← Document-specific logic (you write this)
│   ├── base_adapter.py             ← Abstract base with 11 overridable hooks
│   ├── purchase_order_adapter.py   ← Purchase Order implementation
│   └── shipping_bill_adapter.py    ← Shipping Bill implementation
│
├── configs/                        ← Document-specific settings (you write this)
│   ├── base_config.py              ← Default ExtractionConfig dataclass
│   ├── purchase_order_config.py    ← Page ranges, column maps, regex patterns
│   └── shipping_bill_config.py     ← Row/column positions per section
│
├── plugins/
│   └── registry.py                 ← Maps doc type string → adapter + config
│
├── loaders/                        ← Input file readers
│   ├── merged_md_loader.py         ← Reads PAGE-marker markdown files
│   ├── merged_pages_loader.py      ← Reads glmocr JSON format
│   └── template_loader.py          ← Loads and fills null templates
│
├── helpers/                        ← Shared utilities
│   ├── table_helpers.py            ← HTML table → dict/matrix/column
│   ├── text_helpers.py             ← Regex, date, number, string utils
│   └── schema_helpers.py           ← Fill-rate, json_diff, alignment
│
├── schemas/                        ← Null templates (output shape definitions)
│   ├── purchase_order_v1_null_template.json
│   └── shipping_bill_v1_null_template.json
│
├── data/sample/                    ← Sample inputs for testing
├── output/                         ← Extraction results saved here
└── logs/                           ← Timestamped run logs
```

---

## Understanding the Workflow in Detail

For a complete explanation of what happens from the moment you provide input files to the moment the final JSON is written — how the document is cleaned, chunked, retrieved, extracted, repaired, validated, and assembled — see:

**→ [Architecture & Complete Workflow](documentation/architecture_and_workflow.md)**

This document covers: the design principles, the layer architecture, what each input file contains, and a step-by-step walkthrough of every stage in the pipeline with real examples.

---

## Running the Pipeline End to End

### Prerequisites

**1. Install Python dependencies**
```bash
pip install beautifulsoup4 lxml
```

**2. Install Ollama** (the local LLM server)
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**3. Pull the Qwen2.5 model** (~20 GB one-time download)
```bash
ollama pull qwen2.5:32b
```
> For faster development/testing, use `qwen2.5:7b` instead (much smaller, lower accuracy).

**4. Start the Ollama server** (keep this terminal open)
```bash
ollama serve
```

---

### Clone and Set Up

```bash
git clone <your-repo-url>
cd framework
pip install beautifulsoup4 lxml
```

---

### Run a Purchase Order Extraction

```bash
python run.py \
  --doc-type purchase_order \
  --md   data/sample/merged_purchase_order.md \
  --json data/sample/merged_pages.json
```

Output: `output/purchase_order_result.json`

---

### Run a Shipping Bill Extraction

```bash
python run.py \
  --doc-type shipping_bill \
  --md   data/sample/merged_shipping_bill.md \
  --json data/sample/merged_shipping_pages.json
```

Output: `output/shipping_bill_result.json`

---

### All Available Flags

```bash
# List all registered document types
python run.py --list

# Validate inputs without calling the AI (fast sanity check)
python run.py --doc-type purchase_order --md myfile.md --dry-run

# Inspect file structure before running
python run.py --doc-type purchase_order --md myfile.md --inspect

# Use a smaller, faster model (for development)
python run.py --doc-type purchase_order --md myfile.md --model qwen2.5:7b

# Use a specific Ollama server (not localhost)
python run.py --doc-type purchase_order --md myfile.md --ollama-url http://192.168.1.50:11434

# Disable cache (force fresh AI calls)
python run.py --doc-type purchase_order --md myfile.md --no-cache

# Specify custom output path
python run.py --doc-type purchase_order --md myfile.md --output results/my_output.json

# Provide all inputs explicitly
python run.py \
  --doc-type purchase_order \
  --md       data/sample/merged_purchase_order.md \
  --json     data/sample/merged_pages.json \
  --template schemas/purchase_order_v1_null_template.json \
  --output   output/my_result.json \
  --model    qwen2.5:32b \
  --log-dir  logs/
```

---

### Check Your Results

```python
import json
from helpers.schema_helpers import fill_rate_report, count_filled_fields
from loaders.template_loader import load_template

# Load result
result   = json.load(open("output/purchase_order_result.json"))
template = load_template("schemas/purchase_order_v1_null_template.json")

# Overall fill count
filled, total = count_filled_fields(result)
print(f"Filled: {filled}/{total} ({100*filled/total:.1f}%)")

# Per-section breakdown
report = fill_rate_report(result, template)
for section, stats in report.items():
    print(section, stats)
```

---

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot connect to Ollama` | Server not running | Run `ollama serve` in a separate terminal |
| Field is `null` in output | Missing aliases or wrong section hint | Add aliases in `get_field_aliases()`, add hint in `get_section_hints()` |
| Field includes the label | AI returned `"Supplier: ABC Ltd"` | Add cleanup in `postprocess_field()` |
| Dates in wrong format | `DateNormalizer` converting them | Use `get_custom_repair_engine()` to exclude it |
| List has header row | Missing row-skip logic | Add header text to skip values in config |
| Wrong column values | Column map is wrong | Recount columns in the actual HTML table |
| Very slow extraction | Large model, cold cache | Use `qwen2.5:7b` for dev; let cache warm up |
| Output has wrong shape | Template and adapter out of sync | Verify `finalize()` fills all template keys |

---

## Adding a New Document Type

To add support for a completely new document type, you create three files and add one line to the registry. Zero changes to any core pipeline file.

**→ [Step-by-Step Guide: Adding a New Document Type](documentation/adding_new_document_type.md)**

This guide walks through: designing the null template, writing the config, writing the adapter (with complete working code for a Commercial Invoice), registering, and iterating until the fill rate is acceptable.

---

## Reference: Chunking & Scoring Strategy

For a technical deep-dive into how documents are broken into searchable pieces and how those pieces are ranked for each field:

**→ [Chunking & Scoring Strategy](documentation/chunking_and_scoring.md)**

Covers: the two chunking strategies (JSON blocks vs markdown splitting), the table explosion technique, the four scoring components (keyword score, section score, type bonus, extra scorers), a full worked example, and the limitations of the approach.

---

## Reference: Manual Work Required

For a complete breakdown of every manual decision you must make when adding a new document type — what to write in the config, what to write in the adapter, and why:

**→ [Manual Work Guide](documentation/manual_work_guide.md)**

Covers: null template design, page section ranges, column index maps, regex patterns, field aliases, section hints, layout variant classification, repair rules, and the complete iteration checklist.

---

## Glossary

| Term | Definition |
|---|---|
| **EvidenceBlock** | A single searchable chunk of document content — a paragraph, a full table, or a single table row |
| **EvidenceStore** | The full collection of EvidenceBlocks for one document run (~176 blocks for a 14-page PO) |
| **FieldNode** | One node in the schema tree — stores the field name, data type, aliases, and path |
| **Adapter** | Document-specific logic class implementing `BaseDocumentAdapter` (11 hooks) |
| **Config** | Document-specific settings dataclass — page ranges, column maps, regex patterns |
| **Null template** | JSON file with all output fields set to `null` — defines the exact output shape |
| **top_k** | Number of evidence blocks retrieved per field (default 5–6) |
| **Repair rule** | A single post-extraction value correction — one class, one concern |
| **Section hint** | A section heading string that helps the retriever find relevant blocks for a field |
| **Alias** | An alternative label the document uses for a canonical field name |
| **Ollama** | The local LLM server that runs Qwen2.5 on your hardware |
