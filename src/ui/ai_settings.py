"""AI tab — Ollama connection status, model choice and model download."""
import logging
from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.agent.ai_manager import AIStatus

logger = logging.getLogger(__name__)

_BUTTON = """
    QPushButton { background-color: #45475a; color: #cdd6f4; border: none;
                  border-radius: 6px; padding: 6px 12px; font-size: 12px; }
    QPushButton:hover { background-color: #585b70; }
    QPushButton:disabled { color: #6c7086; }
"""
_PRIMARY = """
    QPushButton { background-color: #7c3aed; color: white; border: none;
                  border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: bold; }
    QPushButton:hover { background-color: #6d28d9; }
    QPushButton:disabled { background-color: #45475a; color: #6c7086; }
"""
_CARD = "QFrame#aiCard { background-color: #181825; border-radius: 8px; }"
_GREEN, _RED, _AMBER = "#a6e3a1", "#f38ba8", "#f9e2af"


@dataclass(frozen=True)
class AICallbacks:
    """What the tab's buttons do."""

    refresh: Callable[[], None]
    start: Callable[[], None]
    install: Callable[[], None]
    load: Callable[[], None]
    use: Callable[[str], None]
    download: Callable[[str], None]


def _label(text: str = "", style: str = "color: #cdd6f4; font-size: 13px;") -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(style)
    return lbl


def _button(text: str, on_click: Callable[[], None], primary: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(_PRIMARY if primary else _BUTTON)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(on_click)
    return btn


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("aiCard")
    frame.setStyleSheet(_CARD)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(6)
    layout.addWidget(_label(title, "color: #6c7086; font-size: 11px; font-weight: bold;"))
    return frame, layout


class AISettingsView(QScrollArea):
    """Shows whether the AI is ready and lets the user fix it."""

    def __init__(self, callbacks: AICallbacks) -> None:
        """Build the tab; call :meth:`show_status` to fill it."""
        super().__init__()
        self._cb = callbacks
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea { background-color: #1e1e2e; border: none; }"
            "QScrollBar:vertical { background: #1e1e2e; width: 8px; margin: 0; }"
            "QScrollBar::handle:vertical { background: #45475a; border-radius: 4px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
        )
        body = QWidget()
        body.setObjectName("aiBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Scoped so the colour doesn't cascade onto the labels inside the cards.
        body.setStyleSheet("#aiBody { background-color: #1e1e2e; }")
        self.setWidget(body)
        col = QVBoxLayout(body)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(10)
        col.addWidget(self._build_ollama_card())
        col.addWidget(self._build_model_card())
        col.addWidget(self._build_models_card())
        col.addWidget(self._build_activity())
        col.addStretch()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_ollama_card(self) -> QFrame:
        frame, layout = _card("OLLAMA")
        self._ollama_state = _label()
        self._start_btn = _button("Start Ollama", self._cb.start, primary=True)
        self._install_btn = _button("Install Ollama", self._cb.install, primary=True)
        self._refresh_btn = _button("Check again", self._cb.refresh)
        row = QHBoxLayout()
        for btn in (self._start_btn, self._install_btn, self._refresh_btn):
            row.addWidget(btn)
        row.addStretch()
        layout.addWidget(self._ollama_state)
        layout.addLayout(row)
        return frame

    def _build_model_card(self) -> QFrame:
        frame, layout = _card("MODEL IN USE")
        self._model_state = _label()
        self._load_btn = _button("Load now", self._cb.load)
        self._hardware = _label(style="color: #6c7086; font-size: 11px;")
        self._recommendation = _label(style="color: #cdd6f4; font-size: 12px;")
        self._download_btn = _button("Download", self._on_download, primary=True)
        row = QHBoxLayout()
        row.addWidget(self._load_btn)
        row.addWidget(self._download_btn)
        row.addStretch()
        for widget in (self._model_state, self._hardware, self._recommendation):
            layout.addWidget(widget)
        layout.addLayout(row)
        return frame

    def _build_models_card(self) -> QFrame:
        frame, layout = _card("DOWNLOADED MODELS")
        self._models_box = QVBoxLayout()
        self._models_box.setSpacing(4)
        layout.addLayout(self._models_box)
        return frame

    def _build_activity(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(2, 0, 2, 0)
        self._busy = _label(style="color: #cdd6f4; font-size: 12px; font-style: italic;")
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet(
            "QProgressBar { background-color: #313244; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background-color: #7c3aed; border-radius: 3px; }"
        )
        self._error = _label(style=f"color: {_RED}; font-size: 12px;")
        for widget in (self._busy, self._progress, self._error):
            layout.addWidget(widget)
        return box

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def show_status(self, s: AIStatus) -> None:
        """Render *s*."""
        self._status = s
        idle = s.busy is None
        self._render_ollama(s, idle)
        self._render_model(s, idle)
        self._render_models(s, idle)
        self._busy.setText(s.busy or "")
        self._busy.setVisible(not idle)
        self._progress.setVisible(not idle)
        if s.progress is None:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, 1000)
            self._progress.setValue(int(s.progress * 1000))
        self._error.setText(s.error or "")
        self._error.setVisible(bool(s.error))

    def _render_ollama(self, s: AIStatus, idle: bool) -> None:
        if s.running:
            text, color = f"● Connected — Ollama {s.version}", _GREEN
        elif s.installed:
            text, color = "● Installed, but not running", _AMBER
        else:
            text, color = "● Not installed — Miple needs Ollama to run the AI", _RED
        self._ollama_state.setText(text)
        self._ollama_state.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
        self._start_btn.setVisible(s.installed and not s.running)
        self._install_btn.setVisible(not s.installed and s.can_install)
        for btn in (self._start_btn, self._install_btn, self._refresh_btn):
            btn.setEnabled(idle)

    def _render_model(self, s: AIStatus, idle: bool) -> None:
        loaded = s.current_loaded
        if not s.current_model:
            state = "No model chosen yet."
        elif loaded:
            state = f"{s.current_model} — loaded ({loaded.placement}), ready to answer"
        elif s.running:
            state = f"{s.current_model} — not loaded yet (the first reply will take longer)"
        else:
            state = f"{s.current_model}"
        self._model_state.setText(state)
        self._load_btn.setVisible(bool(s.running and s.current_model and not loaded))
        self._load_btn.setEnabled(idle)
        self._hardware.setText(f"Your computer: {s.hardware}" if s.hardware else "")
        rec = s.recommended
        if rec:
            self._recommendation.setText(
                f"Best fit for it: {rec.model.label} ({rec.model.tag}, {rec.model.download_gb:.1f} GB). "
                f"{rec.reason}"
            )
        show_download = bool(rec and s.running and not s.recommended_installed)
        self._download_btn.setVisible(show_download)
        if rec:
            self._download_btn.setText(f"Download {rec.model.label} ({rec.model.download_gb:.1f} GB)")
        self._download_btn.setEnabled(idle)

    def _render_models(self, s: AIStatus, idle: bool) -> None:
        while self._models_box.count():
            widget = self._models_box.takeAt(0).widget()
            if widget is not None:
                widget.hide()  # off screen now, not only once deleteLater runs
                widget.deleteLater()
        if not s.models:
            self._models_box.addWidget(_label(
                "None yet." if s.running else "Start Ollama to see your models.",
                "color: #6c7086; font-size: 12px;",
            ))
            return
        for m in s.models:
            self._models_box.addWidget(self._model_row(m.name, m.size_gb, m.name == s.current_model, idle))

    def _model_row(self, name: str, size_gb: float, in_use: bool, idle: bool) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_label(f"{name}  ·  {size_gb:.1f} GB", "color: #cdd6f4; font-size: 12px;"), 1)
        if in_use:
            layout.addWidget(_label("In use", f"color: {_GREEN}; font-size: 12px;"))
        else:
            btn = _button("Use", lambda: self._cb.use(name))
            btn.setEnabled(idle)
            layout.addWidget(btn)
        return row

    def _on_download(self) -> None:
        rec = self._status.recommended
        if rec:
            self._cb.download(rec.model.tag)
