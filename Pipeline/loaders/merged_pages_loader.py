"""
loaders/merged_pages_loader.py
--------------------------------
Normalises the glmocr_pages_merge_v1 format (merged_pages.json) into the
two plain inputs the framework pipeline expects:

    json_pages : List[List[Dict]]   — one list-of-blocks per page
    markdown   : str                — all page markdowns concatenated

Input format (merged_pages.json)
---------------------------------
{
  "schema_version": "glmocr_pages_merge_v1",
  "page_count_merged": 20,
  "pages": [
    {
      "page_number": 0,
      "source_file": "...",
      "data": {
        "json_result":    [[block, block, ...]],   ← nested list-of-list
        "markdown_result": "## PLACEMENT ...",
        "original_images": [...]
      }
    },
    ...
  ]
}

The framework expects json_pages[i] to be a flat list of block dicts.
json_result is already [[blocks]] so we just unwrap the outer list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────── #
# Public entry points
# ──────────────────────────────────────────────────────────────────────────── #

def load_merged_pages(
    path: str,
    page_range: Optional[Tuple[int, int]] = None,
    md_separator: str = "\n\n---PAGE_BREAK---\n\n",
) -> Tuple[List[List[Dict[str, Any]]], str]:
    """
    Load a merged_pages.json file and return (json_pages, combined_markdown).

    Args:
        path:         path to merged_pages.json
        page_range:   optional (start, end) inclusive page indices to load;
                      None = load all pages.
        md_separator: string inserted between page markdowns in the
                      combined markdown string.

    Returns:
        json_pages       : list of pages, each a list of OCR block dicts
        combined_markdown: all selected page markdowns joined together
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_merged_pages(raw, page_range=page_range, md_separator=md_separator)


def parse_merged_pages(
    raw: Dict[str, Any],
    page_range: Optional[Tuple[int, int]] = None,
    md_separator: str = "\n\n---PAGE_BREAK---\n\n",
) -> Tuple[List[List[Dict[str, Any]]], str]:
    """
    Parse an already-loaded merged_pages dict.
    Useful when the dict is loaded externally or in tests.
    """
    pages = raw.get("pages", [])

    if page_range is not None:
        start, end = page_range
        pages = pages[start : end + 1]

    json_pages: List[List[Dict[str, Any]]] = []
    md_parts: List[str] = []

    for page_entry in pages:
        data = page_entry.get("data", {})

        # ── OCR JSON blocks ──────────────────────────────────────────── #
        json_result = data.get("json_result", [])
        # json_result is [[block, block, ...]] — unwrap the outer list
        if json_result and isinstance(json_result[0], list):
            blocks = json_result[0]
        elif json_result and isinstance(json_result[0], dict):
            blocks = json_result          # already flat
        else:
            blocks = []
        json_pages.append(blocks)

        # ── Markdown ─────────────────────────────────────────────────── #
        md = data.get("markdown_result", "")
        if md.strip():
            md_parts.append(md.strip())

    combined_markdown = md_separator.join(md_parts)
    return json_pages, combined_markdown


# ──────────────────────────────────────────────────────────────────────────── #
# Section-aware loader
# ──────────────────────────────────────────────────────────────────────────── #

def load_section(
    path: str,
    section: str,
    sections_config: Dict[str, Tuple[int, int]],
    md_separator: str = "\n\n",
) -> Tuple[List[List[Dict[str, Any]]], str]:
    """
    Load only the pages belonging to a named section.

    Args:
        path:            path to merged_pages.json
        section:         section name key (e.g. 'row_wise_table', 'details')
        sections_config: map of section_name → (start_page, end_page)
        md_separator:    separator between page markdowns

    Example:
        json_pages, md = load_section(
            "merged_pages.json",
            "row_wise_table",
            {"row_wise_table": (0, 1), "details": (2, 13)}
        )
    """
    if section not in sections_config:
        raise KeyError(
            f"Section '{section}' not in sections_config. "
            f"Available: {list(sections_config)}"
        )
    page_range = sections_config[section]
    return load_merged_pages(path, page_range=page_range, md_separator=md_separator)


# ──────────────────────────────────────────────────────────────────────────── #
# Introspection helper
# ──────────────────────────────────────────────────────────────────────────── #

def inspect_merged_pages(path: str) -> None:
    """
    Print a summary of every page in a merged_pages.json file.
    Useful for understanding a new document before writing a config.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    pages = raw.get("pages", [])
    from collections import Counter

    print(f"schema_version : {raw.get('schema_version')}")
    print(f"total pages    : {len(pages)}")
    print()

    for i, p in enumerate(pages):
        data = p.get("data", {})
        jr = data.get("json_result", [])
        blocks = jr[0] if jr and isinstance(jr[0], list) else jr
        md_len = len(data.get("markdown_result", ""))
        labels = Counter(b.get("label", "?") for b in blocks)
        print(
            f"  page {i:>2} | "
            f"blocks={len(blocks):>3} {dict(labels)} | "
            f"md={md_len} chars"
        )
