<div align="center">

<!-- <img src="frontend/assets/bosch.png" alt="Bosch Logo" width="200"/> -->

# Md & JSON Extraction (Stage 1)

**Convert raw PDF/image documents into Markdown text and structured OCR JSON using GLM-OCR**

</div>

---

> **This is Stage 1 of the PDF Document Extraction Pipeline.** After completing this stage, take your OCR outputs and proceed to [Pipeline (Stage 2)](../Pipeline/README.md) for structured data extraction. Once Stage 2 is complete, come back here to run the evaluation frontend and generate comparison reports.

---

## What This Stage Does

You give it PDF pages (as images). It gives you back:

| Output | Description |
|---|---|
| `result.md` | Full page text in Markdown format. Tables preserved as HTML. |
| `result.json` | Every OCR block with its type label (`text`, `table`, `title`), bounding box coordinates, and content. |

These outputs are generated per page. You then merge them into `merged_document.md` and `merged_pages.json` which are the inputs for Stage 2.

Under the hood, this uses **GLM-OCR** — an open-source multimodal OCR model (0.9B parameters) built on the GLM-V encoder–decoder architecture. Layout analysis is handled by **PP-DocLayout-V3**, which detects text blocks, tables, titles, formulas, images, and seals before the OCR model processes each region in parallel.

---

## Prerequisites

- **Python 3.12+** with [UV package manager](https://docs.astral.sh/uv/getting-started/installation/)
- **GPU** with sufficient VRAM (recommended: 24 GB+ for vLLM serving)
- **Docker** (optional, for containerized vLLM deployment)

---

## Step-by-Step Guide

---

### Step 1 — Create the Environment

```bash
cd Md_JSON_Extraction
uv venv --python 3.12 --seed
source .venv/bin/activate
```

---

### Step 2 — Install Dependencies

Install the GLM-OCR SDK:

```bash
uv pip install -e .
```

Install vLLM for model serving:

```bash
uv pip install -U vllm --torch-backend=auto --extra-index-url https://wheels.vllm.ai/nightly
```

GLM-OCR requires the latest transformers source build:

```bash
uv pip install git+https://github.com/huggingface/transformers.git
```

---

### Step 3 — Start the GLM-OCR Server (Terminal 1)

Open a terminal and start the vLLM server:

```bash
vllm serve zai-org/GLM-OCR \
  --allowed-local-media-path / \
  --port 8080 \
  --served-model-name glm-ocr \
  --speculative-config.method mtp \
  --speculative-config.num_speculative_tokens 1
```

The model will download on first run (~1.8 GB). Wait until you see the server is ready and accepting requests.

**Keep this terminal running.** The server must stay alive for OCR inference.

---

### Step 4 — Run OCR Inference (Terminal 2)

Open a **new terminal**, activate the same environment, and run inference on your document images:

```bash
source .venv/bin/activate

python run_glmocr_images.py \
  --image "/path/to/your/images/" \
  --out "./outputs_image" \
  --mode selfhosted \
  --ocr-host 127.0.0.1 \
  --ocr-port 8080 \
  --config "glmocr/config.yaml" \
  --log-level INFO
```

**`--image`** can be a single image file or a directory containing multiple page images.

For PDF files, use the PDF-specific script instead:

```bash
python run_glmocr_pdf_pages.py \
  --pdf "/path/to/your/document.pdf" \
  --out "./outputs_pdf" \
  --mode selfhosted \
  --ocr-host 127.0.0.1 \
  --ocr-port 8080 \
  --config "glmocr/config.yaml" \
  --log-level INFO
```

---

### Step 5 — Collect OCR Outputs

After inference completes, your output directory will contain:

```
outputs_image/
  <image_name>/
    result.json          ← structured OCR blocks with bounding boxes
    result.md            ← Markdown text output
    imgs/                ← cropped image regions (if layout mode enabled)
```

These are the raw OCR outputs that Stage 2 needs.

---

### Step 6 — Proceed to Stage 2 (Pipeline)

Take your OCR outputs and go to the **Pipeline** folder to run the structured extraction:

> **📖 Follow the instructions in [`Pipeline/README.md`](../Pipeline/README.md)**

The Pipeline will:
- Load your merged `.md` and `.json` files
- Extract structured fields using AI + rule-based parsing
- Produce a schema-aligned JSON result

**Come back here after Stage 2 is complete** to run the evaluation frontend.

---

### Step 7 — Install Frontend Dependencies

Once you have your structured outputs from Stage 2, install the evaluation frontend dependencies:

```bash
pip install streamlit pandas openpyxl
```

Or using UV:

```bash
uv pip install streamlit pandas openpyxl
```

---

### Step 8 — Run the Evaluation Frontend

Launch the Streamlit app:

```bash
streamlit run frontend/app.py
```

This opens a web interface in your browser (typically `http://localhost:8501`).

---

### Step 9 — Upload Files and Generate Comparison Report

In the Streamlit frontend, upload three files using the sidebar:

| Upload Slot | What to Upload |
|---|---|
| **Ground Truth** | The ground-truth JSON or Excel file with expected values |
| **Predicted Output** | The structured JSON produced by your Pipeline (Stage 2) |
| **GPT Results** | The GPT-generated extraction JSON (for comparison) |

Then use the action buttons:

1. **Evaluate Overlap Recall (MyModel)** — measures how many ground-truth values appear in your Pipeline output
2. **Evaluate Overlap Recall (GPT)** — same metric for the GPT extraction
3. **Build GT↔Pred Alignment Excel** — generates a color-coded Excel showing exact match, mismatch, and missing values side-by-side
4. **Build 3-way Comparison Excel** — generates a single Excel comparing Ground Truth vs Your Model vs GPT

Download the generated Excel reports for detailed inspection.

---

## What the Comparison Report Contains

The generated Excel report provides field-level comparison with color coding:

| Status | What It Means |
|---|---|
| **MATCH** | Extracted value matches ground truth exactly |
| **NEAR_MATCH** | Extracted value is close but not identical (partial overlap, formatting differences) |
| **MISMATCH** | Extracted value is present but incorrect |
| **MISSING_KEY** | Field exists in ground truth but was not extracted |

This makes it easy to see where the extraction pipeline is working well, where it is partially correct, and where it is failing.

---

## Configuration Reference

The GLM-OCR SDK configuration lives in `glmocr/config.yaml`. Key settings for self-hosted mode:

```yaml
pipeline:
  maas:
    enabled: false            # Self-hosted, not cloud API

  ocr_api:
    api_host: 127.0.0.1       # vLLM server address
    api_port: 8080             # Must match --port from Step 3
    model: glm-ocr             # Must match --served-model-name

  enable_layout: true          # Enable PP-DocLayout-V3 for region detection

  page_loader:
    max_tokens: 5096
    temperature: 0.8
```

---

## Troubleshooting

**vLLM server won't start / OOM errors** — GLM-OCR is 0.9B parameters. Reduce `--max-model-len` if you are GPU-constrained.

**502 errors during inference** — The server may still be loading the model. Wait until startup is complete.

**OCR results are poor quality** — Make sure `enable_layout: true` is set in `config.yaml`. Without layout detection, the model misses table boundaries.

**Streamlit can't find `eval_backend`** — Make sure you run `streamlit run frontend/app.py` from the `Md_JSON_Extraction/` directory (not from inside `frontend/`).

---

## Summary of Execution Order

```
Terminal 1                          Terminal 2
──────────                          ──────────
Start vLLM server (Step 3)
  ↓ keep running
                                    Run OCR inference (Step 4)
                                    Collect outputs (Step 5)
                                      ↓
                                    ─── Go to Pipeline (Stage 2) ───
                                    ─── Run structured extraction ──
                                    ─── Come back with results ─────
                                      ↓
                                    Install Streamlit (Step 7)
                                    Run evaluation frontend (Step 8)
                                    Upload & compare (Step 9)
                                    Download Excel reports
```

---

## Tech Stack

| Component | Technology |
|---|---|
| OCR Model | GLM-OCR (0.9B params, BF16, GLM-V architecture) |
| Layout Detection | PP-DocLayout-V3 (25 label categories) |
| Model Serving | vLLM with Multi-Token Prediction |
| Evaluation Frontend | Streamlit, pandas, openpyxl |
| PDF Rendering | PyMuPDF, pdf2image |

---
