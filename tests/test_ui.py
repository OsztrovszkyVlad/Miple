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

    def set_model(self, model):
        self.model = model

    def shutdown(self):
        pass


class FakeSetup:
    """Setup flow that does nothing until the test pushes a state."""

    def __init__(self):
        from src.agent.setup import SetupState, Stage

        self.state = SetupState(Stage.CHECKING, "Checking…")
        self.clicks: list[str] = []

    def start(self):
        pass

    def primary(self):
        self.clicks.append("primary")

    def secondary(self):
        self.clicks.append("secondary")


def _state(stage_name, **kw):
    from src.agent.setup import SetupState, Stage

    return SetupState(Stage[stage_name], kw.pop("message", "msg"), **kw)


@pytest.fixture
def unready_drawer(qapp):
    from src.ui.drawer import DrawerWindow

    win = DrawerWindow(session=FakeSession(), setup=FakeSetup())
    yield win
    win.close()


@pytest.fixture
def drawer(unready_drawer):
    unready_drawer._on_setup_state(_state("READY", model="gemma4:e4b"))
    return unready_drawer


def test_setup_panel_shown_until_ready(unready_drawer):
    win = unready_drawer
    assert win._chat_stack.currentIndex() == 0
    win._entry.setText("hello")
    win._on_send()
    assert win._session.submitted == []  # not ready yet

    win._on_setup_state(_state("READY", model="gemma4:e4b"))
    assert win._chat_stack.currentIndex() == 1
    assert win._session.model == "gemma4:e4b"
    assert "gemma4:e4b" in win._subtitle.text()
    assert win._chat.has_messages()  # welcome message


def test_setup_needing_user_opens_drawer(unready_drawer):
    win = unready_drawer
    assert win.width() == 30
    win._on_setup_state(_state("NEED_MODEL", primary="Download (6.6 GB)", model="gemma4:e4b"))
    assert win._open
    win._setup_panel._primary.click()
    assert win._setup.clicks == ["primary"]


def test_setup_panel_progress(qapp):
    from src.ui.setup import SetupPanel

    panel = SetupPanel(on_primary=lambda: None, on_secondary=lambda: None)
    panel.show_state(_state("DOWNLOADING", progress=0.25, hardware="32 GB RAM"))
    assert panel._progress.value() == 250
    assert panel._primary.isHidden()
    assert "32 GB RAM" in panel._hardware.text()


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
