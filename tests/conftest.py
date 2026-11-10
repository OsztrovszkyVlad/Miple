"""Shared pytest fixtures."""
import os

# Must be set before any Qt import so UI tests run headless (CI, SSH, etc.).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from src import config  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_notes_dir(tmp_path, monkeypatch):
    """Point the notes directory at a temp folder for every test."""
    notes = tmp_path / "notes"
    monkeypatch.setattr(config, "NOTES_DIR", notes)
    return notes


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep tests away from the real settings file and MIPLE_MODEL."""
    monkeypatch.setenv("MIPLE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(config, "MODEL_OVERRIDE", None)
    return tmp_path / "config"


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for all UI tests (skipped if PyQt6 is missing)."""
    widgets = pytest.importorskip("PyQt6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield app
