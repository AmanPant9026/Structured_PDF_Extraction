"""
helpers/__init__.py
-------------------
Public helpers for extraction, table parsing, text processing,
and template-based output validation.

No GT / ground-truth is used anywhere — only the null template.
"""

from .table_helpers import (
    html_table_to_dicts,
    html_table_to_matrix,
    find_table_by_header,
    extract_column_by_name,
    remap_columns,
    filter_rows_by_column,
)
from .text_helpers import (
    extract_by_label,
    extract_first_match,
    extract_all_matches,
    parse_date_to_iso,
    normalize_whitespace,
    strip_currency,
    safe_float,
    safe_int,
    looks_like_date,
    looks_like_number,
)
from .schema_helpers import (
    force_template_alignment,
    json_diff,
    fill_rate_report,
    list_template_paths,
    count_filled_fields,
)

__all__ = [
    # table
    "html_table_to_dicts", "html_table_to_matrix", "find_table_by_header",
    "extract_column_by_name", "remap_columns", "filter_rows_by_column",
    # text
    "extract_by_label", "extract_first_match", "extract_all_matches",
    "parse_date_to_iso", "normalize_whitespace", "strip_currency",
    "safe_float", "safe_int", "looks_like_date", "looks_like_number",
    # template validation (no GT)
    "force_template_alignment", "json_diff", "fill_rate_report",
    "list_template_paths", "count_filled_fields",
]
