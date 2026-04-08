"""Smoke tests for GTK4 UI components."""
import os
import pytest

try:
    import gi  # noqa: F401
    _HAS_GI = True
except ImportError:
    _HAS_GI = False

_HAS_DISPLAY = bool(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
)
_skip_no_display = pytest.mark.skipif(
    not (_HAS_GI and _HAS_DISPLAY),
    reason="PyGObject or display server not available",
)


@_skip_no_display
def test_chat_view_add_user_message():
    """ChatView.add_user_message should not raise."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    from src.ui.chat import ChatView

    app = Gtk.Application(application_id="com.miple.test.chat")

    def on_activate(a):
        view = ChatView()
        view.add_user_message("Hello")
        view.add_user_message("World")
        a.quit()

    app.connect("activate", on_activate)
    app.run([])


@_skip_no_display
def test_chat_view_add_ai_message():
    """ChatView.add_ai_message and append_ai_token should not raise."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    from src.ui.chat import ChatView

    app = Gtk.Application(application_id="com.miple.test.ai")

    def on_activate(a):
        view = ChatView()
        view.add_ai_message("Hi there")
        view.append_ai_token(" more text")
        a.quit()

    app.connect("activate", on_activate)
    app.run([])


@_skip_no_display
def test_typing_indicator_start_stop():
    """TypingIndicator start/stop should not raise."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    from src.ui.chat import TypingIndicator

    app = Gtk.Application(application_id="com.miple.test.typing")

    def on_activate(a):
        indicator = TypingIndicator()
        indicator.start()
        indicator.stop()
        a.quit()

    app.connect("activate", on_activate)
    app.run([])


@_skip_no_display
def test_quick_action_bar_callback():
    """QuickActionBar should call on_action with correct text."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    from src.ui.quickactions import QuickActionBar

    received: list[str] = []
    app = Gtk.Application(application_id="com.miple.test.qa")

    def on_activate(a):
        bar = QuickActionBar(on_action=received.append)
        # Simulate clicking the first button
        first_btn = list(bar)[0]
        first_btn.emit("clicked")
        a.quit()

    app.connect("activate", on_activate)
    app.run([])
    assert received == ["Organize my Downloads folder"]
