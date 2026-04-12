"""
core/repair.py
--------------
Post-extraction repair engine.

Runs after validation and applies a chain of repair rules to the
assembled JSON. Rules are tried in order; each rule operates on a
single field value and returns the (possibly corrected) value.

Design
------
- RepairRule   – abstract base class (one rule per concern)
- RepairEngine – orchestrates rules, pluggable rule list
- Built-in rules: DateNormalizer, NumberStripper, EmptyStringToNull, TruncateWhitespace
- Adapters can inject document-specific rules via __init__ override
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .schema_parser import FieldNode, ParsedSchema
from .validator import ValidationIssue, ValidationReport


# ──────────────────────────────────────────────────────────────────────────── #
# Abstract rule
# ──────────────────────────────────────────────────────────────────────────── #

class RepairRule(ABC):
    """
    A single repair rule.

    Override `applies_to` to restrict to specific field types or paths.
    Override `repair` to implement the correction logic.
    """

    @abstractmethod
    def applies_to(self, field: FieldNode, value: Any) -> bool: ...

    @abstractmethod
    def repair(self, field: FieldNode, value: Any) -> Any: ...


# ──────────────────────────────────────────────────────────────────────────── #
# Built-in rules
# ──────────────────────────────────────────────────────────────────────────── #

class TruncateWhitespace(RepairRule):
    """Trim leading/trailing whitespace from string values."""

    def applies_to(self, field: FieldNode, value: Any) -> bool:
        return isinstance(value, str)

    def repair(self, field: FieldNode, value: Any) -> Any:
        return value.strip()


class EmptyStringToNull(RepairRule):
    """Convert empty / whitespace-only strings to None."""

    def applies_to(self, field: FieldNode, value: Any) -> bool:
        return isinstance(value, str)

    def repair(self, field: FieldNode, value: Any) -> Any:
        return None if not value.strip() else value


class NumberStripper(RepairRule):
    """Strip currency symbols and commas from number fields."""

    def applies_to(self, field: FieldNode, value: Any) -> bool:
        return field.dtype == "number" and isinstance(value, str)

    def repair(self, field: FieldNode, value: Any) -> Any:
        cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return value


class DateNormalizer(RepairRule):
    """
    Normalize date strings to ISO-8601 (YYYY-MM-DD) where possible.
    Handles patterns like: 12-MAR-2025, 12/03/2025, March 12 2025.
    """

    MONTH_MAP = {
        "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
        "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
        "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
    }

    def applies_to(self, field: FieldNode, value: Any) -> bool:
        return (
            "date" in field.name.lower()
            and isinstance(value, str)
            and not re.match(r"^\d{4}-\d{2}-\d{2}$", value)
        )

    def repair(self, field: FieldNode, value: Any) -> Any:
        v = value.strip().upper()
        # Pattern: DD-MON-YYYY
        m = re.match(r"(\d{1,2})-([A-Z]{3})-(\d{4})", v)
        if m:
            d, mon, y = m.groups()
            mo = self.MONTH_MAP.get(mon)
            if mo:
                return f"{y}-{mo}-{d.zfill(2)}"
        # Pattern: DD/MM/YYYY
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
        if m:
            d, mo, y = m.groups()
            return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        # Already OK or unrecognised — return as-is
        return value


class BooleanNormalizer(RepairRule):
    """Coerce 'yes/no/Y/N/1/0' strings to booleans."""

    YES = {"yes", "y", "true", "1"}
    NO = {"no", "n", "false", "0"}

    def applies_to(self, field: FieldNode, value: Any) -> bool:
        return field.dtype == "boolean" and isinstance(value, str)

    def repair(self, field: FieldNode, value: Any) -> Any:
        lv = value.strip().lower()
        if lv in self.YES:
            return True
        if lv in self.NO:
            return False
        return value


# ──────────────────────────────────────────────────────────────────────────── #
# Engine
# ──────────────────────────────────────────────────────────────────────────── #

class RepairEngine:
    """
    Applies a configurable chain of RepairRules to every field in the
    assembled JSON based on ValidationReport issues.

    Args:
        rules: ordered list of RepairRules (default set is applied if None)
        extra_rules: additional rules to append after the defaults
    """

    DEFAULT_RULES: List[RepairRule] = [
        TruncateWhitespace(),
        EmptyStringToNull(),
        NumberStripper(),
        DateNormalizer(),
        BooleanNormalizer(),
    ]

    def __init__(
        self,
        rules: Optional[List[RepairRule]] = None,
        extra_rules: Optional[List[RepairRule]] = None,
    ):
        self._rules: List[RepairRule] = rules if rules is not None else list(self.DEFAULT_RULES)
        if extra_rules:
            self._rules.extend(extra_rules)

    def repair(
        self,
        data: Dict[str, Any],
        schema: ParsedSchema,
        report: ValidationReport,
    ) -> Dict[str, Any]:
        """
        Run all repair rules over all schema fields in `data`.
        Returns a (shallow) corrected copy.
        """
        import copy
        result = copy.deepcopy(data)

        # Repair scalar fields
        for fn in schema.root_fields:
            for leaf in fn.leaves():
                self._repair_field(result, leaf)

        # Repair list items
        for lr in schema.list_roots:
            item_leaves = lr.list_item_leaves()
            items = _get_nested(result, lr.path)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        for leaf in item_leaves:
                            if leaf.name in item:
                                repaired = self._apply_rules(leaf, item[leaf.name])
                                item[leaf.name] = repaired

        return result

    # ------------------------------------------------------------------ #

    def _repair_field(self, data: dict, leaf: FieldNode) -> None:
        value = _get_nested(data, leaf.path)
        if value is None:
            return
        repaired = self._apply_rules(leaf, value)
        _set_nested(data, leaf.path, repaired)

    def _apply_rules(self, field: FieldNode, value: Any) -> Any:
        for rule in self._rules:
            if rule.applies_to(field, value):
                value = rule.repair(field, value)
        return value


# ──────────────────────────────────────────────────────────────────────────── #
# Utilities
# ──────────────────────────────────────────────────────────────────────────── #

def _get_nested(d: dict, path: str) -> Any:
    clean = path.replace("[]", "")
    parts = clean.split(".")
    cur = d
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_nested(d: dict, path: str, value: Any) -> None:
    clean = path.replace("[]", "")
    parts = clean.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
