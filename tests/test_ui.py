"""Headless smoke tests for the PyQt6 UI (uses the offscreen platform)."""
import pytest

pytest.importorskip("PyQt6")

from src.agent.actions import ActionResult  # noqa: E402
from src.agent.session import Reply  # noqa: E402


class FakeSession:
    """Records calls instead of talking to Ollama."""

    def __init__(self):
        self.submitted: list[str] = []
        self.confirmed: list[dict] = []

    def submit(self, text, on_reply):
        self.submitted.append(text)
        self.on_reply = on_reply

    def confirm(self, pending, on_result):
        self.confirmed.append(pending)

    def shutdown(self):
        pass


@pytest.fixture
def drawer(qapp):
    from src.ui.drawer import DrawerWindow

    win = DrawerWindow(session=FakeSession())
    yield win
    win.close()


def test_chat_view_messages(qapp):
    from src.ui.chat import ChatView

    view = ChatView()
    view.add_user_message("Hello")
    view.add_ai_message("Hi there")
    view.append_ai_token(" more text")
    view.show_typing()
    view.hide_typing()


def test_quick_action_bar_callback(qapp):
    from PyQt6.QtWidgets import QPushButton

    from src.ui.quickactions import QuickActionBar

    received: list[str] = []
    bar = QuickActionBar(on_action=received.append)
    bar.findChildren(QPushButton)[0].click()
    assert received == ["Organize my Downloads folder"]


def test_drawer_starts_closed_at_right_edge(drawer):
    geo = drawer._screen_geo
    assert drawer.width() == 30
    assert drawer.geometry().right() == geo.right()


def test_send_locks_input_until_reply(drawer):
    drawer._entry.setText("hello")
    drawer._on_send()
    assert drawer._session.submitted == ["hello"]
    assert not drawer._send_btn.isEnabled()

    drawer._entry.setText("second")
    drawer._on_send()  # ignored while busy
    assert drawer._session.submitted == ["hello"]

    drawer._on_reply(Reply("Hi!"))
    assert drawer._send_btn.isEnabled()


def test_confirm_flow(drawer):
    pending = {"action": "organize_files", "params": {"path": "~/Downloads"}}
    drawer._on_reply(Reply("Sure", action=ActionResult("plan…", True, pending)))
    assert drawer._confirm_btn is not None

    drawer._confirm_btn.click()
    assert drawer._session.confirmed == [pending]
    assert drawer._confirm_btn is None


def test_notes_view_lists_saved_notes(qapp):
    from src.actions.notes import save_note
    from src.ui.notes import NoteCard, NotesView

    save_note("first line\nsecond", title="groceries")
    view = NotesView()
    cards = view.findChildren(NoteCard)
    assert len(cards) == 1
