"""
core/__init__.py
----------------
Public API for the extraction framework core.

All LLM extraction is done via OllamaExtractor (Apache 2.0 licence).
Qwen2.5:32b is the recommended model — MIT/Apache licensed, runs locally.
No proprietary API is used or imported anywhere in this framework.
"""

from .pipeline import ExtractionPipeline, ExtractionResult
from .evidence import EvidenceStore, EvidenceBlock, EvidenceKind
from .schema_parser import ParsedSchema, FieldNode, load_schema, parse_schema_dict
from .extractor import BaseExtractor
from .ollama_extractor import OllamaExtractor
from .validator import SchemaValidator, ValidationReport
from .repair import RepairEngine, RepairRule
from .cache import CacheManager
from .logger import FrameworkLogger

__all__ = [
    # Pipeline
    "ExtractionPipeline", "ExtractionResult",
    # Evidence
    "EvidenceStore", "EvidenceBlock", "EvidenceKind",
    # Schema
    "ParsedSchema", "FieldNode", "load_schema", "parse_schema_dict",
    # Extractors — Ollama/Qwen only
    "BaseExtractor", "OllamaExtractor",
    # Validation & repair
    "SchemaValidator", "ValidationReport",
    "RepairEngine", "RepairRule",
    # Utilities
    "CacheManager", "FrameworkLogger",
]
