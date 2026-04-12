"""
core/cache.py
-------------
Simple disk-backed LLM response cache.
Key = SHA256 of (doc_type + field_path + evidence_snippet).
Value = raw LLM response string.

In production you'd swap the backend for Redis / Memcached.
The interface is intentionally thin so the swap is trivial.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional


class CacheManager:
    """
    Disk-backed key-value cache for LLM extraction responses.

    Args:
        cache_dir: directory where cache files are stored.
        enabled:   set False to disable entirely (useful in testing).
    """

    def __init__(self, cache_dir: str = ".cache/extractions", enabled: bool = True):
        self._enabled = enabled
        self._dir = Path(cache_dir)
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def make_key(self, doc_type: str, field_path: str, evidence: str) -> str:
        """Deterministic cache key from extraction inputs."""
        raw = f"{doc_type}||{field_path}||{evidence}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[str]:
        """Return cached value or None if missing / cache disabled."""
        if not self._enabled:
            return None
        path = self._dir / f"{key}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("value")
        return None

    def set(self, key: str, value: str) -> None:
        """Store a value. Silently skips when cache is disabled."""
        if not self._enabled:
            return
        path = self._dir / f"{key}.json"
        path.write_text(json.dumps({"key": key, "value": value}))

    def invalidate(self, key: str) -> bool:
        """Remove a single cache entry. Returns True if it existed."""
        if not self._enabled:
            return False
        path = self._dir / f"{key}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def clear_all(self) -> int:
        """Wipe every entry. Returns count of deleted files."""
        if not self._enabled:
            return 0
        removed = 0
        for f in self._dir.glob("*.json"):
            f.unlink()
            removed += 1
        return removed

    @property
    def enabled(self) -> bool:
        return self._enabled
