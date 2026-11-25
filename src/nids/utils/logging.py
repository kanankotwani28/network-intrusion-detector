"""Project-wide logging setup (console + optional log file)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    """Configure the root logger once; safe to call repeatedly."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_nids", False):
            root.removeHandler(h)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, mode="a", encoding="utf-8"))
    for h in handlers:
        h.setFormatter(logging.Formatter(_FORMAT))
        h._nids = True  # type: ignore[attr-defined]
        root.addHandler(h)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
