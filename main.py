#!/usr/bin/env python3
"""Miple — local AI desktop assistant. Entry point."""
import argparse
import logging
import os
import sys


def _parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        prog="miple", description="Miple — a local AI sidebar assistant powered by Ollama."
    )
    parser.add_argument(
        "--debug", action="store_true", help="verbose logging (also: MIPLE_DEBUG=1)"
    )
    parser.add_argument(
        "--open", action="store_true", help="start with the drawer already open"
    )
    return parser.parse_args()


def _configure_logging(debug: bool) -> None:
    """Log to stderr; DEBUG level when requested."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _prefer_xwayland() -> None:
    """Use XWayland on Wayland sessions unless the user chose a platform.

    Wayland doesn't let clients position their own windows, so the drawer
    couldn't anchor itself to the screen edge under native Wayland.
    """
    if os.environ.get("WAYLAND_DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def main() -> None:
    """Run Miple."""
    args = _parse_args()
    _configure_logging(args.debug or os.environ.get("MIPLE_DEBUG") == "1")
    _prefer_xwayland()

    # Imported after the platform is chosen.
    from PyQt6.QtWidgets import QApplication

    from src.ui.drawer import DrawerWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Miple")
    app.setQuitOnLastWindowClosed(True)

    win = DrawerWindow()
    win.show()
    if args.open:
        win.open_drawer()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
