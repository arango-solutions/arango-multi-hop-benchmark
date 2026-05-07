"""Centralised logging configuration.

We keep this trivial — `configure_logging(level)` is idempotent and produces
the same `[HH:MM:SS] [LEVEL] message` format the original script used, so
existing log readers / log scrapers keep working.
"""

from __future__ import annotations

import logging
import sys

_DEFAULT_FMT = "%(asctime)s [%(levelname)s] %(message)s"
_DATEFMT = "%H:%M:%S"


def configure_logging(level: str | int = "INFO", *, stream=None) -> logging.Logger:
    """Configure the root logger and return the package logger.

    Idempotent: calling more than once will not add duplicate handlers.
    """
    if isinstance(level, str):
        level_int = getattr(logging, level.upper(), logging.INFO)
    else:
        level_int = int(level)

    root = logging.getLogger()
    root.setLevel(level_int)

    target_stream = stream or sys.stderr

    already_configured = any(
        isinstance(h, logging.StreamHandler)
        and getattr(h, "_multihop_eval_handler", False)
        for h in root.handlers
    )
    if not already_configured:
        handler = logging.StreamHandler(target_stream)
        handler.setFormatter(logging.Formatter(_DEFAULT_FMT, _DATEFMT))
        handler._multihop_eval_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    return logging.getLogger("multihop_eval")
