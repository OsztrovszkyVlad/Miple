"""Action JSON parser — extract action blocks from model response text."""
import json
import logging
import re

logger = logging.getLogger(__name__)

# Match JSON objects that contain an "action" key anywhere in a response
_ACTION_RE = re.compile(r'\{[^{}]*"action"\s*:', re.DOTALL)
# Also match single-quoted JS-style: {action: 'name', ...}
_ACTION_RE_LOOSE = re.compile(r'\{[^{}]*action\s*:', re.DOTALL)


def extract_action(text: str) -> dict | None:
    """Search *text* for an embedded action JSON block.

    The model may emit the block inline with prose, e.g.:
        "Sure! {action: 'organize_files', params: {path: '~/Downloads'}}"

    Handles both strict JSON (double-quoted keys) and JS-style object
    literals (unquoted keys, single-quoted values).

    Args:
        text: Full response text from the model.

    Returns:
        Parsed action dict with at least an 'action' key, or None.
    """
    # Try strict JSON first
    for match in re.finditer(r'\{', text):
        start = match.start()
        candidate = _extract_balanced(text, start)
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
            if "action" in data:
                logger.debug("Extracted action (JSON): %s", data)
                return data
        except json.JSONDecodeError:
            pass

    # Try JS-style object literals (unquoted keys, single quotes)
    for match in re.finditer(r'\{', text):
        start = match.start()
        candidate = _extract_balanced(text, start)
        if candidate is None:
            continue
        normalised = _js_to_json(candidate)
        if normalised is None:
            continue
        try:
            data = json.loads(normalised)
            if "action" in data:
                logger.debug("Extracted action (JS-style): %s", data)
                return data
        except json.JSONDecodeError:
            pass

    return None


def _extract_balanced(text: str, start: int) -> str | None:
    """Extract a balanced {...} substring starting at *start*.

    Args:
        text: The full text to search.
        start: Index of the opening '{'.

    Returns:
        The substring including braces, or None if unbalanced.
    """
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _js_to_json(js: str) -> str | None:
    """Best-effort conversion of a JS object literal to valid JSON.

    Handles:
    - Unquoted keys:  {action: 'x'}  →  {"action": "x"}
    - Single-quoted values
    - Trailing commas (removed)

    Args:
        js: A JS-style object literal string.

    Returns:
        A valid JSON string, or None on failure.
    """
    try:
        # Quote unquoted keys
        s = re.sub(r"(\{|,)\s*(\w+)\s*:", r'\1 "\2":', js)
        # Replace single-quoted strings with double-quoted
        s = re.sub(r"'([^']*)'", r'"\1"', s)
        # Remove trailing commas before } or ]
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s
    except Exception:
        return None
