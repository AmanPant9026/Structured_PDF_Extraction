"""
core/ollama_extractor.py
-------------------------
Qwen2.5 extractor via Ollama.
Recommended model: qwen2.5:32b  (Apache 2.0 licence, runs locally).

Model recommendation: qwen2.5:32b  (Apache 2.0 licence)
  - Strong instruction following, excellent JSON output
  - 32B gives near-GPT-4 quality on structured extraction tasks
  - Runs on a single A100/H100 or 2× 3090s at Q4 quant

Ollama API: http://localhost:11434  (OpenAI-compatible /v1/chat/completions)

Usage
-----
    from core.ollama_extractor import OllamaExtractor
    extractor = OllamaExtractor(model="qwen2.5:32b")
    # Then pass to ExtractionPipeline(..., extractor=extractor)

Config knobs (via OllamaConfig or constructor args)
----------------------------------------------------
    base_url    Ollama server URL  (default: http://localhost:11434)
    model       model tag          (default: qwen2.5:32b)
    temperature 0 = deterministic  (default: 0.0)
    max_tokens  per-call limit     (default: 1024)
    timeout     HTTP timeout secs  (default: 120)
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .cache import CacheManager
from .evidence import EvidenceBlock
from .extractor import (
    BaseExtractor,
    _build_evidence_text,
    _build_list_prompt,
    _build_scalar_prompt,
    _parse_list_response,
    _parse_scalar_response,
    _strip_fences,
)
from .logger import FrameworkLogger
from .schema_parser import FieldNode, ParsedSchema


class OllamaExtractor(BaseExtractor):
    """
    LLM extractor backed by a local Ollama server.

    Implements the BaseExtractor interface —
    swap models by changing the model= argument, nothing else needs updating.

    Args:
        base_url:    Ollama server base URL (no trailing slash)
        model:       Ollama model tag — must be pulled before running
        temperature: sampling temperature (0 = greedy / deterministic)
        max_tokens:  maximum tokens to generate per call
        timeout:     HTTP request timeout in seconds
        cache:       CacheManager instance (disabled if None)
        retry_count: number of retries on connection error / timeout
        retry_wait:  seconds to wait between retries
    """

    SYSTEM_PROMPT = (
        "You are a precise document extraction engine. "
        "Extract only information explicitly present in the provided document evidence. "
        "Never infer, hallucinate, or fill in information not present. "
        "Always respond with valid JSON only — no markdown fences, no explanation, "
        "no commentary. Output raw JSON and nothing else."
    )

    def __init__(
        self,
        base_url:    str = "http://localhost:11434",
        model:       str = "qwen2.5:32b",
        temperature: float = 0.0,
        max_tokens:  int = 1024,
        timeout:     int = 120,
        cache:       Optional[CacheManager] = None,
        retry_count: int = 3,
        retry_wait:  float = 2.0,
    ):
        self._base_url    = base_url.rstrip("/")
        self._model       = model
        self._temperature = temperature
        self._max_tokens  = max_tokens
        self._timeout     = timeout
        self._cache       = cache or CacheManager(enabled=False)
        self._retry_count = retry_count
        self._retry_wait  = retry_wait
        self._logger      = FrameworkLogger("ollama_extractor")

        # Validate connection once at init (non-fatal — just warns)
        self._check_connection()

    # ------------------------------------------------------------------ #
    # BaseExtractor interface
    # ------------------------------------------------------------------ #

    def extract_scalar(
        self,
        field: FieldNode,
        evidence_blocks: List[EvidenceBlock],
        doc_type: str,
    ) -> Optional[Any]:
        evidence_text = _build_evidence_text(evidence_blocks)
        cache_key = self._cache.make_key(doc_type, field.path, evidence_text)

        cached = self._cache.get(cache_key)
        if cached is not None:
            self._logger.debug("cache_hit", field=field.path)
            return _parse_scalar_response(cached, field)

        prompt = _build_scalar_prompt(field, evidence_text, doc_type)
        raw    = self._call(prompt)
        self._cache.set(cache_key, raw)
        return _parse_scalar_response(raw, field)

    def extract_list(
        self,
        list_root: FieldNode,
        evidence_blocks: List[EvidenceBlock],
        doc_type: str,
    ) -> List[Dict[str, Any]]:
        evidence_text = _build_evidence_text(evidence_blocks)
        cache_key = self._cache.make_key(doc_type, list_root.path + ":LIST", evidence_text)

        cached = self._cache.get(cache_key)
        if cached is not None:
            self._logger.debug("cache_hit_list", field=list_root.path)
            return _parse_list_response(cached)

        item_leaves = list_root.list_item_leaves()
        prompt      = _build_list_prompt(list_root, item_leaves, evidence_text, doc_type)
        raw         = self._call(prompt, max_tokens=2048)
        self._cache.set(cache_key, raw)
        return _parse_list_response(raw)

    # ------------------------------------------------------------------ #
    # HTTP call
    # ------------------------------------------------------------------ #

    def _call(self, user_prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Call Ollama's OpenAI-compatible /v1/chat/completions endpoint.
        Falls back to Ollama's native /api/chat if the v1 endpoint fails.
        """
        max_tok = max_tokens or self._max_tokens

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens":  max_tok,
            "stream":      False,
        }

        for attempt in range(self._retry_count):
            try:
                raw = self._http_post(
                    f"{self._base_url}/v1/chat/completions",
                    payload,
                )
                data = json.loads(raw)
                # OpenAI-compatible response
                return data["choices"][0]["message"]["content"]

            except (KeyError, json.JSONDecodeError):
                # Fallback to native Ollama /api/chat
                try:
                    native_payload = {
                        "model":  self._model,
                        "messages": payload["messages"],
                        "stream": False,
                        "options": {
                            "temperature": self._temperature,
                            "num_predict": max_tok,
                        },
                    }
                    raw  = self._http_post(f"{self._base_url}/api/chat", native_payload)
                    data = json.loads(raw)
                    return data["message"]["content"]
                except Exception as e:
                    self._logger.error("ollama_native_error", error=str(e), attempt=attempt)
                    if attempt == self._retry_count - 1:
                        return "null"
                    time.sleep(self._retry_wait)

            except (urllib.error.URLError, OSError) as e:
                self._logger.warning(
                    "ollama_connection_error", error=str(e), attempt=attempt,
                    url=self._base_url,
                )
                if attempt == self._retry_count - 1:
                    raise RuntimeError(
                        f"Cannot connect to Ollama at {self._base_url}. "
                        f"Is Ollama running? Try: ollama serve"
                    ) from e
                time.sleep(self._retry_wait * (attempt + 1))

        return "null"

    def _http_post(self, url: str, payload: dict) -> str:
        body    = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as resp:
            return resp.read().decode("utf-8")

    def _check_connection(self) -> None:
        """Ping Ollama /api/tags to verify the server is up."""
        try:
            req = urllib.request.Request(f"{self._base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                pass
            self._logger.info("ollama_connected", url=self._base_url, model=self._model)
        except Exception:
            self._logger.warning(
                "ollama_not_reachable",
                url=self._base_url,
                hint="Run 'ollama serve' in a separate terminal",
            )

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #

    def list_local_models(self) -> List[str]:
        """Return names of models already pulled in Ollama."""
        try:
            raw  = self._http_get(f"{self._base_url}/api/tags")
            data = json.loads(raw)
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def _http_get(self, url: str) -> str:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode("utf-8")

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url
