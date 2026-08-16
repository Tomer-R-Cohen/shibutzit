"""Durable logging setup for the backend.

Local-first, single-process app: there is no log aggregator, so a rotating
file under `backend/.logs/` (git-ignored, like `.sessions/`) is the only
record left once the terminal that ran uvicorn is closed.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), ".logs")
LOG_FILE = os.path.join(LOG_DIR, "backend.log")

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        pass

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        # File logging is a convenience, not a correctness requirement.
        pass
