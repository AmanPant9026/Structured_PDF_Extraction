"""
helpers/text_helpers.py
------------------------
Pure-function text utilities used across adapters and the core pipeline.
Safe to import anywhere — no framework dependencies.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────── #
# Pattern extraction
# ──────────────────────────────────────────────────────────────────────────── #

def extract_by_label(
    text: str,
    label: str,
    separator: str = ":",
    multiline: bool = False,
) -> Optional[str]:
    """
    Extract the value that follows a label in plain text.

    Example:
        text = "Supplier: Acme Corp\nDate: 12-MAR-2025"
        extract_by_label(text, "Supplier") → "Acme Corp"

    Args:
        text:       the source string.
        label:      the label to search for (case-insensitive).
        separator:  character that separates label from value.
        multiline:  if True, the value can span multiple lines.

    Returns:
        Stripped value string or None.
    """
    flags = re.IGNORECASE | (re.DOTALL if multiline else 0)
    pattern = re.escape(label) + r"\s*" + re.escape(separator) + r"\s*(.+)"
    if not multiline:
        pattern += r"$"
    m = re.search(pattern, text, flags=flags)
    if m:
        return m.group(1).strip()
    return None


def extract_first_match(text: str, pattern: str, group: int = 1) -> Optional[str]:
    """
    Apply a regex to text and return the first match of the given group.

    Args:
        text:    source string.
        pattern: raw regex pattern.
        group:   capturing group to return (default 1).

    Returns:
        First match string or None.
    """
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return m.group(group).strip()
        except IndexError:
            return m.group(0).strip()
    return None


def extract_all_matches(text: str, pattern: str, group: int = 1) -> List[str]:
    """Return ALL non-overlapping matches of `pattern` in `text`."""
    return [
        m.group(group).strip() if group > 0 else m.group(0).strip()
        for m in re.finditer(pattern, text, re.IGNORECASE)
    ]


# ──────────────────────────────────────────────────────────────────────────── #
# Date utilities
# ──────────────────────────────────────────────────────────────────────────── #

MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
    "JANUARY": "01", "FEBRUARY": "02", "MARCH": "03", "APRIL": "04",
    "JUNE": "06", "JULY": "07", "AUGUST": "08", "SEPTEMBER": "09",
    "OCTOBER": "10", "NOVEMBER": "11", "DECEMBER": "12",
}


def parse_date_to_iso(date_str: str) -> Optional[str]:
    """
    Try to parse a date string into ISO-8601 YYYY-MM-DD format.
    Handles:
      - DD-MON-YYYY  (12-MAR-2025)
      - DD/MM/YYYY
      - MM/DD/YYYY
      - YYYY-MM-DD (passthrough)
      - DD Month YYYY (12 March 2025)

    Returns None if parsing fails.
    """
    if not date_str:
        return None

    s = date_str.strip().upper()

    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # DD-MON-YYYY or DD/MON/YYYY
    m = re.match(r"(\d{1,2})[-/]([A-Z]{3,9})[-/](\d{4})", s)
    if m:
        d, mon, y = m.groups()
        mo = MONTH_MAP.get(mon)
        if mo:
            return f"{y}-{mo}-{d.zfill(2)}"

    # DD/MM/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"

    # YYYY/MM/DD
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}"

    return None


# ──────────────────────────────────────────────────────────────────────────── #
# String normalisation
# ──────────────────────────────────────────────────────────────────────────── #

def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces / tabs / newlines into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def strip_currency(value: str) -> Optional[str]:
    """
    Remove currency symbols (USD, EUR, INR, $, €, ₹, £) and commas.
    Returns None for empty strings.
    """
    cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
    return cleaned if cleaned else None


def to_snake_case(text: str) -> str:
    """Convert 'Ship Mode' or 'SHIP MODE' to 'ship_mode'."""
    return re.sub(r"\s+", "_", text.strip().lower())


def to_title_case(text: str) -> str:
    """Convert 'SHIP MODE' to 'Ship Mode'."""
    return text.strip().title()


# ──────────────────────────────────────────────────────────────────────────── #
# Number utilities
# ──────────────────────────────────────────────────────────────────────────── #

def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """
    Convert a value to float, stripping currency symbols / commas first.
    Returns `default` on failure.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = strip_currency(str(value))
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Convert value to int, stripping commas first."""
    f = safe_float(value)
    if f is None:
        return default
    return int(f)


# ──────────────────────────────────────────────────────────────────────────── #
# Validation helpers
# ──────────────────────────────────────────────────────────────────────────── #

def looks_like_date(text: str) -> bool:
    """Heuristic: does the string look like a date?"""
    return bool(re.search(
        r"\d{1,2}[-/]\w{2,9}[-/]\d{2,4}|\d{4}-\d{2}-\d{2}",
        text.strip(),
        re.IGNORECASE,
    ))


def looks_like_number(text: str) -> bool:
    """Heuristic: does the string look like a number (possibly with units)?"""
    cleaned = re.sub(r"[^\d.,]", "", text.strip())
    return bool(cleaned)
