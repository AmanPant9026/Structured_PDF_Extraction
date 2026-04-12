"""
configs/base_config.py
----------------------
Base configuration dataclass for all document extractors.

LLM backend: Ollama (open-source, local, no API key required).
Recommended model: qwen2.5:32b  — Apache 2.0 licence.
Other good options:  qwen2.5:14b  (faster, slightly lower accuracy)
                     qwen2.5:7b   (very fast, good for dev/testing)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ExtractionConfig:
    """
    Central configuration for one document type's extraction run.
    All fields have sensible defaults — subclasses override what differs.
    """

    # ── Identity ─────────────────────────────────────────────────────── #
    doc_type: str = "generic"
    version:  str = "1.0"

    # ── Ollama LLM settings (Apache 2.0 / MIT licence models only) ──── #
    extraction_model:     str   = "qwen2.5:32b"   # Apache 2.0
    ollama_url:           str   = "http://localhost:11434"
    max_tokens_per_call:  int   = 1000
    temperature:          float = 0.0              # 0 = deterministic extraction

    # ── Retrieval ─────────────────────────────────────────────────────── #
    retrieval_top_k: int = 5

    # ── Caching ───────────────────────────────────────────────────────── #
    enable_cache: bool = True
    cache_dir:    str  = ".cache/extractions"

    # ── I/O ───────────────────────────────────────────────────────────── #
    output_dir: str = "output/"
    log_dir:    str = "logs/"

    # ── Repair ────────────────────────────────────────────────────────── #
    normalize_dates:         bool = True
    strip_currency_symbols:  bool = True

    # ── Validation ────────────────────────────────────────────────────── #
    fail_on_missing_required: bool = True

    # ── Extensible bag for doc-specific tweaks ────────────────────────── #
    extra: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for extra config values."""
        return self.extra.get(key, default)
