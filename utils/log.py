"""Logging: short coloured console lines + full DEBUG log file per run (and a copy per video)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console()   # shared with the progress bar so logs print above it

FILE_FMT = "%(asctime)s %(levelname)-7s [%(step)s] %(message)s"
_NOISY = ["httpx", "httpcore", "urllib3", "googleapiclient", "google_auth_httplib2",
          "faster_whisper", "anthropic", "google_genai", "filelock", "huggingface_hub"]


class _StepFilter(logging.Filter):
    def filter(self, record):
        record.step = record.name.split(".")[-1] if record.name.startswith("clipper.") else record.name
        return True


def setup_logging(log_dir: Path, verbose: bool = False) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    con = RichHandler(console=console, show_path=False, markup=False, rich_tracebacks=True,
                      log_time_format="%H:%M:%S")
    con.setLevel(logging.DEBUG if verbose else logging.INFO)
    con.setFormatter(logging.Formatter("[%(step)s] %(message)s"))
    con.addFilter(_StepFilter())

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FILE_FMT))
    fh.addFilter(_StepFilter())

    root.addHandler(con)
    root.addHandler(fh)
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    return log_file


def add_file_log(path: Path) -> logging.Handler:
    """Extra log file (e.g. data/<video>/run.log). Remove with remove_handler()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, encoding="utf-8")
    h.setLevel(logging.DEBUG)
    h.setFormatter(logging.Formatter(FILE_FMT))
    h.addFilter(_StepFilter())
    logging.getLogger().addHandler(h)
    return h


def remove_handler(h: logging.Handler):
    logging.getLogger().removeHandler(h)
    h.close()


def get(step: str) -> logging.Logger:
    return logging.getLogger(f"clipper.{step}")
