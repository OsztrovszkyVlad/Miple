"""Quick action pill buttons shown at the top of the Miple drawer."""
import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton

logger = logging.getLogger(__name__)

_ACTIONS: list[tuple[str, str]] = [
    ("organize files",  "Organize my Downloads folder"),
    ("install app",     "Install app: "),
    ("open app",        "Open app: "),
    ("google search",   "Search Google for: "),
    ("fix error",       "Help me fix this error:\n"),
]

_PILL_STYLE = """
    QPushButton {
        background-color: #45475a;
        color: #cdd6f4;
        border: none;
        border-radius: 999px;
        padding: 4px 12px;
        font-size: 12px;
    }
    QPushButton:hover { background-color: #585b70; }
    QPushButton:pressed { background-color: #313244; }
"""


_CONFIRM_PILL_STYLE = """
    QPushButton {
        background-color: #40a02b;
        color: #ffffff;
        border: none;
        border-radius: 999px;
        padding: 4px 12px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover  { background-color: #37902a; }
    QPushButton:pressed { background-color: #2d7a22; }
"""


class QuickActionBar(QWidget):
    """Two-row grid of pill-shaped quick-action buttons."""

    def __init__(self, on_action: Callable[[str], None]) -> None:
        """Create the bar.

        Args:
            on_action: Callback invoked with the action template string.
        """
        super().__init__()
        self._on_action = on_action
        self.setStyleSheet("background-color: #181825;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # Split actions into two rows: first 3, then remaining 2
        row1_actions = _ACTIONS[:3]
        row2_actions = _ACTIONS[3:]

        self._row1 = QHBoxLayout()
        self._row1.setSpacing(6)
        self._row1.setAlignment(Qt.AlignmentFlag.AlignLeft)
        for label, action_text in row1_actions:
            self._row1.addWidget(self._make_pill(label, action_text))
        outer.addLayout(self._row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.setAlignment(Qt.AlignmentFlag.AlignLeft)
        for label, action_text in row2_actions:
            row2.addWidget(self._make_pill(label, action_text))
        outer.addLayout(row2)

    def _make_pill(self, label: str, action_text: str) -> QPushButton:
        """Create a single pill button."""
        btn = QPushButton(label)
        btn.setStyleSheet(_PILL_STYLE)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self._handle_click(action_text))
        return btn

    def _handle_click(self, action_text: str) -> None:
        """Forward action text to callback."""
        logger.debug("Quick action: %s", action_text)
        self._on_action(action_text)

    def add_confirm_button(self, btn: QPushButton) -> None:
        """Insert *btn* as the leftmost item in the first action row."""
        btn.setStyleSheet(_CONFIRM_PILL_STYLE)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._row1.insertWidget(0, btn)

    def remove_confirm_button(self, btn: QPushButton) -> None:
        """Remove *btn* from the layout and schedule deletion."""
        self._row1.removeWidget(btn)
        btn.deleteLater()
