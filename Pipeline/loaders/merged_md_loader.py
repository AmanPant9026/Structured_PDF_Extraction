"""
loaders/merged_md_loader.py
----------------------------
Loads the  merged_purchase_order.md  format whose pages are delimited by:

    <!-- PAGE 1: page_0001.md -->
    ...content...
    <!-- PAGE 2: page_0002.md -->
    ...content...

Returns the same two objects the pipeline always expects:

    json_pages : List[List[Dict]]   — empty lists (OCR blocks not in .md)
    md_pages   : List[str]          — per-page markdown strings
    combined_md: str                — all PM pages joined (T&C stripped)

The .md file has no OCR JSON blocks; that is fine.
The adapter (PurchaseOrderAdapter) works purely from markdown for this input.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# page marker pattern: <!-- PAGE N: filename.md -->
_PAGE_MARKER = re.compile(r"<!--\s*PAGE\s+(\d+)\s*:[^>]*-->", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────── #
# Public API
# ──────────────────────────────────────────────────────────────────────────── #

def load_merged_md(
    path: str,
    tc_page: int = 15,              # first page index (1-based) that is T&C
    page_range: Optional[Tuple[int, int]] = None,  # 1-based inclusive
) -> Tuple[List[List[Dict[str, Any]]], str]:
    """
    Load a merged_purchase_order.md file.

    Args:
        path:       path to merged_purchase_order.md
        tc_page:    first PAGE number (1-based) that contains General T&C.
                    All pages from this number onward are stripped.
        page_range: optional (start, end) 1-based page numbers to keep.
                    Overrides tc_page if provided.

    Returns:
        json_pages      : list of empty lists — one per included page
                          (no OCR JSON in .md files; adapter uses md only)
        combined_markdown: all kept pages joined by \\n\\n---PAGE_BREAK---\\n\\n
    """
    raw = Path(path).read_text(encoding="utf-8")
    pages = _split_pages(raw)          # list of (page_number, content) tuples

    # Filter by range
    if page_range is not None:
        start, end = page_range
        pages = [(n, c) for n, c in pages if start <= n <= end]
    else:
        pages = [(n, c) for n, c in pages if n < tc_page]

    # Build outputs
    json_pages: List[List[Dict]] = [[] for _ in pages]   # empty — no OCR JSON
    combined_md = "\n\n---PAGE_BREAK---\n\n".join(c.strip() for _, c in pages)

    return json_pages, combined_md


def get_page_contents(path: str) -> List[Tuple[int, str]]:
    """
    Return list of (page_number, content) for every page in the file.
    Useful for inspection / debugging.
    """
    raw = Path(path).read_text(encoding="utf-8")
    return _split_pages(raw)


def inspect_merged_md(path: str) -> None:
    """Print a quick summary of every page in the .md file."""
    pages = get_page_contents(path)
    print(f"File        : {path}")
    print(f"Total pages : {len(pages)}")
    print()
    for n, content in pages:
        tables = len(re.findall(r"<table", content, re.IGNORECASE))
        chars  = len(content.strip())
        preview = content.strip()[:60].replace("\n", " ")
        print(f"  PAGE {n:>3} | chars={chars:>5} | tables={tables} | {preview!r}")


# ──────────────────────────────────────────────────────────────────────────── #
# Private
# ──────────────────────────────────────────────────────────────────────────── #

def _split_pages(raw: str) -> List[Tuple[int, str]]:
    """
    Split raw text on <!-- PAGE N: ... --> markers.
    Returns list of (page_number, page_content) tuples, 1-based.
    """
    # Find all marker positions
    markers = list(_PAGE_MARKER.finditer(raw))
    if not markers:
        # No markers found — treat entire file as one page
        return [(1, raw.strip())]

    pages: List[Tuple[int, str]] = []
    for i, m in enumerate(markers):
        page_num = int(m.group(1))
        start    = m.end()                              # just after this marker
        end      = markers[i + 1].start() if i + 1 < len(markers) else len(raw)
        content  = raw[start:end].strip()
        pages.append((page_num, content))

    return pages
