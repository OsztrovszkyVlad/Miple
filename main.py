#!/usr/bin/env python3
"""Miple — local AI desktop assistant. Entry point."""
import argparse
import getpass
import logging
import logging.handlers
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


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
    parser.add_argument(
        "--reset-model",
        action="store_true",
        help="forget the chosen model and pick one for this computer again",
    )
    return parser.parse_args()


def _configure_logging(debug: bool) -> None:
    """Log to stderr and to a rotating file next to the settings."""
    from src import settings

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir = settings.config_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_dir / "miple.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
            )
        )
    except OSError:
        pass  # logging to a file is a nicety, never a reason to fail
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
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


def _instance_name() -> str:
    """Per-user name for the single-instance channel."""
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"miple-{user}"


def _hand_off_to_running_instance(open_drawer: bool) -> bool:
    """If Miple already runs, ask it to open its drawer and return True."""
    from PyQt6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(_instance_name())
    if not socket.waitForConnected(300):
        return False
    socket.write(b"open\n" if open_drawer else b"ping\n")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def _listen_for_other_instances(win) -> object:
    """Open the drawer whenever Miple is launched again."""
    from PyQt6.QtNetwork import QLocalServer

    name = _instance_name()
    server = QLocalServer()
    if not server.listen(name):
        QLocalServer.removeServer(name)  # stale socket left by a crash
        server.listen(name)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def on_ready() -> None:
            if bytes(conn.readAll()).startswith(b"open"):
                win.open_drawer()

        conn.readyRead.connect(on_ready)

    server.newConnection.connect(on_connection)
    return server


def main() -> None:
    """Run Miple."""
    os.chdir(APP_DIR)  # so `src` imports work from shortcuts and autostart
    sys.path.insert(0, str(APP_DIR))
    args = _parse_args()
    _configure_logging(args.debug or os.environ.get("MIPLE_DEBUG") == "1")
    _prefer_xwayland()

    # Imported after the platform is chosen.
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from src import settings
    from src.ui.drawer import DrawerWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Miple")
    app.setDesktopFileName("miple")
    app.setWindowIcon(QIcon(str(APP_DIR / "assets" / "miple.svg")))
    app.setQuitOnLastWindowClosed(True)

    if _hand_off_to_running_instance(args.open):
        logging.getLogger(__name__).info("Miple is already running; opened its drawer.")
        return
    if args.reset_model:
        settings.update(model=None)

    win = DrawerWindow()
    server = _listen_for_other_instances(win)  # noqa: F841 — keep a reference
    win.show()
    if args.open:
        win.open_drawer()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
