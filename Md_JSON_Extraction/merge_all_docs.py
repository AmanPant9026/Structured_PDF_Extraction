#!/usr/bin/env python3
"""
merge_all_docs.py
==================

For each document folder inside an outputs root, merge its page_* JSONs into:
    <doc_folder>/merged.pages.json

The output is a single JSON file with this shape:
    {
        "schema_version": "glmocr_pages_merge_v1",
        "document_dir":   "<absolute path to the doc folder>",
        "merged_at":      "<iso timestamp>",
        "page_count_merged": <int>,
        "pages": [
            {"page_number": 1, "source_file": "...", "data": {...}},
            ...
        ]
    }

Usage
-----
    # 1) Merge every doc folder under an outputs root:
    python merge_all_docs.py --outputs-root path/to/outputs

    # 2) Merge a single doc folder (skip the per-folder loop):
    python merge_all_docs.py --doc-dir path/to/outputs/<doc_folder>

    # 3) From inside Md_JSON_Extraction/, the default outputs root is ./outputs:
    python merge_all_docs.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────── #
# Helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _load_json(p: Path) -> object:
    return json.loads(p.read_text(encoding="utf-8"))


def _page_num(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 10**9


def merge_one(doc_dir: Path) -> Optional[Path]:
    """
    Merge all page_* JSONs inside one document folder into merged.pages.json.

    Returns the path to the merged file, or None if no page folders were found.
    """
    page_dirs = sorted(
        [p for p in doc_dir.iterdir() if p.is_dir() and p.name.lower().startswith("page")],
        key=lambda p: _page_num(p.name),
    )
    if not page_dirs:
        return None

    pages = []
    for pd in page_dirs:
        pnum = _page_num(pd.name)
        full_p = pd / "result.full.to_dict.json"
        alt_p  = pd / "result.json"
        if full_p.exists():
            chosen = full_p
        elif alt_p.exists():
            chosen = alt_p
        else:
            continue
        pages.append({
            "page_number": pnum,
            "source_file": str(chosen),
            "data": _load_json(chosen),
        })

    merged = {
        "schema_version": "glmocr_pages_merge_v1",
        "document_dir": str(doc_dir),
        "merged_at": datetime.now().isoformat(timespec="seconds"),
        "page_count_merged": len(pages),
        "pages": pages,
    }

    out_path = doc_dir / "merged.pages.json"
    out_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


# ──────────────────────────────────────────────────────────────────────────── #
# CLI
# ──────────────────────────────────────────────────────────────────────────── #

def _build_parser() -> argparse.ArgumentParser:
    # The script lives next to an outputs/ folder by convention:
    #     <Md_JSON_Extraction>/merge_all_docs.py
    #     <Md_JSON_Extraction>/outputs/<doc_folder>/page_0001/...
    here = Path(__file__).resolve().parent
    default_outputs = here / "outputs"

    p = argparse.ArgumentParser(
        description="Merge per-page GLM-OCR JSONs into one merged.pages.json per doc folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--outputs-root",
        type=str,
        default=str(default_outputs),
        help=f"Root folder containing one or more <doc_folder>/page_*/  (default: {default_outputs})",
    )
    g.add_argument(
        "--doc-dir",
        type=str,
        default=None,
        help="Process exactly one document folder (overrides --outputs-root).",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()

    if args.doc_dir:
        doc_dir = Path(args.doc_dir).expanduser().resolve()
        if not doc_dir.exists() or not doc_dir.is_dir():
            print(f"[ERROR] doc-dir not found or not a directory: {doc_dir}", file=sys.stderr)
            return 2
        outp = merge_one(doc_dir)
        if outp:
            print(f"[OK] {doc_dir.name} -> {outp}")
            return 0
        print(f"[SKIP] {doc_dir.name} (no page_* folders)", file=sys.stderr)
        return 1

    outputs_root = Path(args.outputs_root).expanduser().resolve()
    if not outputs_root.exists():
        print(f"[ERROR] outputs root not found: {outputs_root}", file=sys.stderr)
        return 2

    doc_dirs = [d for d in outputs_root.iterdir() if d.is_dir()]
    if not doc_dirs:
        print(f"[ERROR] no document folders inside: {outputs_root}", file=sys.stderr)
        return 2

    rc = 0
    for d in sorted(doc_dirs):
        outp = merge_one(d)
        if outp:
            print(f"[OK] {d.name} -> {outp}")
        else:
            print(f"[SKIP] {d.name} (no page_* folders)")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
