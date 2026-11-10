"""Chat UI components — MessageBubble, TypingIndicator, ChatView."""
import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QScrollArea,
)

logger = logging.getLogger(__name__)

# Colours
_BG_USER = "#7c3aed"
_BG_AI = "#313244"
_FG_USER = "#ffffff"
_FG_AI = "#cdd6f4"
_BG_CHAT = "#1e1e2e"

# Maximum bubble width in pixels
_BUBBLE_MAX_PX = 300


class MessageBubble(QWidget):
    """A single chat message rendered as a coloured rounded bubble."""

    def __init__(self, text: str, is_user: bool) -> None:
        """Create a bubble. Right-aligned + purple for user, left + gray for AI."""
        super().__init__()

        bg = _BG_USER if is_user else _BG_AI
        fg = _FG_USER if is_user else _FG_AI

        self._label = QLabel(text)
        # AI replies may contain Markdown (e.g. fenced fix commands); user
        # text is always shown verbatim.
        self._label.setTextFormat(
            Qt.TextFormat.PlainText if is_user else Qt.TextFormat.MarkdownText
        )
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(_BUBBLE_MAX_PX)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._label.setOpenExternalLinks(True)
        self._label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border-radius: 12px;
                padding: 8px 12px;
                font-size: 13px;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(0)

        if is_user:
            row.addStretch()
            row.addWidget(self._label)
        else:
            row.addWidget(self._label)
            row.addStretch()

    def append_text(self, token: str) -> None:
        """Append *token* to the bubble's text (streaming support)."""
        self._label.setText(self._label.text() + token)


class TypingIndicator(QWidget):
    """Animated 'Miple is thinking…' label with cycling ellipsis."""

    _STATES = ("Miple is thinking.", "Miple is thinking..", "Miple is thinking...")

    def __init__(self) -> None:
        """Create the indicator (hidden by default)."""
        super().__init__()
        self._idx = 0

        self._label = QLabel(self._STATES[0])
        self._label.setStyleSheet(
            "color: #6c7086; font-style: italic; font-size: 12px;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(self._label)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        """Begin ellipsis animation."""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop ellipsis animation."""
        self._timer.stop()

    def _tick(self) -> None:
        """Advance the ellipsis state."""
        self._idx = (self._idx + 1) % len(self._STATES)
        self._label.setText(self._STATES[self._idx])


class ChatView(QScrollArea):
    """Scrollable list of MessageBubbles with typing indicator support."""

    def __init__(self) -> None:
        """Create an empty chat view."""
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet(f"background-color: {_BG_CHAT}; border: none;")

        self._container = QWidget()
        self._container.setStyleSheet(f"background-color: {_BG_CHAT};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setSpacing(2)
        self._layout.setContentsMargins(4, 8, 4, 8)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._container)

        self._typing = TypingIndicator()
        self._typing_visible = False
        self._last_ai_bubble: MessageBubble | None = None

    def add_user_message(self, text: str) -> None:
        """Append a user message bubble."""
        self.hide_typing()
        bubble = MessageBubble(text, is_user=True)
        self._layout.addWidget(bubble)
        self._scroll_to_bottom()
        logger.debug("User: %s", text[:60])

    def add_ai_message(self, text: str) -> None:
        """Append an AI message bubble and keep a reference for streaming."""
        bubble = MessageBubble(text, is_user=False)
        self._last_ai_bubble = bubble
        self._layout.addWidget(bubble)
        self._scroll_to_bottom()

    def append_ai_token(self, token: str) -> None:
        """Append *token* to the last AI bubble (streaming)."""
        if self._last_ai_bubble is None:
            self.add_ai_message(token)
            return
        self._last_ai_bubble.append_text(token)
        self._scroll_to_bottom()

    def show_typing(self) -> None:
        """Show and animate the typing indicator."""
        if not self._typing_visible:
            self._layout.addWidget(self._typing)
            self._typing.show()
            self._typing_visible = True
        self._typing.start()
        self._scroll_to_bottom()

    def hide_typing(self) -> None:
        """Remove the typing indicator from the layout."""
        if self._typing_visible:
            self._typing.stop()
            self._layout.removeWidget(self._typing)
            self._typing.hide()
            self._typing_visible = False

    def _scroll_to_bottom(self) -> None:
        """Schedule a scroll-to-bottom after layout settles."""
        QTimer.singleShot(0, self._do_scroll)

    def _do_scroll(self) -> None:
        """Execute the scroll."""
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
