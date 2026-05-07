<div align="center">

<img src="frontend/assets/bosch.png" alt="Bosch Logo" width="200"/>

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

These outputs are generated per page. You then merge them into `merged_output.md` and `merged.pages.json` which are the inputs for Stage 2.

Under the hood, this uses **GLM-OCR** — an open-source multimodal OCR model (0.9B parameters) built on the GLM-V encoder–decoder architecture. Layout analysis is handled by **PP-DocLayout-V3**, which detects text blocks, tables, titles, formulas, images, and seals before the OCR model processes each region in parallel.

---

## Prerequisites

- **Python 3.11 or 3.12** with [UV package manager](https://docs.astral.sh/uv/getting-started/installation/) (UV is optional — plain `python -m venv` also works)
- **GPU** with sufficient VRAM (recommended: 24 GB+ for vLLM serving)
- **Docker** (optional, for containerized vLLM deployment)

---

## Step-by-Step Guide

There are **two equivalent paths** through this stage:

- **Scripted path** — drive every step with the bundled scripts in `../scripts/`. One command per step, all paths CLI-driven, nothing hardcoded. Recommended.
- **Manual path** — invoke the Python scripts directly. Useful when you're debugging or running on an unfamiliar setup.

Both paths run the same underlying code; the scripts are thin wrappers that pass paths and env vars through.

---

### Step 1 — Create the Environment

**Scripted (recommended):**

From the **project root** (one level above `Md_JSON_Extraction/`):

```bash
chmod +x scripts/*.sh
PYTHON_BIN=python3.11 ./scripts/setup_env.sh
```

`setup_env.sh` installs the full Stage 1 + Stage 2 + Frontend stack on Python 3.10+. On Python 3.8/3.9 it falls back to the slim Stage 2 + Frontend profile (Stage 1 won't work without 3.10+).

**Manual:**

```bash
cd Md_JSON_Extraction
uv venv --python 3.12 --seed
source .venv/bin/activate
```

---

### Step 2 — Install Dependencies

This is automatic if you used `setup_env.sh` in Step 1, **except** for the two specialised packages below — vLLM and the bleeding-edge transformers source build are not pinned in `requirements.txt`. Install them once:

```bash
uv pip install -U vllm --torch-backend=auto --extra-index-url https://wheels.vllm.ai/nightly
uv pip install git+https://github.com/huggingface/transformers.git
```

(If you're not using UV, replace `uv pip install` with `pip install`.)

If you ran the manual setup in Step 1, also install the SDK:

```bash
uv pip install -e .
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

Open a **new terminal**, activate the same environment, and run inference on your document.

**Scripted (recommended):**

```bash
PDF_PATH=/abs/path/to/your.pdf ./scripts/run_glmocr_pdf.sh
# or for a folder of PDFs:
PDF_DIR=/abs/path/to/folder/of/pdfs ./scripts/run_glmocr_pdf.sh
```

**Manual:**

```bash
source .venv/bin/activate

# For PDFs:
python run_glmocr_pdf_pages.py \
  --pdf "/path/to/your/document.pdf" \
  --out "./outputs" \
  --mode selfhosted \
  --ocr-host 127.0.0.1 \
  --ocr-port 8080 \
  --keep-images \
  --log-level INFO

# For a folder of images:
python run_glmocr_images.py \
  --image "/path/to/your/images/" \
  --out "./outputs_image" \
  --mode selfhosted \
  --ocr-host 127.0.0.1 \
  --ocr-port 8080 \
  --config "glmocr/config.yaml" \
  --log-level INFO
```

`--image` can be a single image file or a directory containing multiple page images.

---

### Step 5 — Merge Per-Page Outputs

After inference completes, your output directory will contain:

```
outputs/
  <pdf_name>/
    page_0001/
      result.json          ← structured OCR blocks with bounding boxes
      result.md            ← Markdown text output
      imgs/                ← cropped image regions (if layout mode enabled)
    page_0002/
      ...
```

Merge them into the two files Stage 2 needs:

**Scripted (recommended):**

```bash
DOC_DIR=Md_JSON_Extraction/outputs/<pdf_name> ./scripts/merge_glmocr_outputs.sh
```

**Manual:**

```bash
cd Md_JSON_Extraction
python merge_md.py        --doc_dir outputs/<pdf_name> --output_file outputs/<pdf_name>/merged_output.md
python merge_all_docs.py  --doc-dir outputs/<pdf_name>
```

You'll get:
```
outputs/<pdf_name>/merged_output.md
outputs/<pdf_name>/merged.pages.json
```

> Both `merge_md.py` and `merge_all_docs.py` are now fully argparse-driven. No source-file edits, no hardcoded paths.

---

### Step 6 — Proceed to Stage 2 (Pipeline)

Take your merged outputs and go to the **Pipeline** folder to run the structured extraction:

> **📖 Follow the instructions in [`Pipeline/README.md`](../Pipeline/README.md)**

The Pipeline will:
- Load your `merged_output.md` and `merged.pages.json` files
- Extract structured fields using AI + rule-based parsing
- Produce a schema-aligned JSON result

**One-shot end-to-end** (Stage 1 + merge + Stage 2 in a single command):

```bash
PDF_PATH=/abs/path/to/your.pdf \
DOC_TYPE=purchase_order \
./scripts/run_full_pipeline.sh
```

**Come back here after Stage 2 is complete** to run the evaluation frontend.

---

### Step 7 — Frontend Dependencies (Already Installed)

If you ran `./scripts/setup_env.sh` in Step 1, Streamlit / pandas / openpyxl are already in the venv. Otherwise install them now:

```bash
pip install -r ../requirements-frontend.txt
# or directly:
pip install streamlit pandas openpyxl
```

---

### Step 8 — Run the Evaluation Frontend

**Scripted (recommended):**

From the **project root**:

```bash
./scripts/run_frontend.sh                                   # local
PORT=8501 HOST=0.0.0.0 HEADLESS=1 ./scripts/run_frontend.sh # SSH / headless
```

**Manual:**

The Streamlit app must be launched from inside `Md_JSON_Extraction/` so its `from eval_backend import ...` resolves cleanly:

```bash
cd Md_JSON_Extraction
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

You can also override these without editing the YAML — the SDK reads `GLMOCR_*` environment variables. The `run_glmocr_pdf.sh` script wires them through:

```bash
GLMOCR_OCR_API_HOST=192.168.1.50 GLMOCR_OCR_API_PORT=8080 \
  PDF_PATH=/abs/path/to/your.pdf ./scripts/run_glmocr_pdf.sh
```

---

## Troubleshooting

**vLLM server won't start / OOM errors** — GLM-OCR is 0.9B parameters. Reduce `--max-model-len` if you are GPU-constrained.

**502 errors during inference** — The server may still be loading the model. Wait until startup is complete.

**OCR results are poor quality** — Make sure `enable_layout: true` is set in `config.yaml`. Without layout detection, the model misses table boundaries.

**Streamlit can't find `eval_backend`** — Use `./scripts/run_frontend.sh` (it cd's into `Md_JSON_Extraction/` automatically). If running manually, `cd Md_JSON_Extraction` first, then `streamlit run frontend/app.py`.

**`Could not find a version that satisfies transformers>=4.57.0`** — Your Python is older than 3.10. Install Python 3.11/3.12 (deadsnakes on Ubuntu) and re-run `PYTHON_BIN=python3.11 ./scripts/setup_env.sh`.

---

## Summary of Execution Order

```
Terminal 1                          Terminal 2
──────────                          ──────────
Start vLLM server (Step 3)
  ↓ keep running
                                    Run OCR inference (Step 4)
                                    Merge per-page outputs (Step 5)
                                      ↓
                                    ─── Go to Pipeline (Stage 2) ───
                                    ─── Run structured extraction ──
                                    ─── Come back with results ─────
                                      ↓
                                    Run evaluation frontend (Step 8)
                                    Upload & compare (Step 9)
                                    Download Excel reports
```

For a fresh machine the whole flow collapses into:

```bash
# Terminal 1
vllm serve zai-org/GLM-OCR --port 8080 --served-model-name glm-ocr --allowed-local-media-path /

# Terminal 2 (project root)
PYTHON_BIN=python3.11 ./scripts/setup_env.sh
ollama serve &                   # if not already running
ollama pull qwen2.5:32b           # one-time
PDF_PATH=/abs/path/to/your.pdf DOC_TYPE=purchase_order ./scripts/run_full_pipeline.sh
./scripts/run_frontend.sh
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
