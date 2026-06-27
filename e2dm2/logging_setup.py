from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .catalog import default_project_root


def log_file_path() -> Path:
    return default_project_root() / "Logs" / "e2dm2.log"


def configure_logging() -> Path:
    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if not any(getattr(handler, "e2dm2_handler", False) for handler in root.handlers):
        handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.e2dm2_handler = True
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
        root.addHandler(handler)
    logging.captureWarnings(True)
    logging.getLogger(__name__).info("E2DM2 logging started: %s", path)
    return path

