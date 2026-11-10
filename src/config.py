"""Runtime configuration for Miple.

Every value can be overridden with an environment variable so the app can
be pointed at a different Ollama server or model without code changes.
"""
import os
from pathlib import Path

OLLAMA_URL: str = os.environ.get("MIPLE_OLLAMA_URL", "http://localhost:11434")
"""Base URL of the Ollama server."""

MODEL_OVERRIDE: str | None = os.environ.get("MIPLE_MODEL") or None
"""Model forced by the user; skips the automatic hardware-based choice."""

DEFAULT_MODEL: str = MODEL_OVERRIDE or "gemma4:e4b"
"""Fallback model when setup hasn't picked one yet."""

NOTES_DIR: Path = Path(
    os.environ.get("MIPLE_NOTES_DIR", Path.home() / "Documents" / "miple-notes")
).expanduser()
"""Directory where notes are written and read."""

REQUEST_TIMEOUT: float = float(os.environ.get("MIPLE_TIMEOUT", "300"))
"""Seconds to wait for the model's reply before giving up (first load of a model is slow)."""

LOAD_TIMEOUT: float = float(os.environ.get("MIPLE_LOAD_TIMEOUT", "900"))
"""Seconds to wait when loading a model into memory ahead of time."""

KEEP_ALIVE: str = os.environ.get("MIPLE_KEEP_ALIVE", "30m")
"""How long Ollama keeps the model in memory after the last message (Ollama syntax)."""
