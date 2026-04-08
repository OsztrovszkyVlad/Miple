"""Error explanation — heuristic pattern matching on error text."""
import logging
import re

logger = logging.getLogger(__name__)


def explain_error(error_text: str) -> dict:
    """Analyse error_text with heuristic patterns.

    Args:
        error_text: The raw error output to analyse.

    Returns:
        dict with keys:
            "explanation": str — human-readable explanation
            "suggested_fix": str | None — shell command or None
    """
    patterns = [
        (
            r"command not found|No such file or directory",
            "The command or file wasn't found on your system.",
            None,
        ),
        (
            r"Permission denied",
            "You don't have permission to access that file or command.",
            "Try running with sudo, or check the file permissions with: ls -la",
        ),
        (
            r"No module named ['\"]?(\w+)",
            None,  # built dynamically below
            None,  # built dynamically below
        ),
        (
            r"Connection refused",
            "A service you're trying to reach isn't running.",
            None,
        ),
        (
            r"Disk quota exceeded|No space left on device",
            "Your storage is full.",
            "df -h",
        ),
    ]

    for pattern, explanation, fix in patterns:
        match = re.search(pattern, error_text)
        if match:
            if pattern == r"No module named ['\"]?(\w+)":
                pkg = match.group(1)
                explanation = f"Python package '{pkg}' is not installed."
                fix = f"pip install {pkg}"
            logger.debug("Error matched pattern %r", pattern)
            return {"explanation": explanation, "suggested_fix": fix}

    return {
        "explanation": "An error occurred. Here's what I captured:",
        "suggested_fix": None,
    }
