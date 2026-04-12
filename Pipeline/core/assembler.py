"""
core/assembler.py
-----------------
Assembles extracted scalar values and lists into the nested GT JSON structure.
The assembler is pure data-wiring — no LLM calls here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schema_parser import FieldNode, ParsedSchema


class JSONAssembler:
    """
    Takes individual field extractions and stitches them into
    a single nested dict matching the GT schema.

    Usage:
        assembler = JSONAssembler(schema)
        assembler.set_scalar("exporter_name", "Acme Corp")
        assembler.set_list("items", [{...}, {...}])
        result = assembler.build()
    """

    def __init__(self, schema: ParsedSchema):
        self._schema = schema
        self._scalars: Dict[str, Any] = {}          # path → value
        self._lists: Dict[str, List[Dict]] = {}      # list_root.path → list

    def set_scalar(self, path: str, value: Any) -> None:
        self._scalars[path] = value

    def set_list(self, path: str, items: List[Dict[str, Any]]) -> None:
        self._lists[path] = items

    def build(self) -> Dict[str, Any]:
        """Construct and return the assembled JSON."""
        result = self._schema.build_empty_template()

        # Fill scalars
        for path, value in self._scalars.items():
            _deep_set(result, path, value)

        # Fill lists
        for path, items in self._lists.items():
            _deep_set(result, path, items)

        return result


# ──────────────────────────────────────────────────────────────────────────── #
# Utility
# ──────────────────────────────────────────────────────────────────────────── #

def _deep_set(d: dict, path: str, value: Any) -> None:
    """Set value at a dot-notation path (ignores [] markers)."""
    clean = path.replace("[]", "")
    parts = clean.split(".")
    cur = d
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
