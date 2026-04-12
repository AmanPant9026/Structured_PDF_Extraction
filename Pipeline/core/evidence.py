"""
core/evidence.py
----------------
Converts the two raw inputs (loose JSON + markdown) into a unified
internal evidence store that the retriever can query.

Key concepts
------------
EvidenceBlock   – smallest addressable unit of evidence (one OCR block,
                  one table, one MD paragraph, one MD table row, etc.)
EvidenceStore   – collection of EvidenceBlocks with lookup methods.
EvidenceKind    – enum tag so retriever knows what type of block it has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup


# ──────────────────────────────────────────────────────────────────────────── #
# Data types
# ──────────────────────────────────────────────────────────────────────────── #

class EvidenceKind(str, Enum):
    TEXT = "text"          # plain text paragraph
    TABLE = "table"        # HTML/structured table
    TABLE_ROW = "table_row"  # single row extracted from a table
    TITLE = "title"        # heading / label
    MD_TEXT = "md_text"    # text block sourced from markdown
    MD_TABLE = "md_table"  # table block sourced from markdown


@dataclass
class EvidenceBlock:
    """
    A single addressable piece of evidence.

    Fields
    ------
    block_id    : unique id within the store
    kind        : EvidenceKind tag
    content     : raw string content (text or HTML)
    source      : 'json' or 'markdown'
    page        : source page index (0-based)
    bbox        : optional bounding box [x1, y1, x2, y2] from OCR JSON
    row_index   : for TABLE_ROW, the row number within its parent table
    parent_id   : for TABLE_ROW, the block_id of the parent TABLE block
    metadata    : arbitrary extra data (section name, native_label, etc.)
    """

    block_id: str
    kind: EvidenceKind
    content: str
    source: str                          # 'json' | 'markdown'
    page: int = 0
    bbox: Optional[List[int]] = None
    row_index: Optional[int] = None
    parent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def plain_text(self) -> str:
        """Return a clean plain-text version (strips HTML tags)."""
        if not self.content:
            return ""
        if "<" in self.content and ">" in self.content:
            return BeautifulSoup(self.content, "html.parser").get_text(" ", strip=True)
        return self.content.strip()


@dataclass
class EvidenceStore:
    """
    Collection of EvidenceBlocks with fast lookup helpers.
    """

    blocks: List[EvidenceBlock] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Build helpers
    # ------------------------------------------------------------------ #

    def add(self, block: EvidenceBlock) -> None:
        self.blocks.append(block)

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #

    def by_kind(self, *kinds: EvidenceKind) -> List[EvidenceBlock]:
        return [b for b in self.blocks if b.kind in kinds]

    def by_page(self, page: int) -> List[EvidenceBlock]:
        return [b for b in self.blocks if b.page == page]

    def by_source(self, source: str) -> List[EvidenceBlock]:
        return [b for b in self.blocks if b.source == source]

    def search(self, keyword: str, case_sensitive: bool = False) -> List[EvidenceBlock]:
        """Return blocks whose plain_text contains keyword."""
        kw = keyword if case_sensitive else keyword.lower()
        results = []
        for b in self.blocks:
            txt = b.plain_text()
            haystack = txt if case_sensitive else txt.lower()
            if kw in haystack:
                results.append(b)
        return results

    def all_text(self, separator: str = "\n\n") -> str:
        """Concatenate all block plain texts — useful for full-doc prompting."""
        return separator.join(b.plain_text() for b in self.blocks)

    def __len__(self) -> int:
        return len(self.blocks)


# ──────────────────────────────────────────────────────────────────────────── #
# Builder function
# ──────────────────────────────────────────────────────────────────────────── #

def build_evidence_store(
    json_pages: List[List[Dict[str, Any]]],
    markdown: str,
) -> EvidenceStore:
    """
    Unified entry point: merge OCR JSON blocks + markdown into one store.

    Args:
        json_pages:  list-of-pages, each page is a list of OCR block dicts.
        markdown:    full document markdown string.

    Returns:
        EvidenceStore ready for retrieval.
    """
    store = EvidenceStore()
    _ingest_json_blocks(store, json_pages)
    _ingest_markdown(store, markdown)
    return store


# ──────────────────────────────────────────────────────────────────────────── #
# Private helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _ingest_json_blocks(
    store: EvidenceStore,
    json_pages: List[List[Dict[str, Any]]],
) -> None:
    """Parse OCR JSON blocks page-by-page and add to store."""
    for page_idx, page_blocks in enumerate(json_pages):
        for block in page_blocks:
            idx = block.get("index", 0)
            label = block.get("label", "text")
            native = block.get("native_label", label)
            content = block.get("content", "")
            bbox = block.get("bbox_2d")

            if label == "table":
                kind = EvidenceKind.TABLE
                table_id = f"json_p{page_idx}_b{idx}"
                store.add(EvidenceBlock(
                    block_id=table_id,
                    kind=kind,
                    content=content,
                    source="json",
                    page=page_idx,
                    bbox=bbox,
                    metadata={"native_label": native},
                ))
                # Also explode table rows for fine-grained retrieval
                _explode_table_rows(store, table_id, content, page_idx)
            else:
                kind = EvidenceKind.TITLE if "title" in native else EvidenceKind.TEXT
                store.add(EvidenceBlock(
                    block_id=f"json_p{page_idx}_b{idx}",
                    kind=kind,
                    content=content,
                    source="json",
                    page=page_idx,
                    bbox=bbox,
                    metadata={"native_label": native},
                ))


def _explode_table_rows(
    store: EvidenceStore,
    parent_id: str,
    html: str,
    page: int,
) -> None:
    """Parse an HTML table and add each row as a TABLE_ROW block."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for row_i, tr in enumerate(soup.find_all("tr")):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if not cells:
                continue
            row_text = " | ".join(cells)
            store.add(EvidenceBlock(
                block_id=f"{parent_id}_row{row_i}",
                kind=EvidenceKind.TABLE_ROW,
                content=row_text,
                source="json",
                page=page,
                row_index=row_i,
                parent_id=parent_id,
            ))
    except Exception:
        pass  # malformed HTML — skip row explosion silently


def _ingest_markdown(store: EvidenceStore, markdown: str) -> None:
    """
    Split markdown into paragraphs and embedded HTML tables, add to store.
    Embedded <table> blocks are parsed as MD_TABLE; everything else as MD_TEXT.
    """
    # Split on blank lines, preserving table blocks
    table_pattern = re.compile(r"(<table[\s\S]*?</table>)", re.IGNORECASE)
    parts = table_pattern.split(markdown)

    md_idx = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue

        if table_pattern.match(part):
            store.add(EvidenceBlock(
                block_id=f"md_table_{md_idx}",
                kind=EvidenceKind.MD_TABLE,
                content=part,
                source="markdown",
                page=0,
            ))
        else:
            # Further split on double newline to get paragraphs
            for para in re.split(r"\n{2,}", part):
                para = para.strip()
                if para:
                    store.add(EvidenceBlock(
                        block_id=f"md_text_{md_idx}",
                        kind=EvidenceKind.MD_TEXT,
                        content=para,
                        source="markdown",
                        page=0,
                    ))
                    md_idx += 1
        md_idx += 1
