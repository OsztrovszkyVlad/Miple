"""DrawerWindow — frameless right-edge sidebar for Miple (PyQt6)."""
import logging

from PyQt6.QtCore import QEasingCurve, QObject, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from src.agent.actions import ActionResult
from src.agent.session import AssistantSession, Reply
from src.agent.setup import SetupFlow, SetupState, Stage
from src.ui.chat import ChatView
from src.ui.notes import NotesView
from src.ui.quickactions import QuickActionBar
from src.ui.setup import SetupPanel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
_TAB_W = 30       # pull-tab width — never changes
_CONTENT_W = 430  # content panel width when fully open
_ANIM_MS = 200    # animation duration in milliseconds


# ---------------------------------------------------------------------------
# Cross-thread signal bridge
# ---------------------------------------------------------------------------

class _Signals(QObject):
    """Emitted from worker threads; Qt delivers them on the GUI thread."""

    reply = pyqtSignal(object)          # Reply
    action_result = pyqtSignal(object)  # ActionResult
    setup_state = pyqtSignal(object)    # SetupState


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class DrawerWindow(QWidget):
    """Frameless, always-on-top sidebar anchored to the screen's right edge.

    The window's right edge is always flush with the screen's right edge;
    only its width changes::

        closed:                     |tab|   (30 px wide)
        open:   |tab| content 430 px     |   (460 px wide)

    The pull tab sits at the window's left edge, so it slides out with the
    drawer. Because the window is never wider than what is visible, it does
    not swallow clicks meant for the windows underneath.

    Animation: QVariantAnimation on the window width, 200 ms, OutCubic.
    Esc closes the drawer.
    """

    def __init__(
        self,
        session: AssistantSession | None = None,
        setup: SetupFlow | None = None,
    ) -> None:
        """Initialise window, compute geometry, build UI, start animation."""
        super().__init__()

        # Frameless, always on top, no taskbar entry
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Transparent background — only child widgets are visible
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        # The window hugs the right screen edge and is only as wide as what
        # is visible, so it never blocks clicks on the windows underneath.
        self._screen_geo = QApplication.primaryScreen().availableGeometry()
        self._apply_width(_TAB_W)

        # Drawer state
        self._open = False

        # Assistant
        self._session = session or AssistantSession()
        self._ready = False
        self._busy = False
        self._signals = _Signals()
        self._signals.reply.connect(self._on_reply)
        self._signals.action_result.connect(self._on_action_result)
        self._signals.setup_state.connect(self._on_setup_state)
        self._setup = setup or SetupFlow(self._signals.setup_state.emit)
        self._pending_action: dict | None = None
        self._confirm_btn: QPushButton | None = None

        self._build_ui()
        self._setup_animation()
        QTimer.singleShot(0, self._setup.start)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._close_drawer)

    def _build_ui(self) -> None:
        """Build the pull tab and the content panel (chat + notes tabs)."""

        # --- Pull tab (always visible, leftmost) ---
        self._tab = QPushButton("‹", self)
        self._tab.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: none;
                border-top-left-radius: 8px;
                border-bottom-left-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover  { background-color: #45475a; }
            QPushButton:pressed { background-color: #585b70; }
        """)
        self._tab.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab.clicked.connect(self._toggle)

        # --- Content panel (revealed as the window widens) ---
        self._content = QWidget(self)
        self._content.setStyleSheet("background-color: #1e1e2e;")

        col = QVBoxLayout(self._content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_header())

        # Tab widget — Chat | Notes
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane  { border: none; background: #1e1e2e; }
            QTabBar::tab {
                background: #181825;
                color: #6c7086;
                padding: 6px 18px;
                border: none;
                font-size: 13px;
            }
            QTabBar::tab:selected { background: #1e1e2e; color: #cdd6f4; }
            QTabBar::tab:hover    { color: #cdd6f4; }
        """)

        # Chat page
        chat_page = QWidget()
        chat_page.setStyleSheet("background-color: #1e1e2e;")
        chat_col = QVBoxLayout(chat_page)
        chat_col.setContentsMargins(0, 0, 0, 0)
        chat_col.setSpacing(0)
        self._quick_bar = QuickActionBar(on_action=self._populate_entry)
        chat_col.addWidget(self._quick_bar)
        self._chat = ChatView()
        chat_col.addWidget(self._chat, stretch=1)
        chat_col.addWidget(self._build_input_row())

        # Notes page
        self._notes_view = NotesView()

        self._setup_panel = SetupPanel(
            on_primary=self._setup.primary, on_secondary=self._setup.secondary
        )
        self._setup_panel.show_state(self._setup.state)
        self._chat_stack = QStackedWidget()
        self._chat_stack.addWidget(self._setup_panel)
        self._chat_stack.addWidget(chat_page)
        tabs.addTab(self._chat_stack, "Chat")
        tabs.addTab(self._notes_view, "Notes")
        col.addWidget(tabs, stretch=1)

        self._place_children()

    def _place_children(self) -> None:
        """Pin the tab to the left edge and the panel right of it.

        The panel always has its full width; when the window is narrower
        than tab + panel, the window edge simply clips it.
        """
        h = self.height()
        self._tab.setGeometry(0, 0, _TAB_W, h)
        self._content.setGeometry(_TAB_W, 0, _CONTENT_W, h)

    def resizeEvent(self, event) -> None:
        """Keep children sized to the window height."""
        super().resizeEvent(event)
        self._place_children()

    def _build_header(self) -> QWidget:
        """Purple-circle M avatar  |  Miple / your AI, locally."""
        header = QWidget()
        header.setFixedHeight(64)
        header.setObjectName("mipleHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Scoped by object name so the border doesn't cascade onto child widgets.
        header.setStyleSheet(
            "#mipleHeader { background-color: #181825; border-bottom: 1px solid #313244; }"
        )

        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        avatar = QLabel("M")
        avatar.setFixedSize(40, 40)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("""
            QLabel {
                background-color: #7c3aed;
                color: white;
                border-radius: 20px;
                font-weight: bold;
                font-size: 18px;
            }
        """)

        text_col = QWidget()
        text_layout = QVBoxLayout(text_col)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        name_lbl = QLabel("Miple")
        name_lbl.setStyleSheet(
            "color: #cdd6f4; font-weight: bold; font-size: 15px;"
        )
        sub_lbl = QLabel("your AI, locally")
        self._subtitle = sub_lbl
        sub_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        text_layout.addWidget(name_lbl)
        text_layout.addWidget(sub_lbl)

        layout.addWidget(avatar)
        layout.addWidget(text_col)
        layout.addStretch()
        return header

    def _build_input_row(self) -> QWidget:
        """Text entry + Send button at the bottom of the content panel."""
        row = QWidget()
        row.setObjectName("mipleInputRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Scoped by object name so the border doesn't cascade onto child widgets.
        row.setStyleSheet(
            "#mipleInputRow { background-color: #181825; border-top: 1px solid #313244; }"
        )

        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        self._entry = QLineEdit()
        self._entry.setPlaceholderText("Ask Miple anything…")
        self._entry.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus { border-color: #7c3aed; }
        """)
        self._entry.returnPressed.connect(self._on_send)

        send_btn = QPushButton("Send")
        self._send_btn = send_btn
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover  { background-color: #6d28d9; }
            QPushButton:pressed { background-color: #5b21b6; }
        """)
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.clicked.connect(self._on_send)

        layout.addWidget(self._entry)
        layout.addWidget(send_btn)
        return row

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _setup_animation(self) -> None:
        """Create the animation that slides the window open and closed."""
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(_ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._apply_width)

    def _apply_width(self, width: int) -> None:
        """Resize the window to *width*, keeping it flush with the right edge."""
        geo = self._screen_geo
        self.setGeometry(geo.x() + geo.width() - width, geo.y(), width, geo.height())

    def _toggle(self) -> None:
        """Open or close the drawer."""
        self._open = not self._open
        # ‹ = closed (drawer shut, click to open)
        # › = open  (drawer showing, click to close)
        self._tab.setText("›" if self._open else "‹")
        self._anim.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(_TAB_W + _CONTENT_W if self._open else _TAB_W)
        self._anim.start()
        if self._open:
            self.activateWindow()
            self._entry.setFocus()
        logger.debug("Drawer %s", "opening" if self._open else "closing")

    def _close_drawer(self) -> None:
        """Close the drawer if it is open (bound to Esc)."""
        if self._open:
            self._toggle()

    def open_drawer(self) -> None:
        """Open the drawer if it is closed."""
        if not self._open:
            self._toggle()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _populate_entry(self, text: str) -> None:
        """Pre-fill the entry from a QuickActionBar button press."""
        self._entry.setText(text)
        self._entry.setFocus()

    def _on_send(self) -> None:
        """Validate input and hand it to the assistant session."""
        text = self._entry.text().strip()
        if not text or self._busy or not self._ready:
            return
        self._clear_confirm_button()
        self._entry.clear()
        self._chat.add_user_message(text)
        self._chat.show_typing()
        self._set_busy(True)
        self._session.submit(text, self._signals.reply.emit)

    def _set_busy(self, busy: bool) -> None:
        """Lock the input while a reply is pending."""
        self._busy = busy
        self._send_btn.setEnabled(not busy)
        self._entry.setPlaceholderText(
            "Miple is thinking…" if busy else "Ask Miple anything…"
        )

    # ------------------------------------------------------------------
    # Results (always on the GUI thread)
    # ------------------------------------------------------------------

    def _on_reply(self, reply: Reply) -> None:
        """Show the model's reply and any action result."""
        self._chat.hide_typing()
        if reply.text:
            self._chat.add_ai_message(reply.text)
        if reply.action is not None:
            self._on_action_result(reply.action)
        self._set_busy(False)
        self._notes_view.refresh()   # pick up any note saved during this turn
        self._entry.setFocus()

    def _on_action_result(self, result: ActionResult) -> None:
        """Show an action result; offer a confirm button if it needs one."""
        if result.message:
            self._chat.add_ai_message(result.message)
        if result.needs_confirmation and result.pending_action is not None:
            self._pending_action = result.pending_action
            self._show_confirm_button()

    def _show_confirm_button(self) -> None:
        """Add a green 'Yes, do it' pill to the QuickActionBar."""
        if self._confirm_btn is not None:
            return
        self._confirm_btn = QPushButton("Yes, do it")
        self._confirm_btn.clicked.connect(self._on_confirm)
        self._quick_bar.add_confirm_button(self._confirm_btn)

    def _on_confirm(self) -> None:
        """Execute the pending action in the background."""
        if self._pending_action is None:
            return
        pending = self._pending_action
        self._clear_confirm_button()
        self._session.confirm(pending, self._signals.action_result.emit)

    def _clear_confirm_button(self) -> None:
        """Remove the confirm button and reset pending state."""
        if self._confirm_btn is not None:
            self._quick_bar.remove_confirm_button(self._confirm_btn)
            self._confirm_btn = None
        self._pending_action = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _on_setup_state(self, state: SetupState) -> None:
        """Show setup progress; switch to the chat once everything is ready."""
        self._setup_panel.show_state(state)
        if state.stage is Stage.READY and state.model:
            self._session.set_model(state.model)
            self._subtitle.setText(f"your AI, locally · {state.model}")
            self._chat_stack.setCurrentIndex(1)
            if not self._ready and not self._chat.has_messages():
                self._chat.add_ai_message(
                    "Hi! I'm Miple. Ask me to tidy a folder, open or install an app, "
                    "search the web, explain an error or save a note."
                )
            self._ready = True
            return
        self._ready = False
        self._chat_stack.setCurrentIndex(0)
        if not state.busy:
            self.open_drawer()  # needs the user: make sure they see it

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop background work when the window closes."""
        self._session.shutdown()
        super().closeEvent(event)
