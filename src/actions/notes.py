"""Note writer — saves plain text to ~/Documents/miple-notes/."""
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_NOTES_DIR = Path.home() / "Documents" / "miple-notes"


def save_note(content: str, title: str | None = None) -> str:
    """Save *content* to ~/Documents/miple-notes/ with a timestamped filename.

    Args:
        content: The note body text.
        title: Optional title used to build the filename.

    Returns:
        Confirmation string including the saved path.
    """
    if not content or not content.strip():
        return "Cannot save an empty note."
    _NOTES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if title:
        slug = re.sub(r"[^\w\-]", "_", title)[:40]
        filename = f"{timestamp}_{slug}.md"
    else:
        filename = f"{timestamp}.md"
    path = _NOTES_DIR / filename
    path.write_text(content, encoding="utf-8")
    logger.debug("Note saved: %s", path)
    return f"Note saved to {path}"
