"""
loaders/template_loader.py
---------------------------
Loads the  purchase_order_v1_null_template.json  (all-null output template)
and provides helpers to:

  1. Introspect its structure (what keys exist, what their types are)
  2. Fill it with extracted data section by section
  3. Validate that every non-null value in the filled result maps to a
     real key defined in the template (no extra keys added by accident)

The template is the ONLY source of truth for output shape.
GT / schema JSON are not used.

Template conventions understood by this loader
-----------------------------------------------
  - Every leaf value is null  →  "fill me in"
  - RowWiseTable is a list with exactly ONE null-row prototype
    →  the prototype is replicated for each extracted row
  - Details is a dict with pre-named keys (Item1, Item 2, …, Item 24)
    →  each key maps to the same null-item prototype (except Item 24
       which has extra fields: HSCode, raw, PLIRate, TotalPLIAmount,
       Total Value of Order)
  - source / schema_version are filled by the adapter at finalize time
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────── #
# Public entry points
# ──────────────────────────────────────────────────────────────────────────── #

def load_template(path: str) -> Dict[str, Any]:
    """
    Load a null-template JSON file and return a deep copy ready for filling.

    Args:
        path: path to the template JSON file

    Returns:
        Deep-copied template dict with all leaves set to null
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return copy.deepcopy(raw)


def get_row_wise_prototype(template: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract the single-row prototype from RowWiseTable.
    Returns a deep copy so the original prototype stays clean.
    """
    rows = template.get("RowWiseTable", [{}])
    proto = rows[0] if rows else {}
    return copy.deepcopy(proto)


def get_detail_item_prototype(template: Dict[str, Any], key: str = "Item1") -> Dict[str, Any]:
    """
    Extract a Detail item prototype by key.
    Defaults to 'Item1' which has the standard field set.
    """
    details = template.get("Details", {})
    proto = details.get(key, {})
    return copy.deepcopy(proto)


def list_detail_keys(template: Dict[str, Any]) -> List[str]:
    """Return ordered list of all Details keys (Item1, Item 2, …, Item 24)."""
    return list(template.get("Details", {}).keys())


def fill_template(
    template: Dict[str, Any],
    header: Dict[str, Any],
    row_wise_rows: List[Dict[str, Any]],
    details_1: Dict[str, Any],
    details_items: List[Dict[str, Any]],
    footer: Dict[str, Any],
    schema_version: str = "purchase_order_v1",
    source_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Fill a null template with extracted data and return the completed dict.

    Args:
        template:        the null template (from load_template)
        header:          dict matching template.Header keys
        row_wise_rows:   list of row dicts (replicated from prototype)
        details_1:       dict matching template['Details-1'] structure
        details_items:   list of item dicts (matched to template Details keys by index)
        footer:          dict matching template.Footer keys
        schema_version:  string for schema_version field
        source_info:     optional dict for source block

    Returns:
        Fully filled copy of the template
    """
    result = copy.deepcopy(template)

    # ── schema_version ───────────────────────────────────────────────── #
    result["schema_version"] = schema_version

    # ── source ───────────────────────────────────────────────────────── #
    if source_info:
        for k, v in source_info.items():
            if k in result.get("source", {}):
                result["source"][k] = v

    # ── Header ───────────────────────────────────────────────────────── #
    _fill_section(result, "Header", header)

    # ── RowWiseTable ─────────────────────────────────────────────────── #
    proto = get_row_wise_prototype(template)
    filled_rows: List[Dict[str, Any]] = []
    for row_data in row_wise_rows:
        slot = copy.deepcopy(proto)
        for field in slot:
            if field in row_data:
                slot[field] = row_data[field]
        filled_rows.append(slot)
    result["RowWiseTable"] = filled_rows

    # ── Details-1 ────────────────────────────────────────────────────── #
    _fill_section(result, "Details-1", details_1)

    # ── Details ──────────────────────────────────────────────────────── #
    detail_keys = list_detail_keys(template)
    for idx, key in enumerate(detail_keys):
        if idx < len(details_items):
            item_data   = details_items[idx]
            item_slot   = copy.deepcopy(result["Details"][key])
            _fill_detail_item(item_slot, item_data)
            result["Details"][key] = item_slot
        # if fewer items extracted than template slots → slot stays null (fine)

    # ── Footer ───────────────────────────────────────────────────────── #
    _fill_section(result, "Footer", footer)

    return result


def introspect_template(template: Dict[str, Any]) -> None:
    """Print a human-readable summary of the template structure."""
    print(f"Template top-level keys : {list(template.keys())}")
    print(f"Header fields           : {list(template.get('Header', {}).keys())}")
    rw = template.get("RowWiseTable", [{}])
    print(f"RowWiseTable prototype  : {list(rw[0].keys()) if rw else '(empty)'}")
    d1 = template.get("Details-1", {})
    print(f"Details-1 fields        : {list(d1.keys())}")
    d1_item = d1.get("Item", {})
    print(f"Details-1.Item fields   : {list(d1_item.keys())}")
    det = template.get("Details", {})
    print(f"Details keys            : {list(det.keys())}")
    if det:
        first_key = next(iter(det))
        print(f"Details[{first_key}] fields  : {list(det[first_key].keys())}")
        # Item 24 may differ
        if "Item 24" in det:
            print(f"Details[Item 24] unique : "
                  f"{set(det['Item 24'].keys()) - set(det[first_key].keys())}")
    print(f"Footer fields           : {list(template.get('Footer', {}).keys())}")


# ──────────────────────────────────────────────────────────────────────────── #
# Private helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _fill_section(result: dict, section: str, data: dict) -> None:
    """Fill one flat section (Header / Footer / Details-1) from a data dict."""
    if section not in result:
        return
    target = result[section]
    if isinstance(target, dict) and isinstance(data, dict):
        _deep_fill(target, data)


def _deep_fill(target: dict, source: dict) -> None:
    """
    Recursively fill null slots in target from source.
    Only fills keys that already exist in target (no new keys added).
    Descends into nested dicts.
    """
    for key in target:
        if key not in source:
            continue
        if isinstance(target[key], dict) and isinstance(source[key], dict):
            _deep_fill(target[key], source[key])
        else:
            target[key] = source[key]


def _fill_detail_item(slot: dict, data: dict) -> None:
    """
    Fill a Detail item slot from extracted data dict.
    Handles nested 'Item' sub-dict separately.
    """
    for key in slot:
        if key == "Item":
            # nested sub-dict
            if isinstance(slot["Item"], dict) and isinstance(data.get("Item"), dict):
                _deep_fill(slot["Item"], data["Item"])
        elif key in data:
            slot[key] = data[key]
