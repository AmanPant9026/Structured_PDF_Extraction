#!/usr/bin/env python3
"""
run_glmocr_pdf_pages.py

Input: a PDF file OR a directory containing PDFs.
Output:
  OUT_ROOT/
    <pdf_name>/
      <pdf_name>.pdf                 (optional copy)
      page_0001/
        result.json
        result.md
        page_0001.png                (if --keep-images)
      page_0002/
        ...

Works with:
- MaaS (cloud): --mode maas --api-key ...
- Self-hosted: --mode selfhosted --ocr-host ... --ocr-port ... (vLLM/SGLang)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from glmocr import GlmOcr


def sanitize_folder_name(name: str) -> str:
    # Keep it readable but safe across filesystems
    name = name.strip()
    name = name.replace(os.sep, "_")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)  # windows-illegal + control chars
    name = re.sub(r"\s+", " ", name)  # collapse whitespace
    return name or "document"


def render_page_to_image(doc: fitz.Document, page_index: int, out_image_path: Path, dpi: int) -> None:
    """Render a single PDF page to an image file."""
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    out_image_path.parent.mkdir(parents=True, exist_ok=True)
    ext = out_image_path.suffix.lower()

    if ext == ".png":
        pix.save(str(out_image_path))
    elif ext in [".jpg", ".jpeg"]:
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.save(str(out_image_path), format="JPEG", quality=95, optimize=True)
    else:
        raise ValueError(f"Unsupported image extension: {ext}")


def safe_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def process_one_pdf(
    pdf_path: Path,
    out_root: Path,
    dpi: int,
    image_format: str,
    start_page: int,
    end_page: int,
    keep_images: bool,
    fail_fast: bool,
    copy_pdf: bool,
    ocr: GlmOcr,
) -> None:
    pdf_path = pdf_path.resolve()
    pdf_name = sanitize_folder_name(pdf_path.stem)
    pdf_out_dir = out_root / pdf_name
    pdf_out_dir.mkdir(parents=True, exist_ok=True)

    if copy_pdf:
        # Copy PDF into its output folder (so outputs are self-contained)
        dst_pdf = pdf_out_dir / pdf_path.name
        if dst_pdf.resolve() != pdf_path:
            shutil.copy2(pdf_path, dst_pdf)

    doc = fitz.open(pdf_path)
    try:
        n_pages = doc.page_count
        s = max(1, start_page)
        e = end_page if end_page and end_page > 0 else n_pages
        e = min(e, n_pages)

        if s > e:
            raise ValueError(f"Invalid page range: start={s}, end={e}, total_pages={n_pages}")

        print(f"\n[INFO] Processing PDF: {pdf_path.name} | pages={n_pages} | range={s}..{e}")
        print(f"[INFO] Output folder: {pdf_out_dir}")

        for p in range(s, e + 1):
            page_index0 = p - 1
            page_dir = pdf_out_dir / f"page_{p:04d}"
            page_dir.mkdir(parents=True, exist_ok=True)

            img_ext = ".png" if image_format == "png" else ".jpg"
            img_path = page_dir / f"page_{p:04d}{img_ext}"

            try:
                print(f"\n[PAGE {p}/{e}] render -> {img_path.name}")
                render_page_to_image(doc, page_index0, img_path, dpi=dpi)

                print(f"[PAGE {p}/{e}] GLM-OCR parse...")
                result = ocr.parse(str(img_path))

                # Saves: result.json, result.md, imgs/ (if layout enabled)
                result.save(output_dir=str(page_dir))

                # Optional extra debug dump (ignore if not supported)
                try:
                    safe_write_json(page_dir / "result.full.to_dict.json", result.to_dict())
                except Exception:
                    pass

                if not keep_images:
                    try:
                        img_path.unlink(missing_ok=True)
                    except Exception:
                        pass

                print(f"[PAGE {p}/{e}] done ✅ -> {page_dir}")

            except Exception as ex:
                print(f"[ERROR] Page {p} failed: {ex}", file=sys.stderr)
                if fail_fast:
                    raise
                continue

    finally:
        doc.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run GLM-OCR on PDFs (page-by-page).")

    inp = ap.add_mutually_exclusive_group(required=True)
    inp.add_argument("--pdf", help="Path to a single PDF")
    inp.add_argument("--pdf-dir", help="Path to a directory containing PDFs")

    ap.add_argument("--out", default="./outputs", help="Output ROOT folder (default: ./outputs)")
    ap.add_argument("--dpi", type=int, default=300, help="Render DPI (default: 300)")
    ap.add_argument("--image-format", choices=["png", "jpg"], default="png", help="Rendered page image format")
    ap.add_argument("--start-page", type=int, default=1, help="1-based start page (default: 1)")
    ap.add_argument("--end-page", type=int, default=0, help="1-based end page inclusive (0 = till last)")
    ap.add_argument("--keep-images", action="store_true", help="Keep rendered page images inside each page folder")
    ap.add_argument("--fail-fast", action="store_true", help="Stop on first failure")
    ap.add_argument("--copy-pdf", action="store_true", help="Copy input PDF into its output folder")

    # GLM-OCR runtime
    ap.add_argument("--mode", choices=["maas", "selfhosted"], default=None, help="GLM-OCR mode")
    ap.add_argument("--api-key", default=None, help="MaaS API key (if mode=maas)")
    ap.add_argument("--config", default=None, help="Path to config.yaml (optional)")
    ap.add_argument("--enable-layout", action="store_true", help="Enable layout detection (if available)")
    ap.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR")

    # Self-hosted OCR API location (vLLM/SGLang)
    ap.add_argument("--ocr-host", default=None, help="Selfhosted OCR API host (e.g., localhost)")
    ap.add_argument("--ocr-port", type=int, default=None, help="Selfhosted OCR API port (e.g., 8080)")

    args = ap.parse_args()

    out_root = Path(args.out).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # Set env overrides (SDK reads GLMOCR_*). Works even if you don't pass kwargs.
    if args.mode:
        os.environ["GLMOCR_MODE"] = args.mode
    if args.api_key:
        os.environ["GLMOCR_API_KEY"] = args.api_key
    if args.log_level:
        os.environ["GLMOCR_LOG_LEVEL"] = args.log_level
    if args.enable_layout:
        os.environ["GLMOCR_ENABLE_LAYOUT"] = "true"
    if args.ocr_host:
        os.environ["GLMOCR_OCR_API_HOST"] = args.ocr_host
    if args.ocr_port is not None:
        os.environ["GLMOCR_OCR_API_PORT"] = str(args.ocr_port)

    # Build parser once and reuse
    parser_kwargs = {}
    if args.config:
        parser_kwargs["config_path"] = str(Path(args.config).expanduser().resolve())
    if args.api_key:
        parser_kwargs["api_key"] = args.api_key
    if args.mode:
        parser_kwargs["mode"] = args.mode
    if args.enable_layout:
        parser_kwargs["enable_layout"] = True
    if args.log_level:
        parser_kwargs["log_level"] = args.log_level

    # Collect PDFs
    pdfs: list[Path] = []
    if args.pdf:
        p = Path(args.pdf).expanduser()
        if not p.exists():
            print(f"[ERROR] PDF not found: {p}", file=sys.stderr)
            return 2
        pdfs = [p]
    else:
        d = Path(args.pdf_dir).expanduser()
        if not d.exists() or not d.is_dir():
            print(f"[ERROR] Not a directory: {d}", file=sys.stderr)
            return 2
        pdfs = sorted(d.glob("*.pdf"))
        if not pdfs:
            print(f"[ERROR] No PDFs found in: {d}", file=sys.stderr)
            return 2

    print(f"[INFO] Output ROOT: {out_root}")
    print(f"[INFO] PDFs to process: {len(pdfs)}")

    try:
        with GlmOcr(**parser_kwargs) as ocr:
            for pdf_path in pdfs:
                try:
                    process_one_pdf(
                        pdf_path=pdf_path,
                        out_root=out_root,
                        dpi=args.dpi,
                        image_format=args.image_format,
                        start_page=args.start_page,
                        end_page=args.end_page,
                        keep_images=args.keep_images,
                        fail_fast=args.fail_fast,
                        copy_pdf=args.copy_pdf,
                        ocr=ocr,
                    )
                except Exception as e:
                    print(f"[ERROR] PDF failed: {pdf_path.name}: {e}", file=sys.stderr)
                    if args.fail_fast:
                        return 1
                    continue

        print("\n[INFO] All done ✅")
        return 0

    except Exception as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())