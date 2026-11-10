"""Find, start and install the Ollama runtime.

All subprocess work for Ollama lives here (project rule: subprocess calls only
in ``src/actions``). Installing is a system change, so :func:`install_ollama`
has a ``dry_run`` mode and is only run after the user clicks *Install*.
"""
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_INSTALL_TIMEOUT_S = 1800
_LINUX_INSTALL = "curl -fsSL https://ollama.com/install.sh | sh"


def find_ollama() -> str | None:
    """Return the path of the ``ollama`` executable, or None if not installed."""
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in _known_locations():
        if candidate.is_file():
            return str(candidate)
    return None


def _known_locations() -> list[Path]:
    """Install locations that may not be on PATH yet (e.g. right after install)."""
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return [local / "Programs" / "Ollama" / "ollama.exe"]
    if sys.platform == "darwin":
        return [Path("/usr/local/bin/ollama"), Path("/Applications/Ollama.app/Contents/Resources/ollama")]
    return [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"), Path.home() / ".local/bin/ollama"]


def start_server() -> bool:
    """Start ``ollama serve`` in the background. Returns False if not installed."""
    binary = find_ollama()
    if binary is None:
        return False
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    try:
        subprocess.Popen(
            [binary, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
            creationflags=flags,
            # Don't let the long-lived server inherit (and lock) Miple's app folder.
            cwd=str(Path.home()),
        )
    except OSError as exc:
        logger.warning("Could not start Ollama: %s", exc)
        return False
    logger.info("Started Ollama server: %s serve", binary)
    return True


def install_command() -> list[str] | None:
    """The command that installs Ollama on this OS, or None if unsupported."""
    if sys.platform == "win32" and shutil.which("winget"):
        return [
            "winget", "install", "-e", "--id", "Ollama.Ollama",
            "--accept-package-agreements", "--accept-source-agreements", "--silent",
        ]
    if sys.platform.startswith("linux") and shutil.which("pkexec") and shutil.which("curl"):
        # pkexec shows the desktop's password dialog; the official script then
        # installs the binary and a systemd service that starts Ollama.
        return ["pkexec", "sh", "-c", _LINUX_INSTALL]
    if sys.platform == "darwin" and shutil.which("brew"):
        return ["brew", "install", "ollama"]
    return None


def install_progress_text() -> str:
    """What to show while the install runs."""
    if sys.platform.startswith("linux"):
        return (
            "Installing Ollama… enter your password in the dialog that appears. "
            "This takes a few minutes."
        )
    return "Installing Ollama… this takes a few minutes (about 1 GB to download)."


def manual_install_hint() -> str:
    """What to tell the user when automatic install isn't possible."""
    if sys.platform.startswith("linux"):
        return f"Open a terminal and run:\n```\n{_LINUX_INSTALL}\n```"
    return "Download it from https://ollama.com/download, install it, then click Retry."


def install_ollama(
    dry_run: bool = True,
    on_complete: Callable[[bool, str], None] | None = None,
) -> str:
    """Install Ollama.

    Args:
        dry_run: If True, only describe what would run.
        on_complete: Called from a worker thread with (success, message)
            when the install finishes (not called on dry_run).

    Returns:
        A preview (dry_run) or a "started" message.
    """
    cmd = install_command()
    if cmd is None:
        return "I can't install Ollama automatically here. " + manual_install_hint()
    if dry_run:
        return "Would run: `" + " ".join(cmd) + "`"
    threading.Thread(target=_run_install, args=(cmd, on_complete), daemon=True).start()
    return "Installing Ollama… this can take a few minutes."


def no_window_flags() -> int:
    """Windows: run console tools without popping up a console window.

    Miple is started without a console (pythonw), so Windows would otherwise
    open an empty one for winget — and closing it kills the install.
    """
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _run_install(cmd: list[str], on_complete: Callable[[bool, str], None] | None) -> None:
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_INSTALL_TIMEOUT_S,
            creationflags=no_window_flags(),
        )
        ok = result.returncode == 0 or find_ollama() is not None
        if ok:
            msg = "Ollama installed."
        else:
            logger.warning(
                "Ollama install exited with %s:\n%s\n%s",
                result.returncode, result.stdout, result.stderr,
            )
            msg = f"Ollama install failed ({describe_failure(result)})."
    except subprocess.TimeoutExpired:
        ok, msg = False, "Ollama install timed out."
    except OSError as exc:
        ok, msg = False, f"Ollama install failed: {exc}"
    logger.info("Ollama install result: %s", msg)
    if on_complete:
        on_complete(ok, msg)


# Progress lines and banners that say nothing about why an install failed.
_NOISE = ("Downloading ", "Found ", "This application is licensed", "Microsoft is not responsible",
          "Successfully verified", "Starting package install")


def describe_failure(result: subprocess.CompletedProcess) -> str:
    """Short reason for a failed install: the last meaningful output line + exit code."""
    lines = [
        line.strip()
        for line in f"{result.stdout or ''}\n{result.stderr or ''}".splitlines()
        if line.strip()
        and any(ch.isalnum() for ch in line)
        and not line.strip().startswith(_NOISE)
        and "█" not in line and "▒" not in line
    ]
    code = result.returncode
    code_text = f"exit code {code}" + (f" / 0x{code & 0xFFFFFFFF:08X}" if code < 0 or code > 255 else "")
    return f"{lines[-1]}; {code_text}" if lines else code_text
