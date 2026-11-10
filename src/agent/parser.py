"""Action parser — extract the action block embedded in a model response.

The model is prompted to end each reply with an object such as::

    Sure! {action: 'organize_files', params: {path: '~/Downloads'}}

Small local models are inconsistent about quoting, so both strict JSON and
JS-style object literals (unquoted keys, single-quoted strings) are accepted.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

_UNQUOTED_KEY_RE = re.compile(r"([{,])\s*([A-Za-z_]\w*)\s*:")
_SINGLE_QUOTED_RE = re.compile(r"'((?:[^'\\]|\\.)*)'")
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def split_action(text: str) -> tuple[dict | None, str]:
    """Separate the action block from the prose in *text*.

    Args:
        text: Full response text from the model.

    Returns:
        ``(action, prose)`` where *action* is the parsed dict (with at least an
        ``"action"`` key) or None, and *prose* is *text* with that block removed
        and surrounding whitespace stripped.
    """
    for match in re.finditer(r"\{", text):
        start = match.start()
        candidate = _extract_balanced(text, start)
        if candidate is None:
            continue
        data = _parse_object(candidate)
        if isinstance(data, dict) and "action" in data:
            logger.debug("Extracted action: %s", data)
            prose = (text[:start] + text[start + len(candidate):]).strip()
            return data, prose
    return None, text.strip()


def extract_action(text: str) -> dict | None:
    """Return the first action block found in *text*, or None."""
    return split_action(text)[0]


def strip_action(text: str) -> str:
    """Return *text* with its action block removed, for display."""
    return split_action(text)[1]


def _parse_object(candidate: str) -> dict | None:
    """Parse *candidate* as JSON, falling back to JS-literal normalisation."""
    for source in (candidate, _js_to_json(candidate)):
        try:
            data = json.loads(source)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _extract_balanced(text: str, start: int) -> str | None:
    """Return the balanced ``{...}`` substring starting at *start*, or None."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _js_to_json(js: str) -> str:
    """Best-effort conversion of a JS object literal to JSON.

    Handles unquoted keys, single-quoted strings and trailing commas.
    """
    s = _SINGLE_QUOTED_RE.sub(lambda m: json.dumps(m.group(1)), js)
    s = _UNQUOTED_KEY_RE.sub(r'\1 "\2":', s)
    return _TRAILING_COMMA_RE.sub(r"\1", s)
