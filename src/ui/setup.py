"""SetupPanel — shown in the drawer until Ollama and a model are ready."""
import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from src.agent.setup import SetupState, Stage

logger = logging.getLogger(__name__)

_TITLES = {
    Stage.CHECKING: "Getting ready",
    Stage.STARTING_OLLAMA: "Getting ready",
    Stage.NEED_OLLAMA: "One-time setup",
    Stage.INSTALLING_OLLAMA: "Installing Ollama",
    Stage.NEED_MODEL: "Your AI model",
    Stage.DOWNLOADING: "Downloading your AI model",
    Stage.READY: "All set",
    Stage.ERROR: "Something went wrong",
}

_PRIMARY_STYLE = """
    QPushButton { background-color: #7c3aed; color: white; border: none;
                  border-radius: 6px; padding: 8px 16px; font-weight: bold; font-size: 13px; }
    QPushButton:hover { background-color: #6d28d9; }
    QPushButton:pressed { background-color: #5b21b6; }
"""
_SECONDARY_STYLE = """
    QPushButton { background-color: #45475a; color: #cdd6f4; border: none;
                  border-radius: 6px; padding: 8px 16px; font-size: 13px; }
    QPushButton:hover { background-color: #585b70; }
"""
_PROGRESS_STYLE = """
    QProgressBar { background-color: #313244; border: none; border-radius: 4px;
                   height: 8px; color: transparent; }
    QProgressBar::chunk { background-color: #7c3aed; border-radius: 4px; }
"""


class SetupPanel(QWidget):
    """Explains what setup is doing and offers at most two buttons."""

    def __init__(
        self, on_primary: Callable[[], None], on_secondary: Callable[[], None]
    ) -> None:
        """Create the panel; the callbacks fire when the buttons are clicked."""
        super().__init__()
        self.setStyleSheet("background-color: #1e1e2e;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 28, 20, 20)
        layout.setSpacing(12)

        self._title = QLabel()
        self._title.setStyleSheet("color: #cdd6f4; font-size: 17px; font-weight: bold;")
        self._hardware = QLabel()
        self._hardware.setStyleSheet("color: #6c7086; font-size: 11px;")
        self._hardware.setWordWrap(True)
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setTextFormat(Qt.TextFormat.MarkdownText)
        self._message.setOpenExternalLinks(True)
        self._message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._message.setStyleSheet("color: #cdd6f4; font-size: 13px;")
        self._progress = QProgressBar()
        self._progress.setStyleSheet(_PROGRESS_STYLE)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)

        self._primary = QPushButton()
        self._primary.setStyleSheet(_PRIMARY_STYLE)
        self._primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary.clicked.connect(on_primary)
        self._secondary = QPushButton()
        self._secondary.setStyleSheet(_SECONDARY_STYLE)
        self._secondary.setCursor(Qt.CursorShape.PointingHandCursor)
        self._secondary.clicked.connect(on_secondary)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self._primary)
        buttons.addWidget(self._secondary)
        buttons.addStretch()

        for widget in (self._title, self._hardware, self._message, self._progress):
            layout.addWidget(widget)
        layout.addLayout(buttons)
        layout.addStretch()

    def show_state(self, state: SetupState) -> None:
        """Render *state*."""
        self._title.setText(_TITLES.get(state.stage, "Setup"))
        self._hardware.setText(f"Your computer: {state.hardware}" if state.hardware else "")
        self._hardware.setVisible(bool(state.hardware))
        self._message.setText(state.message)
        self._progress.setVisible(state.busy)
        if state.progress is None:
            self._progress.setRange(0, 0)   # animated "busy" bar
        else:
            self._progress.setRange(0, 1000)
            self._progress.setValue(int(state.progress * 1000))
        for button, label in ((self._primary, state.primary), (self._secondary, state.secondary)):
            button.setVisible(bool(label))
            button.setText(label or "")
