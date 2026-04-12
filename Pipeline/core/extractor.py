"""
core/extractor.py
-----------------
Base extractor interface + shared prompt-building utilities.

The ONLY extractor used in this framework is OllamaExtractor (Apache 2.0).
This module contains:
  - BaseExtractor   : abstract interface — implement to swap models
  - Shared helpers  : prompt builders, response parsers, evidence text builder

To use a different open-source model, subclass BaseExtractor and implement
extract_scalar() and extract_list().  See core/ollama_extractor.py for the
reference implementation (Qwen2.5:32b via Ollama).

No proprietary API is imported, referenced, or required.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .evidence import EvidenceBlock
from .logger import FrameworkLogger
from .schema_parser import FieldNode


# ──────────────────────────────────────────────────────────────────────────── #
# Abstract interface
# ──────────────────────────────────────────────────────────────────────────── #

class BaseExtractor(ABC):
    """
    Abstract base for all LLM extractors.

    Implement this to plug in any open-source model.
    The rest of the pipeline never changes.
    """

    @abstractmethod
    def extract_scalar(
        self,
        field: FieldNode,
        evidence_blocks: List[EvidenceBlock],
        doc_type: str,
    ) -> Optional[Any]:
        """Extract a single scalar value from evidence blocks."""
        ...

    @abstractmethod
    def extract_list(
        self,
        list_root: FieldNode,
        evidence_blocks: List[EvidenceBlock],
        doc_type: str,
    ) -> List[Dict[str, Any]]:
        """Extract a full list (e.g. line items) from evidence blocks."""
        ...


# ──────────────────────────────────────────────────────────────────────────── #
# Shared prompt builders (used by OllamaExtractor and any future extractor)
# ──────────────────────────────────────────────────────────────────────────── #

def _build_scalar_prompt(
    field: FieldNode,
    evidence_text: str,
    doc_type: str,
) -> str:
    aliases = (
        f"This field may also appear as: {', '.join(field.aliases)}.\n"
        if field.aliases else ""
    )
    desc = f"Description: {field.description}\n" if field.description else ""
    dtype_hint = _dtype_hint(field.dtype)

    return (
        f"Document type: {doc_type}\n"
        f"Target field: {field.path}\n"
        f"{desc}{aliases}"
        f"Extract the value of this field from the evidence below.\n"
        f"{dtype_hint}\n"
        f'Return ONLY a JSON object: {{"value": <extracted_value>}}\n'
        f'If not found, return: {{"value": null}}\n\n'
        f"--- EVIDENCE ---\n{evidence_text}\n--- END EVIDENCE ---"
    )


def _build_list_prompt(
    list_root: FieldNode,
    item_leaves: List[FieldNode],
    evidence_text: str,
    doc_type: str,
) -> str:
    field_defs = "\n".join(
        f"  - {leaf.name} ({leaf.dtype})"
        + (f": {leaf.description}" if leaf.description else "")
        + (f" [also: {', '.join(leaf.aliases)}]" if leaf.aliases else "")
        for leaf in item_leaves
    )
    desc = f"Description: {list_root.description}\n" if list_root.description else ""

    return (
        f"Document type: {doc_type}\n"
        f"Target: Extract all rows for the list '{list_root.name}'\n"
        f"{desc}\n"
        f"Each row should contain these fields:\n{field_defs}\n\n"
        f"Return ONLY a JSON array of objects. Example:\n"
        f'[{{"field1": "value1", "field2": "value2"}}, ...]\n'
        f"If no items found return: []\n\n"
        f"--- EVIDENCE ---\n{evidence_text}\n--- END EVIDENCE ---"
    )


# ──────────────────────────────────────────────────────────────────────────── #
# Shared response parsers
# ──────────────────────────────────────────────────────────────────────────── #

def _parse_scalar_response(raw: str, field: FieldNode) -> Optional[Any]:
    """Parse {"value": ...} response, coerce to correct type."""
    try:
        clean = _strip_fences(raw)
        data = json.loads(clean)
        value = data.get("value")
        if value is None:
            return None
        return _coerce(value, field.dtype)
    except (json.JSONDecodeError, AttributeError, KeyError):
        stripped = raw.strip().strip('"')
        return stripped if stripped not in ("null", "None", "") else None


def _parse_list_response(raw: str) -> List[Dict[str, Any]]:
    """Parse JSON array response."""
    try:
        clean = _strip_fences(raw)
        data = json.loads(clean)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "rows", "data", "results"):
                if key in data and isinstance(data[key], list):
                    return data[key]
    except (json.JSONDecodeError, AttributeError):
        pass
    return []


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` fences if present."""
    return re.sub(r"^```(?:json)?\n?|```$", "", text.strip(), flags=re.MULTILINE).strip()


def _coerce(value: Any, dtype: str) -> Any:
    if dtype == "number":
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return value
    if dtype == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "yes", "1")
    return value


def _dtype_hint(dtype: str) -> str:
    hints = {
        "number": "The value should be a numeric type (integer or float).",
        "boolean": "The value should be true or false.",
        "string": "The value should be a string.",
    }
    return hints.get(dtype, "")


def _build_evidence_text(blocks: List[EvidenceBlock], max_chars: int = 4000) -> str:
    """Concatenate block plain texts, truncating to max_chars total."""
    parts: List[str] = []
    total = 0
    for block in blocks:
        txt = block.plain_text()
        if total + len(txt) > max_chars:
            remaining = max_chars - total
            if remaining > 100:
                parts.append(txt[:remaining] + "…")
            break
        parts.append(txt)
        total += len(txt)
    return "\n\n".join(parts)
