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


class FakeAI:
    """AIManager stand-in that records which buttons were pressed."""

    def __init__(self):
        from src.agent.ai_manager import AIStatus

        self.status = AIStatus()
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        if name in ("refresh", "start_ollama", "install_ollama", "warm_up", "use_model", "download"):
            return lambda *args: self.calls.append((name, *args))
        raise AttributeError(name)


def _state(stage_name, **kw):
    from src.agent.setup import SetupState, Stage

    return SetupState(Stage[stage_name], kw.pop("message", "msg"), **kw)


@pytest.fixture
def unready_drawer(qapp):
    from src.ui.drawer import DrawerWindow

    win = DrawerWindow(session=FakeSession(), setup=FakeSetup(), ai=FakeAI())
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


# ---------------------------------------------------------------------------
# Multi-step replies and the AI tab
# ---------------------------------------------------------------------------

def test_reply_shows_every_step_result(drawer):
    from src.ui.chat import MessageBubble

    before = len(drawer._chat._container.findChildren(MessageBubble))
    pending = {"action": "organize_files", "params": {"path": "~/Downloads"}}
    steps = [ActionResult("Note saved to x"), ActionResult("plan…", True, pending)]
    drawer._on_reply(Reply("Done.", action=steps[-1], steps=steps))
    texts = [b._label.text() for b in drawer._chat._container.findChildren(MessageBubble)][before:]
    assert texts == ["Done.", "Note saved to x", "plan…"]
    assert drawer._confirm_btn is not None  # the last step still needs confirmation


def test_setup_ready_warms_up_model_once(drawer):
    assert drawer._ai.calls.count(("warm_up",)) == 1
    drawer._on_setup_state(_state("READY", model="gemma4:e4b"))
    assert drawer._ai.calls.count(("warm_up",)) == 1


def test_opening_ai_tab_refreshes(drawer):
    drawer._tabs.setCurrentWidget(drawer._ai_view)
    assert ("refresh",) in drawer._ai.calls


def test_model_picked_in_ai_tab_finishes_setup(unready_drawer):
    win = unready_drawer
    win._on_model_changed("llama3.2:3b")
    assert win._chat_stack.currentIndex() == 1
    assert win._session.model == "llama3.2:3b"
    assert "llama3.2:3b" in win._subtitle.text()


def _ai_status(**kw):
    from src.actions.system import HardwareInfo
    from src.agent import models
    from src.agent.ai_manager import AIStatus
    from src.agent.ollama import InstalledModel, LoadedModel

    hw = HardwareInfo("Windows", 31, 24, 600)
    base = dict(
        installed=True, running=True, can_install=True, version="0.40.16",
        current_model="gemma4:e4b",
        models=(InstalledModel("gemma4:e4b", 6.6), InstalledModel("llama3.2:3b", 2.0)),
        loaded=(LoadedModel("gemma4:e4b", 7.0, 1.0),),
        recommended=models.recommend(hw), hardware=hw.summary(),
    )
    base.update(kw)
    return AIStatus(**base)


def _ai_view():
    from src.ui.ai_settings import AICallbacks, AISettingsView

    calls = []
    cb = AICallbacks(
        refresh=lambda: calls.append("refresh"), start=lambda: calls.append("start"),
        install=lambda: calls.append("install"), load=lambda: calls.append("load"),
        use=lambda name: calls.append(("use", name)), download=lambda tag: calls.append(("download", tag)),
    )
    return AISettingsView(cb), calls


def test_ai_view_connected_and_loaded(qapp):
    from PyQt6.QtWidgets import QPushButton

    view, calls = _ai_view()
    view.show_status(_ai_status())
    assert "Connected" in view._ollama_state.text() and "0.40.16" in view._ollama_state.text()
    assert "loaded (GPU)" in view._model_state.text()
    assert view._start_btn.isHidden() and view._install_btn.isHidden()
    assert view._load_btn.isHidden() and view._download_btn.isHidden()
    use_buttons = [b for b in view.findChildren(QPushButton) if b.text() == "Use"]
    assert len(use_buttons) == 1
    use_buttons[0].click()
    assert calls == [("use", "llama3.2:3b")]


def test_ai_view_not_running(qapp):
    view, calls = _ai_view()
    view.show_status(_ai_status(running=False, version=None, models=(), loaded=()))
    assert "not running" in view._ollama_state.text()
    assert not view._start_btn.isHidden()
    view._start_btn.click()
    assert calls == ["start"]


def test_ai_view_not_installed_offers_install(qapp):
    view, calls = _ai_view()
    view.show_status(_ai_status(installed=False, running=False, version=None, models=(), loaded=()))
    assert "Not installed" in view._ollama_state.text()
    view._install_btn.click()
    assert calls == ["install"]


def test_ai_view_offers_download_and_load(qapp):
    view, calls = _ai_view()
    view.show_status(_ai_status(models=(), loaded=(), current_model=None))
    assert not view._download_btn.isHidden()
    assert "6.6 GB" in view._download_btn.text()
    view._download_btn.click()
    assert calls == [("download", "gemma4:e4b")]

    view.show_status(_ai_status(loaded=()))
    assert "not loaded yet" in view._model_state.text()
    view._load_btn.click()
    assert calls[-1] == "load"


def test_ai_view_busy_disables_buttons(qapp):
    view, _ = _ai_view()
    view.show_status(_ai_status(busy="Downloading… 1.0 of 6.6 GB", progress=0.15, error=None))
    assert not view._refresh_btn.isEnabled()
    assert view._progress.value() == 150
    view.show_status(_ai_status(error="The download stopped: offline"))
    assert view._refresh_btn.isEnabled()
    assert "offline" in view._error.text()
