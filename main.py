#!/usr/bin/env python3
"""Miple — local AI desktop assistant. Entry point."""
import logging
import sys

from PyQt6.QtWidgets import QApplication

from src.ui.drawer import DrawerWindow

logging.basicConfig(
    level=logging.DEBUG,
    format="%(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run Miple."""
    app = QApplication(sys.argv)
    app.setApplicationName("Miple")
    app.setQuitOnLastWindowClosed(True)

    win = DrawerWindow()
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
