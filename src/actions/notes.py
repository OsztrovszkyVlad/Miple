"""Note writer — saves plain-text Markdown notes to the notes directory."""
import logging
import re
from datetime import datetime
from pathlib import Path

from src import config

logger = logging.getLogger(__name__)


def notes_dir() -> Path:
    """Return the directory notes are stored in (see ``MIPLE_NOTES_DIR``)."""
    return config.NOTES_DIR


def list_notes() -> list[Path]:
    """Return all saved notes, newest first."""
    directory = notes_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"), reverse=True)


def save_note(content: str, title: str | None = None) -> str:
    """Save *content* as a timestamped Markdown file in the notes directory.

    Args:
        content: The note body text.
        title: Optional title; it is slugified into the filename.

    Returns:
        Confirmation string including the saved path.
    """
    if not content or not content.strip():
        return "Cannot save an empty note."
    directory = notes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _unique_path(directory, _filename(title))
    path.write_text(content.strip() + "\n", encoding="utf-8")
    logger.debug("Note saved: %s", path)
    return f"Note saved to {path}"


def _filename(title: str | None) -> str:
    """Build ``<timestamp>[_<slug>]`` (without extension)."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug = re.sub(r"[^\w\-]+", "_", title or "").strip("_")[:40]
    return f"{timestamp}_{slug}" if slug else timestamp


def _unique_path(directory: Path, stem: str) -> Path:
    """Return ``directory/stem.md``, adding ``-2``, ``-3`` … if it already exists."""
    path = directory / f"{stem}.md"
    counter = 2
    while path.exists():
        path = directory / f"{stem}-{counter}.md"
        counter += 1
    return path
