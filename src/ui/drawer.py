"""DrawerWindow — frameless right-edge sidebar for Miple (PyQt6)."""
import asyncio
import logging
import re
import threading

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QWidget, QBoxLayout, QHBoxLayout, QVBoxLayout,
    QPushButton, QLineEdit, QLabel, QApplication, QSizePolicy, QTabWidget,
)

from src.ui.chat import ChatView
from src.ui.notes import NotesView
from src.ui.quickactions import QuickActionBar
from src.agent.ollama import OllamaClient
from src.agent import parser
from src.agent.actions import ActionResult, confirm, dispatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
_TAB_W = 30       # pull-tab width — never changes
_CONTENT_W = 430  # content panel width when fully open
_ANIM_MS = 200    # animation duration in milliseconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_action_json(text: str) -> str:
    """Remove the action JSON block from model response text for display.

    Walks the text looking for balanced {…} blocks that contain the word
    'action'. The first such block is removed; the remaining prose is
    returned so users never see raw JSON in the chat UI.
    """
    for match in re.finditer(r"\{", text):
        start = match.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    if "action" in candidate:
                        return (text[:start] + text[i + 1 :]).strip()
                    break
    return text.strip()


# ---------------------------------------------------------------------------
# Cross-thread signal bridge
# ---------------------------------------------------------------------------

class _Signals(QObject):
    """Emitted from the Ollama worker thread; delivered to the main thread."""
    token = pyqtSignal(str)
    done = pyqtSignal()
    action_result = pyqtSignal(object)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class DrawerWindow(QWidget):
    """Frameless, always-on-top sidebar anchored to the screen right edge.

    The window is FIXED SIZE and never moves:
        x = screen_x + screen_w - 460
        y = screen_y
        w = 460   (TAB_W + CONTENT_W)
        h = available screen height

    The window background is fully transparent (WA_TranslucentBackground).
    Only the tab button and content panel have visible backgrounds, so the
    transparent 430 px on the left is invisible when the drawer is closed.

    Layout direction is LeftToRight; tab is always the leftmost element:

        | tab 30 px | ← content 0–430 px → | ← transparent gap → |

    Animation
    ---------
    QPropertyAnimation on content.maximumWidth:
        Closed → maximumWidth = 0   (content invisible, tab at right edge)
        Open   → maximumWidth = 430 (content fills leftward from the tab)
    Duration 200 ms, OutCubic easing.
    """

    def __init__(self) -> None:
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

        # Fixed window geometry — set once, never changed
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()   # excludes taskbars on all edges
        screen_x = geo.x()
        screen_y = geo.y()
        screen_w = geo.width()
        screen_h = geo.height()
        win_w = _TAB_W + _CONTENT_W        # 460 px
        self.setGeometry(
            screen_x + screen_w - win_w,   # x: right edge flush to screen
            screen_y,                       # y: just below top taskbar
            win_w,                          # width: fixed 460 px
            screen_h,                       # height: full available height
        )
        logger.debug(
            "Window geometry: %d×%d at (%d,%d)",
            win_w, screen_h,
            screen_x + screen_w - win_w, screen_y,
        )

        # Drawer state
        self._open = False

        # Ollama
        self._ollama = OllamaClient()
        self._chat_history: list[dict] = []
        self._first_token: bool = True
        self._signals = _Signals()
        self._signals.token.connect(self._on_token)
        self._signals.done.connect(self._on_done)
        self._signals.action_result.connect(self._on_action_result)
        self._pending_action: dict | None = None
        self._confirm_btn: QPushButton | None = None

        self._build_ui()
        self._setup_animation()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the widget tree inside the fixed window.

        Layout direction is LeftToRight; addWidget order is visual order:
            root.addWidget(tab)     → leftmost   (0–30 px)
            root.addWidget(content) → right of tab (30–460 px, animated)
        """
        root = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Pull tab (always visible, leftmost) ---
        self._tab = QPushButton("‹")
        self._tab.setFixedWidth(_TAB_W)
        self._tab.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
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
        root.addWidget(self._tab)           # → rightmost position

        # --- Content panel (animates in/out to the left of the tab) ---
        self._content = QWidget()
        self._content.setMinimumWidth(0)
        self._content.setMaximumWidth(0)    # start closed
        self._content.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
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

        tabs.addTab(chat_page, "Chat")
        tabs.addTab(self._notes_view, "Notes")
        col.addWidget(tabs, stretch=1)

        root.addWidget(self._content)       # → right of tab button, expands

    def _build_header(self) -> QWidget:
        """Purple-circle M avatar  |  Miple / your AI, locally."""
        header = QWidget()
        header.setFixedHeight(64)
        header.setStyleSheet(
            "background-color: #181825; border-bottom: 1px solid #313244;"
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
        row.setStyleSheet(
            "background-color: #181825; border-top: 1px solid #313244;"
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
        """Create the QPropertyAnimation for content panel width."""
        self._anim = QPropertyAnimation(self._content, b"maximumWidth")
        self._anim.setDuration(_ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _toggle(self) -> None:
        """Open or close the drawer."""
        self._open = not self._open
        # ‹ = closed (drawer shut, click to open)
        # › = open  (drawer showing, click to close)
        self._tab.setText("›" if self._open else "‹")
        self._anim.stop()
        self._anim.setStartValue(self._content.maximumWidth())
        self._anim.setEndValue(_CONTENT_W if self._open else 0)
        self._anim.start()
        logger.debug("Drawer %s", "opening" if self._open else "closing")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _populate_entry(self, text: str) -> None:
        """Pre-fill the entry from a QuickActionBar button press."""
        self._entry.setText(text)
        self._entry.setFocus()

    def _on_send(self) -> None:
        """Validate input and dispatch to Ollama."""
        self._clear_confirm_button()
        text = self._entry.text().strip()
        if not text:
            return
        self._entry.clear()
        self._chat_history.append({"role": "user", "content": text})
        self._chat.add_user_message(text)
        self._chat.show_typing()
        self._first_token = True

        messages = list(self._chat_history)
        threading.Thread(
            target=self._run_ollama, args=(messages,), daemon=True
        ).start()

    # ------------------------------------------------------------------
    # Ollama integration
    # ------------------------------------------------------------------

    def _run_ollama(self, messages: list[dict]) -> None:
        """Entry point for the background daemon thread."""
        asyncio.run(self._stream_ollama(messages))

    async def _stream_ollama(self, messages: list[dict]) -> None:
        """Collect the full model response, then emit clean text to the UI.

        Tokens are collected silently while the typing indicator shows.
        After the full response arrives:
        1. The action JSON block is stripped before display so users only
           see the friendly prose.
        2. The raw response (with JSON) is stored in chat history so the
           model keeps correct context.
        3. If an action block was found, it is dispatched.
        """
        collected: list[str] = []
        async for token in self._ollama.chat(messages):
            logger.debug("Token received: %r", token)
            collected.append(token)
        full_response = "".join(collected)
        logger.debug("Full response: %r", full_response)
        self._chat_history.append(
            {"role": "assistant", "content": full_response}
        )
        display_text = _strip_action_json(full_response)
        if display_text:
            self._signals.token.emit(display_text)  # shown as a single bubble
        action_dict = parser.extract_action(full_response)
        if action_dict is not None:
            result = dispatch(action_dict)
            self._signals.action_result.emit(result)
        self._signals.done.emit()

    def _on_token(self, token: str) -> None:
        """Receive a streaming token on the main thread."""
        if self._first_token:
            self._chat.hide_typing()
            self._chat.add_ai_message(token)
            self._first_token = False
        else:
            self._chat.append_ai_token(token)

    def _on_action_result(self, result: ActionResult) -> None:
        """Handle an action result from the dispatcher on the main thread."""
        logger.debug("_on_action_result called: needs_confirmation=%s message=%r",
                     result.needs_confirmation, result.message[:80])
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
        """Execute the pending action and clear the confirm button."""
        if self._pending_action is None:
            return
        pending = self._pending_action
        self._clear_confirm_button()

        def _on_install_done(message: str) -> None:
            self._signals.action_result.emit(
                ActionResult(message, needs_confirmation=False, pending_action=None)
            )

        result = confirm(pending, on_complete=_on_install_done)
        if result.message:
            self._chat.add_ai_message(result.message)

    def _clear_confirm_button(self) -> None:
        """Remove the confirm button and reset pending state."""
        if self._confirm_btn is not None:
            self._quick_bar.remove_confirm_button(self._confirm_btn)
            self._confirm_btn = None
        self._pending_action = None

    def _on_done(self) -> None:
        """Called when the Ollama stream ends."""
        self._chat.hide_typing()
        self._notes_view.refresh()   # pick up any note saved during this turn
        logger.debug("Ollama stream complete")
