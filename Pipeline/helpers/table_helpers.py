"""
helpers/table_helpers.py
-------------------------
Reusable utilities for working with HTML tables embedded in JSON / markdown.

All helpers are pure functions — no side effects, easy to unit-test.
Document adapters can import and call these directly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag


# ──────────────────────────────────────────────────────────────────────────── #
# HTML Table → structured data
# ──────────────────────────────────────────────────────────────────────────── #

def html_table_to_dicts(
    html: str,
    header_row_index: int = 0,
    skip_empty_rows: bool = True,
) -> List[Dict[str, str]]:
    """
    Parse an HTML table into a list of dicts keyed by column headers.

    Args:
        html:             raw HTML string containing a <table>.
        header_row_index: which <tr> index to treat as the header row.
        skip_empty_rows:  drop rows where all cells are empty strings.

    Returns:
        List of row dicts, e.g. [{"Ship No": "1", "Ship Mode": "AIR"}, ...]
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    all_rows = table.find_all("tr")
    if not all_rows:
        return []

    # Extract headers from the designated row
    header_cells = all_rows[header_row_index].find_all(["th", "td"])
    headers = [_cell_text(c) for c in header_cells]
    # Deduplicate blank headers
    headers = _deduplicate_headers(headers)

    result: List[Dict[str, str]] = []
    for row in all_rows[header_row_index + 1:]:
        cells = row.find_all(["td", "th"])
        values = [_cell_text(c) for c in cells]

        # Pad / truncate to match header count
        while len(values) < len(headers):
            values.append("")
        values = values[:len(headers)]

        row_dict = dict(zip(headers, values))

        if skip_empty_rows and all(v == "" for v in row_dict.values()):
            continue

        result.append(row_dict)

    return result


def html_table_to_matrix(
    html: str,
    include_headers: bool = True,
) -> List[List[str]]:
    """
    Parse an HTML table into a 2D list (list of rows, each a list of cell strings).
    Handles colspan by repeating the cell value.

    Args:
        html:            raw HTML string.
        include_headers: if True, include <th> rows; if False, skip them.

    Returns:
        2D list of strings.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    matrix: List[List[str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"] if include_headers else ["td"])
        if not cells:
            continue
        row_data: List[str] = []
        for cell in cells:
            text = _cell_text(cell)
            colspan = int(cell.get("colspan", 1))
            row_data.extend([text] * colspan)
        matrix.append(row_data)

    return matrix


def find_table_by_header(
    html_tables: List[str],
    header_keywords: List[str],
    min_match: int = 1,
) -> Optional[str]:
    """
    Find the first table whose header row contains at least `min_match`
    of the given header_keywords (case-insensitive).

    Args:
        html_tables:     list of raw HTML table strings.
        header_keywords: keywords to look for in the first row.
        min_match:       minimum number of keywords that must appear.

    Returns:
        The matching HTML table string, or None.
    """
    for html in html_tables:
        matrix = html_table_to_matrix(html)
        if not matrix:
            continue
        header_text = " ".join(matrix[0]).lower()
        matched = sum(1 for kw in header_keywords if kw.lower() in header_text)
        if matched >= min_match:
            return html
    return None


def extract_column_by_name(
    html: str,
    column_name: str,
    case_sensitive: bool = False,
) -> List[str]:
    """
    Extract all values from a named column (matches header cell text).

    Returns empty list if column not found.
    """
    rows = html_table_to_dicts(html)
    if not rows:
        return []

    # Find the matching column key
    target = column_name if case_sensitive else column_name.lower()
    col_key: Optional[str] = None
    for key in rows[0].keys():
        k = key if case_sensitive else key.lower()
        if target in k:
            col_key = key
            break

    if col_key is None:
        return []

    return [row.get(col_key, "") for row in rows]


# ──────────────────────────────────────────────────────────────────────────── #
# Table normalization helpers
# ──────────────────────────────────────────────────────────────────────────── #

def remap_columns(
    rows: List[Dict[str, Any]],
    column_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Rename dict keys according to a mapping.
    Keys not in column_map are passed through unchanged.

    Args:
        rows:       list of row dicts.
        column_map: {original_key: new_key, ...}

    Returns:
        New list of row dicts with renamed keys.
    """
    result = []
    for row in rows:
        new_row = {column_map.get(k, k): v for k, v in row.items()}
        result.append(new_row)
    return result


def filter_rows_by_column(
    rows: List[Dict[str, Any]],
    column: str,
    exclude_values: Optional[List[str]] = None,
    require_non_empty: bool = True,
) -> List[Dict[str, Any]]:
    """
    Filter rows based on a column's value.

    Args:
        rows:               list of row dicts.
        column:             the column key to check.
        exclude_values:     rows with these values (case-insensitive) are removed.
        require_non_empty:  if True, also remove rows where the column is empty.

    Returns:
        Filtered list.
    """
    exclusions = {v.lower() for v in (exclude_values or [])}

    def _keep(row: Dict) -> bool:
        val = str(row.get(column, "")).strip()
        if require_non_empty and not val:
            return False
        if exclusions and val.lower() in exclusions:
            return False
        return True

    return [r for r in rows if _keep(r)]


# ──────────────────────────────────────────────────────────────────────────── #
# Private utilities
# ──────────────────────────────────────────────────────────────────────────── #

def _cell_text(cell: Tag) -> str:
    """Get clean text from a BS4 cell element."""
    return cell.get_text(separator=" ", strip=True)


def _deduplicate_headers(headers: List[str]) -> List[str]:
    """
    Ensure no two headers are identical by appending _2, _3, etc.
    Blank headers become 'col_N'.
    """
    seen: Dict[str, int] = {}
    result: List[str] = []
    for i, h in enumerate(headers):
        if not h:
            h = f"col_{i}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 1
        result.append(h)
    return result
