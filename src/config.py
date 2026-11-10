"""Runtime configuration for Miple.

Every value can be overridden with an environment variable so the app can
be pointed at a different Ollama server or model without code changes.
"""
import os
from pathlib import Path

OLLAMA_URL: str = os.environ.get("MIPLE_OLLAMA_URL", "http://localhost:11434")
"""Base URL of the Ollama server."""

DEFAULT_MODEL: str = os.environ.get("MIPLE_MODEL", "gemma4:e4b")
"""Preferred Ollama model; the first installed model is used if it is missing."""

NOTES_DIR: Path = Path(
    os.environ.get("MIPLE_NOTES_DIR", Path.home() / "Documents" / "miple-notes")
).expanduser()
"""Directory where notes are written and read."""

REQUEST_TIMEOUT: float = float(os.environ.get("MIPLE_TIMEOUT", "120"))
"""Seconds to wait for Ollama before giving up (first load of a model is slow)."""
