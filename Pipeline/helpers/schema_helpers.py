"""
helpers/schema_helpers.py
--------------------------
Utilities for strict schema/template alignment and JSON structure comparison.

These helpers work purely on the extracted JSON and the null template.
No ground-truth or GT file is used anywhere in this framework.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────── #
# Template alignment
# ──────────────────────────────────────────────────────────────────────────── #

def force_template_alignment(
    data: Dict[str, Any],
    template: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ensure the extracted data matches the template structure exactly.

    - Keys in data that are NOT in the template are removed.
    - Keys in the template that are missing from data are added as null.
    - Recurses into nested dicts.

    Args:
        data:     extracted output dict
        template: null template dict (defines the allowed shape)

    Returns:
        Aligned copy of data matching the template structure.
    """
    import copy
    result: Dict[str, Any] = {}
    for key, tmpl_val in template.items():
        if key not in data:
            result[key] = copy.deepcopy(tmpl_val)  # fill missing with null
            continue
        actual_val = data[key]
        if isinstance(tmpl_val, dict) and isinstance(actual_val, dict):
            result[key] = force_template_alignment(actual_val, tmpl_val)
        elif isinstance(tmpl_val, list) and isinstance(actual_val, list):
            result[key] = actual_val  # lists are filled dynamically
        else:
            result[key] = actual_val
    return result


def list_template_paths(
    template: Dict[str, Any],
    prefix: str = "",
) -> List[str]:
    """
    Return all leaf paths in the template as dot-notation strings.

    Example:
        template = {"Header": {"PMNo": null, "Date": null}}
        → ["Header.PMNo", "Header.Date"]
    """
    paths: List[str] = []
    for key, val in template.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            paths.extend(list_template_paths(val, full))
        else:
            paths.append(full)
    return paths


def count_filled_fields(data: Dict[str, Any]) -> Tuple[int, int]:
    """
    Count (filled, total) leaf fields in the extracted output.
    A field is 'filled' if its value is not None.

    Returns:
        (filled_count, total_count)
    """
    total = filled = 0
    for val in _iter_leaves_with_values(data):
        total += 1
        if val is not None:
            filled += 1
    return filled, total


def fill_rate_report(
    data: Dict[str, Any],
    template: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate a per-section fill-rate report comparing extracted data
    against the template structure.

    Returns a dict like:
        {
            "Header":       {"filled": 6, "total": 8, "pct": 75.0},
            "RowWiseTable": {"rows": 24},
            "Details":      {"filled": 22, "total": 24, "pct": 91.7},
            "Footer":       {"filled": 4, "total": 5, "pct": 80.0},
            "overall":      {"filled": 32, "total": 37, "pct": 86.5},
        }
    """
    report: Dict[str, Any] = {}
    total_filled = total_total = 0

    for section in ("Header", "Details-1", "Footer"):
        tmpl_sec = template.get(section, {})
        data_sec = data.get(section, {})
        f, t = _count_section(data_sec, tmpl_sec)
        report[section] = {"filled": f, "total": t, "pct": _pct(f, t)}
        total_filled += f
        total_total  += t

    # RowWiseTable — count rows
    rw = data.get("RowWiseTable", [])
    report["RowWiseTable"] = {"rows": len(rw)}

    # Details — count items with at least one filled field
    det = data.get("Details", {})
    det_filled = sum(
        1 for item in det.values()
        if isinstance(item, dict) and any(
            v is not None for v in _iter_leaves_with_values(item)
        )
    )
    report["Details"] = {"filled": det_filled, "total": len(det),
                          "pct": _pct(det_filled, len(det))}
    total_filled += det_filled
    total_total  += len(det)

    report["overall"] = {
        "filled": total_filled,
        "total":  total_total,
        "pct":    _pct(total_filled, total_total),
    }
    return report


# ──────────────────────────────────────────────────────────────────────────── #
# JSON diff (two extracted outputs, e.g. comparing two model runs)
# ──────────────────────────────────────────────────────────────────────────── #

def json_diff(
    a: Dict[str, Any],
    b: Dict[str, Any],
    path: str = "",
) -> List[Dict[str, Any]]:
    """
    Recursively diff two dicts.  Returns list of difference records:
        [{"path": "Header.PMNo", "a": "X", "b": "Y"}, ...]

    Useful for comparing two extraction runs, not for comparing to GT.
    """
    diffs: List[Dict[str, Any]] = []
    all_keys = set(a.keys()) | set(b.keys())
    for key in sorted(all_keys):
        full = f"{path}.{key}" if path else key
        av, bv = a.get(key), b.get(key)
        if isinstance(av, dict) and isinstance(bv, dict):
            diffs.extend(json_diff(av, bv, full))
        elif av != bv:
            diffs.append({"path": full, "a": av, "b": bv})
    return diffs


# ──────────────────────────────────────────────────────────────────────────── #
# Private helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _iter_leaves_with_values(data: Any) -> Iterator[Any]:
    """Yield every leaf value (non-dict, non-list) recursively."""
    if isinstance(data, dict):
        for v in data.values():
            yield from _iter_leaves_with_values(v)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_leaves_with_values(item)
    else:
        yield data


def _count_section(
    data: Dict[str, Any],
    template: Dict[str, Any],
) -> Tuple[int, int]:
    """Count (filled, total) leaves in one section against the template."""
    total = filled = 0
    for key, tmpl_val in template.items():
        actual = data.get(key)
        if isinstance(tmpl_val, dict):
            f, t = _count_section(
                actual if isinstance(actual, dict) else {},
                tmpl_val,
            )
            filled += f
            total  += t
        else:
            total += 1
            if actual is not None:
                filled += 1
    return filled, total


def _pct(filled: int, total: int) -> float:
    return round(100 * filled / total, 1) if total else 0.0
