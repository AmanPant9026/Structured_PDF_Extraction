"""
core/retriever.py
-----------------
Given an EvidenceStore and a target field, return the top-K most
relevant EvidenceBlocks.

Strategy (lightweight, no embedding model required):
  1. Keyword scoring   — count occurrences of field name / aliases in block text
  2. Section scoring   — reward blocks whose section pattern matches the field
  3. Type bonus        — prefer TABLE_ROW for list fields; TEXT for scalar fields
  4. Final ranking     — sort by composite score, return top K

For production: swap `_keyword_score` with a real embedding similarity
function and the code remains unchanged (open/closed principle).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .evidence import EvidenceBlock, EvidenceKind, EvidenceStore
from .schema_parser import FieldNode


# ──────────────────────────────────────────────────────────────────────────── #
# Types
# ──────────────────────────────────────────────────────────────────────────── #

ScoreFn = Callable[[EvidenceBlock, FieldNode], float]


@dataclass
class ScoredBlock:
    block: EvidenceBlock
    score: float

    def __lt__(self, other: "ScoredBlock") -> bool:
        return self.score < other.score


# ──────────────────────────────────────────────────────────────────────────── #
# Retriever
# ──────────────────────────────────────────────────────────────────────────── #

class EvidenceRetriever:
    """
    Retrieves the most relevant EvidenceBlocks for a given FieldNode.

    Args:
        store:           the document's EvidenceStore
        top_k:           number of blocks to return per field
        section_hints:   map of field_name → list of section header strings
                         injected by the document adapter
        extra_scorers:   additional scoring functions to mix in
    """

    def __init__(
        self,
        store: EvidenceStore,
        top_k: int = 5,
        section_hints: Optional[Dict[str, List[str]]] = None,
        extra_scorers: Optional[List[ScoreFn]] = None,
    ):
        self._store = store
        self._top_k = top_k
        self._section_hints = section_hints or {}
        self._extra_scorers = extra_scorers or []

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def retrieve(self, field: FieldNode) -> List[EvidenceBlock]:
        """Return the top-K blocks most relevant to `field`."""
        scored: List[ScoredBlock] = []
        for block in self._store.blocks:
            s = self._score(block, field)
            if s > 0:
                scored.append(ScoredBlock(block=block, score=s))

        scored.sort(key=lambda x: x.score, reverse=True)
        return [sb.block for sb in scored[: self._top_k]]

    def retrieve_for_list(self, list_root: FieldNode) -> List[EvidenceBlock]:
        """
        For list fields: return TABLE / TABLE_ROW blocks first,
        then fall back to text blocks containing list-like content.
        """
        table_blocks = [
            b for b in self._store.blocks
            if b.kind in (EvidenceKind.TABLE, EvidenceKind.MD_TABLE)
        ]
        if table_blocks:
            return table_blocks[: self._top_k]

        row_blocks = [
            b for b in self._store.blocks
            if b.kind == EvidenceKind.TABLE_ROW
        ]
        if row_blocks:
            return row_blocks[: self._top_k * 3]  # more rows for list items

        # fallback: text blocks containing field aliases
        return self.retrieve(list_root)

    # ------------------------------------------------------------------ #
    # Scoring
    # ------------------------------------------------------------------ #

    def _score(self, block: EvidenceBlock, field: FieldNode) -> float:
        score = 0.0
        score += _keyword_score(block, field)
        score += _section_score(block, field, self._section_hints)
        score += _type_bonus(block, field)
        for scorer in self._extra_scorers:
            score += scorer(block, field)
        return score


# ──────────────────────────────────────────────────────────────────────────── #
# Built-in scoring functions
# ──────────────────────────────────────────────────────────────────────────── #

def _keyword_score(block: EvidenceBlock, field: FieldNode) -> float:
    """
    Score based on how many times the field name or its aliases
    appear in the block text (case-insensitive).
    """
    text = block.plain_text().lower()
    keywords = [field.name.lower().replace("_", " ")] + [a.lower() for a in field.aliases]
    score = 0.0
    for kw in keywords:
        count = text.count(kw)
        if count:
            score += min(count * 1.5, 6.0)  # cap per-keyword bonus
    return score


def _section_score(
    block: EvidenceBlock,
    field: FieldNode,
    section_hints: Dict[str, List[str]],
) -> float:
    """
    Reward blocks that are in a relevant section.
    section_hints[field_name] = ["EXPORTER DETAILS", "SHIPPER"]
    """
    hints = section_hints.get(field.name, [])
    if not hints:
        return 0.0
    text = block.plain_text().upper()
    for hint in hints:
        if hint.upper() in text:
            return 3.0
    return 0.0


def _type_bonus(block: EvidenceBlock, field: FieldNode) -> float:
    """
    Give a bonus when the block type aligns with what the field likely needs.
    """
    if field.is_list:
        if block.kind in (EvidenceKind.TABLE, EvidenceKind.MD_TABLE):
            return 4.0
        if block.kind == EvidenceKind.TABLE_ROW:
            return 2.0
    else:
        if block.kind in (EvidenceKind.TEXT, EvidenceKind.MD_TEXT, EvidenceKind.TITLE):
            return 1.0
    return 0.0
