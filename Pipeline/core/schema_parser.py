"""
core/schema_parser.py
---------------------
Parses the Ground-Truth (GT) schema JSON and exposes:

  - A tree of FieldNode objects (one per schema leaf / list-root)
  - Helper methods to enumerate extraction targets
  - Empty template builder (filled-in by the assembler)

GT Schema format (our convention):
{
  "document_type": "shipping_bill",
  "version": "1.0",
  "fields": {
    "exporter_name": { "type": "string", "required": true, "description": "..." },
    "items": {
      "type": "list",
      "list_root": true,
      "description": "...",
      "items": {
        "hs_code":    { "type": "string" },
        "quantity":   { "type": "number" },
        "unit_price": { "type": "number" }
      }
    }
  }
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────── #
# Data types
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class FieldNode:
    """
    Represents one node in the schema tree.

    Attributes
    ----------
    path        : dot-notation path from root, e.g. "items.hs_code"
    name        : local field name, e.g. "hs_code"
    dtype       : 'string' | 'number' | 'boolean' | 'list' | 'object'
    required    : whether GT requires this field
    list_root   : True when this node is the root of a repeating list
    description : human-readable hint used in LLM prompt
    children    : child FieldNodes for object / list types
    aliases     : alternative names the field may appear as in the document
    """

    path: str
    name: str
    dtype: str = "string"
    required: bool = False
    list_root: bool = False
    description: str = ""
    children: List[FieldNode] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_list(self) -> bool:
        return self.dtype == "list" or self.list_root

    def leaves(self) -> Iterator[FieldNode]:
        """Yield all leaf descendants (depth-first)."""
        if self.is_leaf:
            yield self
        else:
            for child in self.children:
                yield from child.leaves()

    def list_item_leaves(self) -> List[FieldNode]:
        """
        For a list_root node: return its item-level leaves.
        These are extracted once per list item, not once per document.
        """
        if not self.is_list:
            return []
        return [c for child in self.children for c in child.leaves()]


@dataclass
class ParsedSchema:
    """Top-level schema container after parsing."""
    document_type: str
    version: str
    root_fields: List[FieldNode]          # top-level non-list leaves
    list_roots: List[FieldNode]           # list-root nodes

    def all_leaves(self) -> Iterator[FieldNode]:
        """Yield every scalar leaf (including those inside lists)."""
        for fn in self.root_fields:
            yield from fn.leaves()
        for lr in self.list_roots:
            yield from lr.list_item_leaves()

    def build_empty_template(self) -> Dict[str, Any]:
        """
        Return an empty dict matching the GT schema structure.
        Scalars → None; lists → [].
        """
        result: Dict[str, Any] = {}
        for fn in self.root_fields:
            _set_path(result, fn.path, None)
        for lr in self.list_roots:
            _set_path(result, lr.path, [])
        return result


# ──────────────────────────────────────────────────────────────────────────── #
# Public entry point
# ──────────────────────────────────────────────────────────────────────────── #

def load_schema(schema_path: str) -> ParsedSchema:
    """Load and parse a GT schema JSON file."""
    raw = json.loads(Path(schema_path).read_text())
    return _parse_schema(raw)


def parse_schema_dict(raw: Dict[str, Any]) -> ParsedSchema:
    """Parse an already-loaded schema dict."""
    return _parse_schema(raw)


# ──────────────────────────────────────────────────────────────────────────── #
# Private parser
# ──────────────────────────────────────────────────────────────────────────── #

def _parse_schema(raw: Dict[str, Any]) -> ParsedSchema:
    doc_type = raw.get("document_type", "unknown")
    version = raw.get("version", "1.0")
    fields_dict = raw.get("fields", {})

    root_fields: List[FieldNode] = []
    list_roots: List[FieldNode] = []

    for name, spec in fields_dict.items():
        node = _parse_field(name, name, spec)
        if node.is_list:
            list_roots.append(node)
        else:
            root_fields.append(node)

    return ParsedSchema(
        document_type=doc_type,
        version=version,
        root_fields=root_fields,
        list_roots=list_roots,
    )


def _parse_field(name: str, path: str, spec: Dict[str, Any]) -> FieldNode:
    dtype = spec.get("type", "string")
    required = spec.get("required", False)
    list_root = spec.get("list_root", False)
    description = spec.get("description", "")
    aliases = spec.get("aliases", [])

    node = FieldNode(
        path=path,
        name=name,
        dtype=dtype,
        required=required,
        list_root=list_root,
        description=description,
        aliases=aliases,
    )

    # Recurse into nested object fields
    if dtype == "object" and "fields" in spec:
        for child_name, child_spec in spec["fields"].items():
            child_path = f"{path}.{child_name}"
            node.children.append(_parse_field(child_name, child_path, child_spec))

    # Recurse into list item fields
    if (dtype == "list" or list_root) and "items" in spec:
        item_spec = spec["items"]
        items_node = FieldNode(path=f"{path}[]", name="__items__", dtype="object")
        for child_name, child_spec in item_spec.items():
            child_path = f"{path}[].{child_name}"
            items_node.children.append(_parse_field(child_name, child_path, child_spec))
        node.children.append(items_node)

    return node


# ──────────────────────────────────────────────────────────────────────────── #
# Utility
# ──────────────────────────────────────────────────────────────────────────── #

def _set_path(d: dict, path: str, value: Any) -> None:
    """Set a value at a dot-notation path in a nested dict."""
    # Strip list-marker for template building
    clean = path.replace("[]", "")
    parts = clean.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
