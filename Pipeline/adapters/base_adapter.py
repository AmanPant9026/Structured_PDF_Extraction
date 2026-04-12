"""
adapters/base_adapter.py
-------------------------
Abstract base class for document adapters.

Every hook is fully documented and has a sensible no-op default.
Subclasses override ONLY the hooks they need — the pipeline always calls
through this interface so adding a new document type is purely additive.

Hook call order (matches pipeline steps):
  1.  set_config
  2.  preprocess_json_blocks
  3.  preprocess_markdown
  4.  on_schema_parsed
  5.  get_section_hints          ← retriever customisation
  6.  get_extra_scorers          ← retriever customisation
  7.  postprocess_field          ← per scalar field
  8.  postprocess_list           ← per list root
  9.  get_repair_rules           ← extra repair rules
  10. get_validator              ← custom validator (or None → default)
  11. finalize                   ← last chance mutation before return
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.repair import RepairRule
    from core.retriever import ScoreFn
    from core.schema_parser import ParsedSchema
    from core.validator import SchemaValidator
    from configs.base_config import ExtractionConfig


class BaseDocumentAdapter(ABC):
    """
    Document adapter interface.

    Subclass this and override whichever hooks your document type needs.
    The pipeline only calls methods defined here — safe to add new hooks
    in the future without breaking existing adapters.
    """

    def __init__(self):
        self._config: Optional["ExtractionConfig"] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def set_config(self, config: "ExtractionConfig") -> None:
        """Called by the pipeline before any other hook. Store config."""
        self._config = config

    @property
    def config(self) -> "ExtractionConfig":
        if self._config is None:
            raise RuntimeError("Config not set — did you call set_config?")
        return self._config

    # ------------------------------------------------------------------ #
    # Hook 2: preprocess_json_blocks
    # ------------------------------------------------------------------ #

    def preprocess_json_blocks(
        self,
        pages: List[List[Dict[str, Any]]],
    ) -> List[List[Dict[str, Any]]]:
        """
        Optional pre-processing on raw OCR JSON pages.

        Use cases:
          - Remove spurious blocks (e.g. headers/footers by bbox position)
          - Merge adjacent text blocks
          - Rename/normalise native_label values
          - Filter to specific pages

        Default: return as-is.
        """
        return pages

    # ------------------------------------------------------------------ #
    # Hook 3: preprocess_markdown
    # ------------------------------------------------------------------ #

    def preprocess_markdown(self, markdown: str) -> str:
        """
        Optional pre-processing on the raw markdown string.

        Use cases:
          - Strip boilerplate (T&Cs, disclaimers)
          - Normalise unusual whitespace
          - Translate non-English labels before LLM sees them

        Default: return as-is.
        """
        return markdown

    # ------------------------------------------------------------------ #
    # Hook 4: on_schema_parsed
    # ------------------------------------------------------------------ #

    def on_schema_parsed(self, schema: "ParsedSchema") -> None:
        """
        Called after the GT schema is parsed.
        Use to inject field aliases from config into the schema nodes.

        Default: inject aliases from get_field_aliases().
        """
        aliases = self.get_field_aliases()
        for fn in schema.root_fields:
            for leaf in fn.leaves():
                if leaf.name in aliases:
                    leaf.aliases.extend(aliases[leaf.name])
        for lr in schema.list_roots:
            for leaf in lr.list_item_leaves():
                if leaf.name in aliases:
                    leaf.aliases.extend(aliases[leaf.name])

    # ------------------------------------------------------------------ #
    # Hook 4a: get_field_aliases
    # ------------------------------------------------------------------ #

    def get_field_aliases(self) -> Dict[str, List[str]]:
        """
        Return a map of canonical_field_name → [alternative names].

        These are injected into the schema nodes so the retriever and
        extractor know what to look for.

        Example:
            return {
                "exporter_name": ["SHIPPER", "SENDER"],
                "hs_code": ["H.S. CODE", "TARIFF CODE"],
            }
        """
        return {}

    # ------------------------------------------------------------------ #
    # Hook 5: get_section_hints
    # ------------------------------------------------------------------ #

    def get_section_hints(self) -> Dict[str, List[str]]:
        """
        Return a map of field_name → section header strings.
        Blocks near/containing these headers get a retrieval score bonus.

        Example:
            return {
                "exporter_name": ["EXPORTER DETAILS", "SHIPPER"],
                "consignee_name": ["CONSIGNEE", "IMPORTER"],
            }
        """
        return {}

    # ------------------------------------------------------------------ #
    # Hook 6: get_extra_scorers
    # ------------------------------------------------------------------ #

    def get_extra_scorers(self) -> List["ScoreFn"]:
        """
        Return additional evidence scoring functions for the retriever.
        Each scorer: (EvidenceBlock, FieldNode) → float (score delta)
        """
        return []

    # ------------------------------------------------------------------ #
    # Hook 7: postprocess_field
    # ------------------------------------------------------------------ #

    def postprocess_field(self, path: str, value: Any) -> Any:
        """
        Per-scalar-field post-processing hook.
        Called immediately after the LLM extraction for that field.

        Use cases:
          - Normalise a specific field's format
          - Apply lookup tables (e.g. port code → port name)
          - Validate a specific regex

        Default: return as-is.
        """
        return value

    # ------------------------------------------------------------------ #
    # Hook 8: postprocess_list
    # ------------------------------------------------------------------ #

    def postprocess_list(
        self,
        path: str,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Per-list post-processing hook.
        Called after the LLM returns the full list for a list_root field.

        Use cases:
          - Filter out header rows mistakenly included
          - Deduplicate rows
          - Reorder / sort items

        Default: return as-is.
        """
        return items

    # ------------------------------------------------------------------ #
    # Hook 9: get_repair_rules
    # ------------------------------------------------------------------ #

    def get_repair_rules(self) -> List["RepairRule"]:
        """
        Return extra RepairRule instances for this document type.
        These are APPENDED to the engine's default rule chain.
        """
        return []

    # ------------------------------------------------------------------ #
    # Hook 10: get_validator
    # ------------------------------------------------------------------ #

    def get_validator(self) -> Optional["SchemaValidator"]:
        """
        Return a custom SchemaValidator subclass, or None to use default.
        Override to add document-specific validation logic.
        """
        return None

    # ------------------------------------------------------------------ #
    # Hook 11: finalize
    # ------------------------------------------------------------------ #

    def finalize(
        self,
        data: Dict[str, Any],
        schema: "ParsedSchema",
    ) -> Dict[str, Any]:
        """
        Last-chance mutation of the assembled + repaired JSON.

        Use cases:
          - Add computed fields (e.g. total_value = sum of line items)
          - Remove internal scaffolding keys
          - Rename top-level keys to match downstream systems

        Default: return as-is.
        """
        return data
