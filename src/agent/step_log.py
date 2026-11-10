"""Agent step log — one JSON object per line, one line per agent-loop step.

Written to ``<config dir>/agent-steps.jsonl`` (see :mod:`src.settings`). The
log stays on this machine; it exists to debug what the model asked for and
what Miple did. Logging problems never interrupt a chat turn.
"""
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import settings

logger = logging.getLogger(__name__)

LOG_FILENAME = "agent-steps.jsonl"


def default_path() -> Path:
    """Where the step log lives unless a path is given explicitly."""
    return settings.config_dir() / LOG_FILENAME


class StepLog:
    """Append-only JSON-lines writer for agent steps."""

    def __init__(self, path: Path | None = None) -> None:
        """Log to *path* (default: :func:`default_path`)."""
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """The file being written."""
        return self._path or default_path()

    def write(self, record: dict[str, Any]) -> None:
        """Append *record* (plus a UTC timestamp) as one JSON line."""
        line = json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **record},
            ensure_ascii=False,
            default=str,
        )
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError as exc:
            logger.warning("Could not write agent step log %s: %s", self.path, exc)
