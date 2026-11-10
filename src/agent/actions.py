"""Central action dispatcher for Miple.

The model emits an action dict such as
``{"action": "organize_files", "params": {"path": "~/Downloads"}}``.
:func:`dispatch` normalises it (action aliases, param names), then either runs
it straight away (safe actions) or returns a dry-run preview that the UI must
confirm via :func:`confirm` (destructive actions).
"""
import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.actions import apps, errors, files, notes, search

logger = logging.getLogger(__name__)

NO_ACTION = "no_action"


@dataclass
class ActionResult:
    """Result returned by dispatch() or confirm()."""

    message: str
    needs_confirmation: bool = False
    pending_action: dict | None = None


# Common action name variants that the model may emit instead of canonical names.
_ACTION_ALIASES: dict[str, str] = {
    # Reminder variants → save_note
    "set_reminder": "save_note",
    "remind_me": "save_note",
    "reminder": "save_note",
    "note": "save_note",
    "take_note": "save_note",
    # Search variants → google_search
    "search": "google_search",
    "web_search": "google_search",
    "browse": "google_search",
    # App-launch variants → open_app
    "launch_app": "open_app",
    "run_app": "open_app",
    "start_app": "open_app",
    "open": "open_app",
    # App-install variants → install_app
    "install": "install_app",
    # File variants → organize_files
    "organise_files": "organize_files",
    "sort_files": "organize_files",
    # Error/command variants → explain_error
    "shell_execute": "explain_error",
    "run_command": "explain_error",
    "fix_error": "explain_error",
    # Clarification / no-op variants → silent no-op
    "request_clarification": NO_ACTION,
    "none": NO_ACTION,
    "null": NO_ACTION,
}

_NOTE_CONTENT_KEYS = ("content", "task", "text", "note", "message", "reminder")


def normalize(action_dict: dict) -> dict:
    """Return a canonical ``{"action": str, "params": dict}`` copy of *action_dict*."""
    raw = str(action_dict.get("action") or "").strip().lower()
    action = _ACTION_ALIASES.get(raw, raw) or NO_ACTION
    params = action_dict.get("params")
    params = dict(params) if isinstance(params, dict) else {}

    if action == "save_note":
        params = _normalize_note_params(params)
    elif action in ("open_app", "install_app") and "name" not in params:
        params["name"] = params.get("app") or params.get("package") or ""
    elif action == "google_search" and "query" not in params:
        params["query"] = params.get("q") or params.get("text") or ""
    return {"action": action, "params": params}


def _normalize_note_params(params: dict) -> dict:
    """Map the many ways a model names note content onto ``content``/``title``."""
    content = next((params[k] for k in _NOTE_CONTENT_KEYS if params.get(k)), None)
    title = params.get("title") or params.get("time")
    if content is None:
        content = " ".join(str(v) for v in params.values())
    return {"content": str(content), "title": str(title) if title else None}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _preview_organize(p: dict) -> str:
    return files.organize_files(path=p.get("path") or "~/Downloads", dry_run=True)


def _preview_install(p: dict) -> str:
    return apps.install_app(name=p.get("name", ""), dry_run=True)


def _run_open(p: dict) -> str:
    return apps.open_app(name=p.get("name", ""))


def _run_search(p: dict) -> str:
    return search.google_search(query=p.get("query", ""))


def _run_note(p: dict) -> str:
    return notes.save_note(content=p.get("content", ""), title=p.get("title"))


def _run_explain(p: dict) -> str:
    command = p.get("command") or p.get("cmd")
    if command and "error_text" not in p:
        return f"To do that, run this yourself:\n```\n{command}\n```"
    error_text = p.get("error_text") or p.get("error") or ""
    return _format_error_result(errors.explain_error(error_text=error_text))


# Destructive actions: previewed by dispatch(), executed only by confirm().
_PREVIEW_HANDLERS: dict[str, Callable[[dict], str]] = {
    "organize_files": _preview_organize,
    "install_app": _preview_install,
}

# Safe actions: executed immediately by dispatch().
_IMMEDIATE_HANDLERS: dict[str, Callable[[dict], str]] = {
    "open_app": _run_open,
    "google_search": _run_search,
    "save_note": _run_note,
    "explain_error": _run_explain,
}


def dispatch(action_dict: dict) -> ActionResult:
    """Route *action_dict* to the correct handler.

    Destructive actions are previewed with ``dry_run=True`` and returned with
    ``needs_confirmation=True``; the returned ``pending_action`` is the
    normalised dict to pass to :func:`confirm`. Safe actions run immediately.
    Unknown actions return an empty message.

    Args:
        action_dict: Dict with 'action' (str) and optional 'params' (dict).

    Returns:
        ActionResult describing what happened or what will happen.
    """
    normalized = normalize(action_dict)
    action, params = normalized["action"], normalized["params"]
    try:
        if action in _PREVIEW_HANDLERS:
            msg = _PREVIEW_HANDLERS[action](params)
            # Only offer confirmation if the preview produced a real plan.
            can_confirm = msg.startswith(files.PLAN_PREFIX) or msg.startswith(
                apps.INSTALL_PREVIEW_PREFIX
            )
            return ActionResult(msg, can_confirm, normalized if can_confirm else None)
        if action in _IMMEDIATE_HANDLERS:
            return ActionResult(_IMMEDIATE_HANDLERS[action](params))
        if action != NO_ACTION:
            logger.warning("Unknown action: %s", action)
        return ActionResult("")
    except Exception as exc:
        logger.error("dispatch() error for action '%s': %s", action, exc, exc_info=True)
        return ActionResult(f"Something went wrong trying to {action}: {exc}")


def confirm(
    pending_action: dict,
    on_complete: Callable[[str], None] | None = None,
) -> ActionResult:
    """Execute a previously-previewed destructive action for real.

    Args:
        pending_action: The ``pending_action`` from a prior dispatch() result.
        on_complete: Optional callback(message) invoked when a background
            action (install_app) finishes. Called from a worker thread.

    Returns:
        ActionResult with needs_confirmation=False.
    """
    normalized = normalize(pending_action)
    action, params = normalized["action"], normalized["params"]
    try:
        if action == "organize_files":
            path = params.get("path") or "~/Downloads"
            return ActionResult(files.organize_files(path=path, dry_run=False))
        if action == "install_app":
            name = params.get("name", "")
            return ActionResult(
                apps.install_app(name=name, dry_run=False, on_complete=on_complete)
            )
        return ActionResult(f"No confirmation handler for '{action}'.")
    except Exception as exc:
        logger.error("confirm() error for action '%s': %s", action, exc, exc_info=True)
        return ActionResult(f"Failed to execute {action}: {exc}")


def _format_error_result(result: dict) -> str:
    """Format an explain_error dict into a chat-ready string.

    The suggested fix command is wrapped in a fenced code block so the
    UI renders it as copyable monospace text; it is never auto-executed.
    """
    msg = result.get("explanation", "An error occurred.")
    fix = result.get("suggested_fix")
    if fix:
        msg += f"\n\nSuggested fix:\n```\n{fix}\n```"
    return msg
