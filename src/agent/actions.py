"""Central action dispatcher for Miple."""
import logging
from dataclasses import dataclass

from src.actions import apps, errors, files, notes, search

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result returned by dispatch() or confirm()."""

    message: str
    needs_confirmation: bool
    pending_action: dict | None


# Common action name variants that the model may emit instead of canonical names.
_ACTION_ALIASES: dict[str, str] = {
    # Reminder variants → save_note
    "set_reminder": "save_note",
    "remind_me":    "save_note",
    "reminder":     "save_note",
    # Search variants → google_search
    "search":           "google_search",
    "web_search":       "google_search",
    "browse":           "google_search",
    # App-launch variants → open_app
    "launch_app":       "open_app",
    "run_app":          "open_app",
    "start_app":        "open_app",
    "open":             "open_app",
    # App-install variants → install_app
    "install":          "install_app",
    # Error/command variants → explain_error
    "shell_execute":    "explain_error",
    "run_command":      "explain_error",
    # Clarification / no-op variants → silent no-op
    "request_clarification": "no_action",
    "none":                  "no_action",
    "no_action":             "no_action",
    "null":                  "no_action",
}


def dispatch(action_dict: dict) -> ActionResult:
    """Route *action_dict* to the correct handler.

    Destructive actions (organize_files, install_app) are previewed with
    dry_run=True and returned with needs_confirmation=True so the UI can
    prompt the user before anything is changed.

    Non-destructive actions are executed immediately.
    Unknown action names are resolved through _ACTION_ALIASES before dispatch.

    Args:
        action_dict: Dict with 'action' (str) and optional 'params' (dict).

    Returns:
        ActionResult describing what happened or what will happen.
    """
    action = _ACTION_ALIASES.get(
        action_dict.get("action", ""),
        action_dict.get("action", ""),
    )
    params = action_dict.get("params", {})
    # Params normalisation for shell/command aliases routed to explain_error
    if action == "explain_error" and "error_text" not in params:
        command = params.get("command", params.get("cmd", ""))
        if command:
            return ActionResult(
                f"To fix this, run:\n```\n{command}\n```",
                needs_confirmation=False,
                pending_action=None,
            )
        params = {"error_text": str(params)}

    if action == "save_note" and "content" not in params:
        if "task" in params:
            params = {"content": params["task"], "title": params.get("time", "")}
        elif "text" in params:
            params = {"content": params["text"]}
        elif "note" in params:
            params = {"content": params["note"]}
        elif "message" in params:
            params = {"content": params["message"]}
        else:
            params = {"content": str(params)}
    try:
        if action == "organize_files":
            path = params.get("path", "~/Downloads")
            msg = files.organize_files(path=path, dry_run=True)
            return ActionResult(msg, needs_confirmation=True, pending_action=action_dict)

        if action == "install_app":
            name = params.get("name", "")
            msg = apps.install_app(name=name, dry_run=True)
            return ActionResult(msg, needs_confirmation=True, pending_action=action_dict)

        if action == "open_app":
            name = params.get("name", "")
            msg = apps.open_app(name=name)
            return ActionResult(msg, needs_confirmation=False, pending_action=None)

        if action == "google_search":
            query = params.get("query", "")
            msg = search.google_search(query=query)
            return ActionResult(msg, needs_confirmation=False, pending_action=None)

        if action == "save_note":
            content = params.get("content", "")
            title = params.get("title", None)
            msg = notes.save_note(content=content, title=title)
            return ActionResult(msg, needs_confirmation=False, pending_action=None)

        if action == "explain_error":
            error_text = params.get("error_text", "")
            result = errors.explain_error(error_text=error_text)
            msg = _format_error_result(result)
            return ActionResult(msg, needs_confirmation=False, pending_action=None)

        logger.warning("Unknown or no-op action: %s", action)
        return ActionResult("", needs_confirmation=False, pending_action=None)
    except Exception as exc:
        logger.error("dispatch() error for action '%s': %s", action, exc, exc_info=True)
        return ActionResult(
            f"Something went wrong trying to {action}: {exc}",
            needs_confirmation=False,
            pending_action=None,
        )


def confirm(
    pending_action: dict,
    on_complete=None,
) -> ActionResult:
    """Execute a previously-staged destructive action with dry_run=False.

    Args:
        pending_action: The original action_dict from a prior dispatch() call.
        on_complete: Optional callback(message: str) invoked when a background
                     action (e.g. install_app) finishes.

    Returns:
        ActionResult with needs_confirmation=False.
    """
    action = pending_action.get("action", "")
    params = pending_action.get("params", {})
    try:
        if action == "organize_files":
            path = params.get("path", "~/Downloads")
            msg = files.organize_files(path=path, dry_run=False)
            return ActionResult(msg, needs_confirmation=False, pending_action=None)

        if action == "install_app":
            name = params.get("name", "")
            msg = apps.install_app(name=name, dry_run=False, on_complete=on_complete)
            return ActionResult(msg, needs_confirmation=False, pending_action=None)

        return ActionResult(
            f"No confirmation handler for '{action}'.",
            needs_confirmation=False,
            pending_action=None,
        )
    except Exception as exc:
        logger.error("confirm() error for action '%s': %s", action, exc, exc_info=True)
        return ActionResult(
            f"Failed to execute {action}: {exc}",
            needs_confirmation=False,
            pending_action=None,
        )


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
