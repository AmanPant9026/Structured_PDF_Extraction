# Developer Run Guide

A script-by-script reference for the complete pipeline. The root `README.md` has the conceptual overview; this file is the practical "how do I drive it" companion.

All scripts live in `scripts/` and are driven by environment variables and CLI flags. Nothing in any Python file needs to be edited — renaming the repo or moving it to a different machine will not break anything.

---

## 1. File layout

After dropping in the run-layer files, the project root looks like this:

```text
project-root/
├── Md_JSON_Extraction/                    # Stage 1 (OCR) + Streamlit eval frontend
├── Pipeline/                              # Stage 2 (structured extraction)
├── README.md
├── README_RUN.md                          # this file
├── requirements.txt                       # full stack (Py 3.10+)
├── requirements-frontend.txt              # streamlit/pandas/openpyxl, Py 3.8 markers
└── scripts/
    ├── setup_env.sh
    ├── clean.sh
    ├── check_ollama.sh
    ├── run_stage2.sh
    ├── run_purchase_order.sh
    ├── run_shipping_bill.sh
    ├── run_all_sample.sh
    ├── run_glmocr_pdf.sh
    ├── merge_glmocr_outputs.sh
    ├── run_full_pipeline.sh
    └── run_frontend.sh
```

---

## 2. Permissions

```bash
chmod +x scripts/*.sh
```

---

## 3. One-time environment setup

```bash
./scripts/setup_env.sh
```

`setup_env.sh` auto-detects the Python version on `python3` and picks a profile:

| Detected Python | Profile installed | Notes |
|---|---|---|
| 3.10+ | **full** — Stage 1 + Stage 2 + Frontend | Installs `requirements.txt` and editable-installs `Md_JSON_Extraction/`. |
| 3.8 / 3.9 | **2** — Stage 2 + Frontend only | Skips `transformers` / `torch` / `vLLM` (those need Python ≥ 3.10). |

Useful overrides:

```bash
STAGE=2     ./scripts/setup_env.sh             # force slim install
STAGE=full  ./scripts/setup_env.sh             # force full stack (errors if Python < 3.10)
PYTHON_BIN=python3.11 ./scripts/setup_env.sh   # use a specific interpreter
CLEAN=1     ./scripts/setup_env.sh             # nuke .venv first and rebuild
NO_FRONTEND=1 ./scripts/setup_env.sh           # skip streamlit/pandas/openpyxl
VENV_DIR=.venv-dev ./scripts/setup_env.sh      # custom venv directory
```

`setup_env.sh` also removes the legacy `Pipeline/{core,adapters,...` garbage directory if it exists (it was created by an old `mkdir` ran under `sh` instead of `bash`).

---

## 4. Start Ollama (Stage 2)

In a separate terminal:

```bash
ollama serve
```

Pull the model once:

```bash
ollama pull qwen2.5:32b
```

For faster iteration on a weaker box:

```bash
ollama pull qwen2.5:7b
# then for any run:
OLLAMA_MODEL=qwen2.5:7b ./scripts/run_purchase_order.sh
```

`./scripts/check_ollama.sh` verifies the daemon is reachable and auto-pulls the model if it's missing.

---

## 5. Run Stage 2 on the bundled samples

The repo ships pre-OCR'd merged outputs in `Pipeline/data/sample/`, so this works immediately after `setup_env.sh`:

```bash
./scripts/run_purchase_order.sh
./scripts/run_shipping_bill.sh
./scripts/run_all_sample.sh                    # both, with auto-setup
```

Outputs land in `Pipeline/output/`.

---

## 6. Useful Stage-2 flags

```bash
EXTRA_ARGS="--dry-run"  ./scripts/run_purchase_order.sh    # validate inputs, no LLM calls
EXTRA_ARGS="--inspect"  ./scripts/run_purchase_order.sh    # print schema + page structure and exit
EXTRA_ARGS="--list"     ./scripts/run_purchase_order.sh    # list registered doc types
EXTRA_ARGS="--no-cache" ./scripts/run_purchase_order.sh    # force fresh LLM calls (skip cache)
```

`EXTRA_ARGS` accepts multiple flags:

```bash
EXTRA_ARGS="--no-cache --inspect" ./scripts/run_purchase_order.sh
```

---

## 7. Run Stage 2 on your own merged files

```bash
DOC_TYPE=purchase_order \
MD_PATH=/absolute/path/merged_purchase_order.md \
JSON_PATH=/absolute/path/merged_pages.json \
OUTPUT_PATH=output/custom_result.json \
./scripts/run_stage2.sh
```

`MD_PATH` and `JSON_PATH` may be absolute or relative to `Pipeline/`. `OUTPUT_PATH` is always relative to `Pipeline/` unless absolute.

---

## 8. Stage 1 — GLM-OCR a PDF locally

Requires:

- Python 3.10+ environment with the FULL stack (run `setup_env.sh` on a Py 3.11 box).
- A vLLM server serving GLM-OCR. Example startup (in its own terminal):

  ```bash
  vllm serve zai-org/GLM-OCR \
      --allowed-local-media-path / \
      --port 8080 \
      --served-model-name glm-ocr \
      --speculative-config.method mtp \
      --speculative-config.num_speculative_tokens 1
  ```

Then:

```bash
PDF_PATH=/absolute/path/input.pdf ./scripts/run_glmocr_pdf.sh
# or process a folder of PDFs:
PDF_DIR=/absolute/path/to/folder/of/pdfs ./scripts/run_glmocr_pdf.sh
```

Per-page outputs end up in `Md_JSON_Extraction/outputs/<pdf_name>/page_*/`.

---

## 9. Merge per-page OCR outputs

```bash
DOC_DIR=Md_JSON_Extraction/outputs/<pdf_name> ./scripts/merge_glmocr_outputs.sh
```

This produces:

```text
<pdf_name>/merged_output.md
<pdf_name>/merged.pages.json
```

These are the two files Stage 2 consumes — pass them via `MD_PATH` and `JSON_PATH`.

> The underlying `Md_JSON_Extraction/merge_all_docs.py` is now fully argparse-driven (`--outputs-root` or `--doc-dir`). No paths are hardcoded.

---

## 10. End-to-end one-shot

For a fresh PDF on a Py 3.10+ machine with both vLLM and Ollama running:

```bash
PDF_PATH=/absolute/path/your.pdf \
DOC_TYPE=purchase_order \
./scripts/run_full_pipeline.sh
```

What it does:

1. Stage 1 OCR via `run_glmocr_pdf.sh`
2. Merge per-page outputs via `merge_glmocr_outputs.sh`
3. Stage 2 extraction via `run_stage2.sh`

It prints the path of the final structured JSON and a hint to launch the eval frontend.

To skip Stage 1 (OCR was done elsewhere — you only have the merged files):

```bash
SKIP_OCR=1 SKIP_MERGE=1 \
MD_PATH=/abs/merged_output.md \
JSON_PATH=/abs/merged.pages.json \
DOC_TYPE=purchase_order \
./scripts/run_full_pipeline.sh
```

To skip just the merge step (Stage 1 already produced merged outputs):

```bash
SKIP_OCR=1 \
DOC_DIR=Md_JSON_Extraction/outputs/<pdf_name> \
DOC_TYPE=purchase_order \
./scripts/run_full_pipeline.sh
```

---

## 11. Streamlit eval frontend

After Stage 2 has produced a result JSON, compare it against your ground truth:

```bash
./scripts/run_frontend.sh
```

For an SSH/headless box (no auto-open browser):

```bash
PORT=8501 HOST=0.0.0.0 HEADLESS=1 ./scripts/run_frontend.sh
```

Open the URL it prints and:

1. Upload your **GT JSON** (or Excel) in the sidebar.
2. Upload your **MyModel prediction** (the Stage-2 output JSON).
3. Optionally upload a **GPT prediction** for 3-way comparison.
4. Click *Evaluate Overlap Recall* / *Build GT↔Pred Alignment Excel* / *Build 3-way Comparison Excel*.
5. Download the color-coded alignment Excel.

The frontend is launched from inside `Md_JSON_Extraction/` automatically (so its `from eval_backend import ...` resolves cleanly).

---

## 12. Reset / clean up

```bash
./scripts/clean.sh
```

Removes:

- `.venv/`
- the legacy `Pipeline/{core,adapters,...` garbage directory
- `__pycache__/` trees
- `*.egg-info/` directories from editable installs

Does **not** touch:

- input PDFs / sample data
- `Pipeline/output/`, `Pipeline/logs/`
- `Md_JSON_Extraction/outputs/` (Stage 1 OCR results)

---

## 13. Quick troubleshooting

| Problem | Cause / fix |
|---|---|
| `Could not find a version that satisfies the requirement transformers>=4.57.0` | Your Python is < 3.10. Run `STAGE=2 ./scripts/setup_env.sh` for the slim profile, or install Py 3.11. |
| `[ERROR] Ollama server is not reachable at http://localhost:11434` | Run `ollama serve` in another terminal. |
| `[ERROR] Markdown file not found …` | Set `MD_PATH` to a path that exists (absolute, or relative to `Pipeline/`). |
| `[ERROR] vLLM server not reachable at http://localhost:8080` | Start `vllm serve zai-org/GLM-OCR …` in another terminal — only needed for Stage 1. |
| `streamlit: command not found` | Frontend deps weren't installed. Re-run `./scripts/setup_env.sh` (default installs them) or `pip install -r requirements-frontend.txt`. |
| Extraction is slow / takes forever on the first run | Expected. The SHA-256 cache is empty on first run; subsequent runs against the same MD/JSON skip already-seen prompts. |
