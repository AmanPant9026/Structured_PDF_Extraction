"""
core/pipeline.py
----------------
The stable generic pipeline.  This is the ONLY file that orchestrates
the full extraction flow.  It never needs to change for new document types.

Flow
----
  load → unify_evidence → parse_schema → retrieve →
  extract → assemble → repair → validate → finalize

Each step calls into the document adapter for customization hooks.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .assembler import JSONAssembler
from .cache import CacheManager
from .evidence import EvidenceStore, build_evidence_store
from .extractor import BaseExtractor
from .logger import FrameworkLogger
from .repair import RepairEngine
from .retriever import EvidenceRetriever
from .schema_parser import ParsedSchema, load_schema, parse_schema_dict
from .validator import SchemaValidator


# ──────────────────────────────────────────────────────────────────────────── #
# Result container
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class ExtractionResult:
    doc_type: str
    data: Dict[str, Any]
    is_valid: bool
    validation_summary: str
    elapsed_seconds: float
    warnings: List[str]

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.data, indent=indent, default=str)

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_json())


# ──────────────────────────────────────────────────────────────────────────── #
# Pipeline
# ──────────────────────────────────────────────────────────────────────────── #

class ExtractionPipeline:
    """
    Orchestrates the full extraction flow for any document type.

    This class is STABLE — new document types are added by registering
    a new adapter + config in the DocumentRegistry, not by touching this class.

    Args:
        registry: DocumentRegistry with all adapters + configs registered.
        extractor: override the LLM extractor (useful in tests).
        log_dir:   where to write logs.
    """

    def __init__(
        self,
        registry: "DocumentRegistry",          # forward ref to avoid circular import
        extractor: Optional[BaseExtractor] = None,
        log_dir: str = "logs/",
    ):
        self._registry = registry
        self._extractor = extractor
        self._log_dir = log_dir
        self._logger = FrameworkLogger("pipeline", log_dir=log_dir)

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def run(
        self,
        doc_type: str,
        json_pages: List[List[Dict[str, Any]]],
        markdown: str,
        schema: Dict[str, Any],
        output_path: Optional[str] = None,
    ) -> ExtractionResult:
        """
        Run the full extraction pipeline.

        Args:
            doc_type:    registered document type key (e.g. 'shipping_bill')
            json_pages:  list of pages, each a list of OCR block dicts
            markdown:    full document markdown string
            schema:      GT schema dict (already loaded)
            output_path: if given, save result JSON here

        Returns:
            ExtractionResult
        """
        t0 = time.time()
        warnings: List[str] = []
        self._logger.info("pipeline_start", doc_type=doc_type)

        # 1. Resolve adapter + config
        adapter, config = self._registry.get(doc_type)
        adapter.set_config(config)

        # 2. Build extractor
        if self._extractor is None:
            from .ollama_extractor import OllamaExtractor
            extractor = OllamaExtractor(
                base_url=getattr(config, "ollama_url", "http://localhost:11434"),
                model=config.extraction_model,
                max_tokens=config.max_tokens_per_call,
                temperature=config.temperature,
                cache=CacheManager(
                    cache_dir=config.cache_dir,
                    enabled=config.enable_cache,
                ),
            )
        else:
            extractor = self._extractor

        # 3. STEP: Load / pre-process
        self._logger.info("step_preprocess")
        json_pages = adapter.preprocess_json_blocks(json_pages)
        markdown = adapter.preprocess_markdown(markdown)

        # 4. STEP: Unify evidence
        self._logger.info("step_evidence")
        store = build_evidence_store(json_pages, markdown)
        self._logger.info("evidence_built", n_blocks=len(store))

        # 5. STEP: Parse schema
        self._logger.info("step_schema")
        parsed_schema: ParsedSchema = parse_schema_dict(schema)
        adapter.on_schema_parsed(parsed_schema)

        # 6. STEP: Build retriever with adapter's section hints
        retriever = EvidenceRetriever(
            store=store,
            top_k=config.retrieval_top_k,
            section_hints=adapter.get_section_hints(),
            extra_scorers=adapter.get_extra_scorers(),
        )

        # 7. STEP: Extract + assemble
        self._logger.info("step_extract")
        assembler = JSONAssembler(parsed_schema)

        # Extract scalar fields
        for fn in parsed_schema.root_fields:
            for leaf in fn.leaves():
                self._logger.debug("extract_scalar", field=leaf.path)
                evidence = retriever.retrieve(leaf)
                value = extractor.extract_scalar(leaf, evidence, doc_type)
                # Run adapter per-field post-process hook
                value = adapter.postprocess_field(leaf.path, value)
                assembler.set_scalar(leaf.path, value)

        # Extract list fields
        for lr in parsed_schema.list_roots:
            self._logger.debug("extract_list", field=lr.path)
            evidence = retriever.retrieve_for_list(lr)
            items = extractor.extract_list(lr, evidence, doc_type)
            items = adapter.postprocess_list(lr.path, items)
            assembler.set_list(lr.path, items)

        # 8. STEP: Assemble draft
        draft = assembler.build()

        # 9. STEP: Repair
        self._logger.info("step_repair")
        # Allow adapter to fully override the repair engine (e.g. to
        # exclude DateNormalizer when GT keeps DD-MON-YYYY dates).
        if hasattr(adapter, "get_custom_repair_engine"):
            repair_engine = adapter.get_custom_repair_engine()
        else:
            repair_engine = RepairEngine(extra_rules=adapter.get_repair_rules())
        validator = _build_validator(adapter)
        pre_report = validator.validate(draft, parsed_schema)
        repaired = repair_engine.repair(draft, parsed_schema, pre_report)

        # 10. STEP: Validate final
        self._logger.info("step_validate")
        final_report = validator.validate(repaired, parsed_schema)
        for issue in final_report.issues:
            warnings.append(f"[{issue.severity.upper()}] {issue.path}: {issue.message}")
            self._logger.warning(
                "validation_issue",
                severity=issue.severity,
                path=issue.path,
                message=issue.message,
            )

        # 11. STEP: Adapter final hook
        final_data = adapter.finalize(repaired, parsed_schema)

        elapsed = round(time.time() - t0, 2)
        self._logger.info(
            "pipeline_done",
            doc_type=doc_type,
            elapsed=elapsed,
            valid=final_report.is_valid,
        )

        result = ExtractionResult(
            doc_type=doc_type,
            data=final_data,
            is_valid=final_report.is_valid,
            validation_summary=final_report.summary(),
            elapsed_seconds=elapsed,
            warnings=warnings,
        )

        if output_path:
            result.save(output_path)
            self._logger.info("result_saved", path=output_path)

        return result


# ──────────────────────────────────────────────────────────────────────────── #
# Helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _build_validator(adapter) -> SchemaValidator:
    """Return adapter's custom validator or the default SchemaValidator."""
    custom = adapter.get_validator()
    if custom is not None:
        return custom
    return SchemaValidator()
