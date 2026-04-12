"""
core/logger.py
--------------
Centralized structured logger for the extraction framework.
All modules get a child logger from this; log output is both console + rotating file.
"""

import logging
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Any


class FrameworkLogger:
    """
    Thin wrapper around Python's standard logging.
    Provides structured key=value output on top of normal log levels.
    Usage:
        logger = FrameworkLogger("pipeline", log_dir="logs/")
        logger.info("step_complete", step="load", doc_type="shipping_bill")
    """

    def __init__(self, name: str, log_dir: Optional[str] = None, level: int = logging.DEBUG):
        self._logger = logging.getLogger(f"pdf_extractor.{name}")
        self._logger.setLevel(level)
        self._logger.propagate = False  # prevent double-logging

        fmt = logging.Formatter(
            "%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler (INFO+)
        if not self._logger.handlers:
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.INFO)
            ch.setFormatter(fmt)
            self._logger.addHandler(ch)

            # File handler (DEBUG+) — only if log_dir is given
            if log_dir:
                Path(log_dir).mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                fh = logging.FileHandler(Path(log_dir) / f"{name}_{stamp}.log")
                fh.setLevel(logging.DEBUG)
                fh.setFormatter(fmt)
                self._logger.addHandler(fh)

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #

    def _fmt(self, msg: str, kwargs: dict) -> str:
        if not kwargs:
            return msg
        kv = " | ".join(f"{k}={json.dumps(v, default=str)}" for k, v in kwargs.items())
        return f"{msg} | {kv}"

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(self._fmt(msg, kwargs))

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(self._fmt(msg, kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(self._fmt(msg, kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error(self._fmt(msg, kwargs))

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._logger.critical(self._fmt(msg, kwargs))
