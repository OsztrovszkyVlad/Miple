"""Notes tab — browse and read notes saved by Miple."""
import logging
import re
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from src.actions.notes import list_notes

logger = logging.getLogger(__name__)


class NoteCard(QFrame):
    """Clickable card showing a note's title and first-line preview."""

    def __init__(self, path: Path, on_click: Callable[[Path], None]) -> None:
        """Create a card for the note at *path*."""
        super().__init__()
        self._path = path
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QFrame {
                background-color: #313244;
                border-radius: 8px;
            }
            QFrame:hover { background-color: #45475a; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        title_lbl = QLabel(_friendly_title(path))
        title_lbl.setStyleSheet(
            "color: #cdd6f4; font-weight: bold; font-size: 13px;"
        )

        preview_lbl = QLabel(_first_line(path))
        preview_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")

        layout.addWidget(title_lbl)
        layout.addWidget(preview_lbl)

    def mousePressEvent(self, _event) -> None:
        """Open this note when clicked."""
        self._on_click(self._path)


class NoteReader(QWidget):
    """Full-text view of a single note with a back button."""

    def __init__(self, on_back: Callable[[], None]) -> None:
        """Create a reader; *on_back* is called when the back button is clicked."""
        super().__init__()
        self.setStyleSheet("background-color: #1e1e2e;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet(
            "background-color: #181825; border-bottom: 1px solid #313244;"
        )
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 4, 8, 4)
        back_btn = QPushButton("← Back")
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #89b4fa;
                border: none;
                font-size: 13px;
            }
            QPushButton:hover { color: #cdd6f4; }
        """)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(on_back)
        tb.addWidget(back_btn)
        tb.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background-color: #1e1e2e; border: none;")

        self._text_lbl = QLabel()
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._text_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._text_lbl.setStyleSheet("""
            QLabel {
                color: #cdd6f4;
                font-size: 13px;
                padding: 12px;
                background-color: #1e1e2e;
            }
        """)
        scroll.setWidget(self._text_lbl)

        layout.addWidget(toolbar)
        layout.addWidget(scroll)

    def load(self, path: Path) -> None:
        """Load and display the note at *path*."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read note %s: %s", path, exc)
            text = f"Could not read note: {exc}"
        self._text_lbl.setText(text)


class NotesView(QWidget):
    """Notes browser: scrollable list view ↔ full-text reader view."""

    def __init__(self) -> None:
        """Create the notes browser (starts on the list page)."""
        super().__init__()
        self.setStyleSheet("background-color: #1e1e2e;")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._stack = QStackedWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

        # Page 0 — list
        list_page = QWidget()
        list_page.setStyleSheet("background-color: #1e1e2e;")
        list_outer = QVBoxLayout(list_page)
        list_outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet("background-color: #1e1e2e; border: none;")

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background-color: #1e1e2e;")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(8, 8, 8, 8)
        self._cards_layout.setSpacing(6)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._cards_container)
        list_outer.addWidget(self._scroll)

        # Page 1 — reader
        self._reader = NoteReader(on_back=self._show_list)

        self._stack.addWidget(list_page)
        self._stack.addWidget(self._reader)

        self.refresh()

    def refresh(self) -> None:
        """Reload the notes list from disk."""
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        notes = list_notes()

        if not notes:
            lbl = QLabel("No notes yet.\nAsk Miple to save a note!")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "color: #6c7086; font-size: 13px; padding: 20px;"
            )
            self._cards_layout.addWidget(lbl)
        else:
            for path in notes:
                self._cards_layout.addWidget(
                    NoteCard(path, on_click=self._open_note)
                )

        logger.debug("Notes refreshed: %d notes", len(notes))

    def _open_note(self, path: Path) -> None:
        """Switch to the reader page for *path*."""
        self._reader.load(path)
        self._stack.setCurrentIndex(1)

    def _show_list(self) -> None:
        """Switch back to the list page."""
        self._stack.setCurrentIndex(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _friendly_title(path: Path) -> str:
    """Convert a timestamped filename stem to a readable title."""
    name = re.sub(r"^\d{4}-\d{2}-\d{2}_\d{6}_?", "", path.stem)
    name = re.sub(r"-\d+$", "", name)  # collision suffix added by save_note
    return name.replace("_", " ").strip() or path.stem


def _first_line(path: Path) -> str:
    """Return the first non-empty line of a note, truncated to 80 chars."""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                return line[:80]
    except OSError:
        pass
    return "(empty)"
