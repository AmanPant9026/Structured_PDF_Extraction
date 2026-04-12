"""
core/validator.py
-----------------
Post-extraction validation: checks that the assembled JSON strictly
aligns with the GT schema (types, required fields, list structure).

Returns a ValidationReport with per-field issues instead of raising,
so the repair engine can decide what to do with each violation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .schema_parser import FieldNode, ParsedSchema


# ──────────────────────────────────────────────────────────────────────────── #
# Report types
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class ValidationIssue:
    path: str
    severity: str          # 'error' | 'warning'
    message: str
    current_value: Any = None


@dataclass
class ValidationReport:
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self) -> str:
        if self.is_valid:
            return f"VALID ({len(self.warnings())} warnings)"
        return (
            f"INVALID — {len(self.errors())} errors, "
            f"{len(self.warnings())} warnings"
        )


# ──────────────────────────────────────────────────────────────────────────── #
# Validator
# ──────────────────────────────────────────────────────────────────────────── #

class SchemaValidator:
    """
    Validates an assembled JSON dict against a ParsedSchema.

    Extend by subclassing and overriding `extra_validations`.
    """

    def validate(
        self,
        data: Dict[str, Any],
        schema: ParsedSchema,
    ) -> ValidationReport:
        issues: List[ValidationIssue] = []

        # Validate root scalar fields
        for fn in schema.root_fields:
            self._validate_field(fn, data, issues)

        # Validate list roots
        for lr in schema.list_roots:
            self._validate_list(lr, data, issues)

        # Hook for subclass-specific validations
        self.extra_validations(data, schema, issues)

        is_valid = all(i.severity != "error" for i in issues)
        return ValidationReport(is_valid=is_valid, issues=issues)

    def extra_validations(
        self,
        data: Dict[str, Any],
        schema: ParsedSchema,
        issues: List[ValidationIssue],
    ) -> None:
        """Override in subclasses to add document-specific validations."""
        pass

    # ------------------------------------------------------------------ #
    # Private
    # ------------------------------------------------------------------ #

    def _validate_field(
        self,
        fn: FieldNode,
        data: Dict[str, Any],
        issues: List[ValidationIssue],
    ) -> None:
        value = _get_path(data, fn.path)

        if fn.required and value is None:
            issues.append(ValidationIssue(
                path=fn.path,
                severity="error",
                message=f"Required field '{fn.path}' is missing",
                current_value=None,
            ))
            return

        if value is None:
            return  # optional + missing is fine

        # Type check
        if not _check_type(value, fn.dtype):
            issues.append(ValidationIssue(
                path=fn.path,
                severity="warning",
                message=f"Field '{fn.path}' expected {fn.dtype}, got {type(value).__name__}",
                current_value=value,
            ))

    def _validate_list(
        self,
        lr: FieldNode,
        data: Dict[str, Any],
        issues: List[ValidationIssue],
    ) -> None:
        value = _get_path(data, lr.path)

        if value is None:
            if lr.required:
                issues.append(ValidationIssue(
                    path=lr.path, severity="error",
                    message=f"Required list '{lr.path}' is missing",
                ))
            return

        if not isinstance(value, list):
            issues.append(ValidationIssue(
                path=lr.path, severity="error",
                message=f"'{lr.path}' should be a list, got {type(value).__name__}",
                current_value=value,
            ))
            return

        item_leaves = lr.list_item_leaves()
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                issues.append(ValidationIssue(
                    path=f"{lr.path}[{i}]", severity="error",
                    message="List item is not a dict",
                    current_value=item,
                ))
                continue
            for leaf in item_leaves:
                leaf_name = leaf.name
                if leaf.required and item.get(leaf_name) is None:
                    issues.append(ValidationIssue(
                        path=f"{lr.path}[{i}].{leaf_name}",
                        severity="warning",
                        message=f"Required list-item field '{leaf_name}' missing in row {i}",
                    ))


# ──────────────────────────────────────────────────────────────────────────── #
# Utilities
# ──────────────────────────────────────────────────────────────────────────── #

def _get_path(d: dict, path: str) -> Any:
    clean = path.replace("[]", "")
    parts = clean.split(".")
    cur = d
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _check_type(value: Any, dtype: str) -> bool:
    if dtype == "string":
        return isinstance(value, str)
    if dtype == "number":
        return isinstance(value, (int, float))
    if dtype == "boolean":
        return isinstance(value, bool)
    return True
