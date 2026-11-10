"""Tests for the action dispatcher (src.agent.actions)."""
from unittest.mock import patch

from src.agent import actions


def test_normalize_aliases_and_params():
    assert actions.normalize({"action": "Install", "params": {"package": "vlc"}}) == {
        "action": "install_app",
        "params": {"package": "vlc", "name": "vlc"},
    }
    assert actions.normalize({"action": "remind_me", "params": {"task": "milk", "time": "5pm"}}) == {
        "action": "save_note",
        "params": {"content": "milk", "title": "5pm"},
    }
    assert actions.normalize({"params": "garbage"}) == {"action": "no_action", "params": {}}


def test_organize_requires_confirmation(tmp_path):
    (tmp_path / "a.pdf").write_text("x")
    result = actions.dispatch({"action": "organize_files", "params": {"path": str(tmp_path)}})
    assert result.needs_confirmation
    assert result.pending_action["action"] == "organize_files"
    assert (tmp_path / "a.pdf").exists()  # dry run: nothing moved

    done = actions.confirm(result.pending_action)
    assert not done.needs_confirmation
    assert (tmp_path / "documents" / "a.pdf").exists()


def test_no_confirmation_offered_for_bad_path(tmp_path):
    result = actions.dispatch(
        {"action": "organize_files", "params": {"path": str(tmp_path / "missing")}}
    )
    assert not result.needs_confirmation
    assert result.pending_action is None


def test_aliased_install_can_be_confirmed():
    """Regression: an alias like 'install' used to break the confirm step."""
    with patch.object(actions.apps, "_build_install_cmd", return_value=["pkcon", "install", "-y", "vlc"]):
        preview = actions.dispatch({"action": "install", "params": {"name": "vlc"}})
        assert preview.needs_confirmation
        assert preview.pending_action["action"] == "install_app"
        with patch.object(actions.apps.threading, "Thread") as thread:
            result = actions.confirm(preview.pending_action)
    assert "Installing vlc" in result.message
    thread.return_value.start.assert_called_once()


def test_invalid_package_name_not_confirmable():
    result = actions.dispatch({"action": "install_app", "params": {"name": "--evil"}})
    assert not result.needs_confirmation
    assert "valid package name" in result.message


def test_save_note_runs_immediately(isolated_notes_dir):
    result = actions.dispatch({"action": "reminder", "params": {"text": "buy milk"}})
    assert "Note saved" in result.message
    saved = list(isolated_notes_dir.glob("*.md"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8").strip() == "buy milk"


def test_shell_command_is_only_shown():
    result = actions.dispatch({"action": "run_command", "params": {"command": "rm -rf /"}})
    assert "run this yourself" in result.message
    assert not result.needs_confirmation


def test_unknown_and_noop_actions_are_silent():
    assert actions.dispatch({"action": "dance"}).message == ""
    assert actions.dispatch({"action": "none"}).message == ""


def test_handler_exceptions_are_caught():
    with patch.object(actions.search, "google_search", side_effect=RuntimeError("boom")):
        result = actions.dispatch({"action": "search", "params": {"query": "x"}})
    assert "boom" in result.message
