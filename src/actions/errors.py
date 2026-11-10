"""Error explanation — heuristic pattern matching on pasted error text.

Suggested fixes are only ever *shown* to the user; nothing here executes them.
"""
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_ECHO_CHARS = 500


@dataclass(frozen=True)
class _Rule:
    """One known error pattern and how to explain it."""

    pattern: re.Pattern[str]
    explain: Callable[[re.Match[str]], tuple[str, str | None]]


def _fixed(explanation: str, fix: str | None = None):
    """Build an explain() callback that ignores the match."""
    return lambda _m: (explanation, fix)


_RULES: list[_Rule] = [
    _Rule(
        re.compile(r"No module named ['\"]?([\w.]+)"),
        lambda m: (
            f"Python can't find the package '{m.group(1).split('.')[0]}' — it isn't installed "
            "in the Python environment you're running.",
            f"python3 -m pip install {m.group(1).split('.')[0]}",
        ),
    ),
    _Rule(
        re.compile(r"(?:bash|zsh|sh): (?:line \d+: )?([\w.+-]+): command not found"),
        lambda m: (
            f"The command '{m.group(1)}' isn't installed or isn't on your PATH. "
            "Ask me to install it, or check the spelling.",
            None,
        ),
    ),
    _Rule(
        re.compile(r"command not found", re.I),
        _fixed("That command isn't installed or isn't on your PATH."),
    ),
    _Rule(
        re.compile(r"Permission denied", re.I),
        _fixed(
            "You don't have permission to access that file or run that command. "
            "Check who owns it and its permissions; only use sudo if you trust the command.",
            "ls -la <path-from-the-error>",
        ),
    ),
    _Rule(
        re.compile(r"No such file or directory", re.I),
        _fixed("A file or folder the program expected doesn't exist. Check the path."),
    ),
    _Rule(
        re.compile(r"Could not get lock|Unable to acquire the dpkg frontend lock", re.I),
        _fixed(
            "Another package manager (like Software Updater) is running. "
            "Wait for it to finish, then try again."
        ),
    ),
    _Rule(
        re.compile(r"Unable to locate package ([\w.+-]+)|No match for argument: ([\w.+-]+)"),
        lambda m: (
            f"The package '{m.group(1) or m.group(2)}' isn't in your package lists. "
            "Refresh them, or the package may have a different name on your distro.",
            "sudo apt update  # or: sudo dnf makecache",
        ),
    ),
    _Rule(
        re.compile(r"Connection refused", re.I),
        _fixed("The service you're trying to reach isn't running or isn't listening on that port."),
    ),
    _Rule(
        re.compile(r"Temporary failure in name resolution|Could not resolve host", re.I),
        _fixed("Your computer couldn't look up that address — check your internet connection."),
    ),
    _Rule(
        re.compile(r"Disk quota exceeded|No space left on device", re.I),
        _fixed("Your disk is full. Free up some space and try again.", "df -h"),
    ),
    _Rule(
        re.compile(r"Address already in use", re.I),
        _fixed(
            "Another program is already using that network port.",
            "ss -ltnp  # shows which program holds each port",
        ),
    ),
    _Rule(
        re.compile(r"Segmentation fault", re.I),
        _fixed("The program crashed (segmentation fault). This is a bug in that program."),
    ),
]


def explain_error(error_text: str) -> dict:
    """Analyse *error_text* with heuristic patterns.

    Args:
        error_text: The raw error output to analyse.

    Returns:
        dict with keys:
            "explanation": str — human-readable explanation
            "suggested_fix": str | None — a command to show the user, or None
    """
    text = (error_text or "").strip()
    if not text:
        return {
            "explanation": "Paste the full error message and I'll explain it.",
            "suggested_fix": None,
        }
    for rule in _RULES:
        match = rule.pattern.search(text)
        if match:
            logger.debug("Error matched pattern %r", rule.pattern.pattern)
            explanation, fix = rule.explain(match)
            return {"explanation": explanation, "suggested_fix": fix}

    echoed = text if len(text) <= _MAX_ECHO_CHARS else text[:_MAX_ECHO_CHARS] + "…"
    return {
        "explanation": (
            "I don't recognise this error yet. Here's what I captured:\n"
            f"```\n{echoed}\n```"
        ),
        "suggested_fix": None,
    }
