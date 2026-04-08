"""App launcher and installer."""
import logging
import shutil
import subprocess
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


_COMMON_APPS: dict[str, list[str]] = {
    "files":        ["nautilus", "thunar", "dolphin", "nemo"],
    "file":         ["nautilus", "thunar", "dolphin", "nemo"],
    "file_browser": ["nautilus", "thunar", "dolphin", "nemo"],
    "file_manager": ["nautilus", "thunar", "dolphin", "nemo"],
    "terminal":     ["gnome-terminal", "konsole", "xterm", "alacritty"],
    "browser":      ["firefox", "chromium", "google-chrome"],
    "editor":       ["gedit", "kate", "mousepad", "xed"],
    "calculator":   ["gnome-calculator", "kcalc", "galculator"],
}


def open_app(name: str) -> str:
    """Launch *name* as a detached subprocess.

    Generic names like 'files' or 'terminal' are resolved to the first
    installed candidate from *_COMMON_APPS* before launching.

    Args:
        name: Executable name, path, or a common alias ('files', 'terminal', …).

    Returns:
        Human-readable status string.
    """
    candidates = _COMMON_APPS.get(name.lower().strip(), [name])
    for candidate in candidates:
        if shutil.which(candidate) is None and candidate != name:
            continue
        try:
            subprocess.Popen([candidate], start_new_session=True)
            logger.debug("Launched: %s", candidate)
            return f"Launching {candidate}…"
        except FileNotFoundError:
            continue
    return f"Could not find '{name}'. Make sure it's installed and in your PATH."


def install_app(
    name: str,
    dry_run: bool = True,
    on_complete: Callable[[str], None] | None = None,
) -> str:
    """Install a package via PackageKit (pkcon) or pkexec — never sudo.

    Resolution order:
      1. pkcon install -y <name>          (PackageKit CLI, auth via GUI)
      2. pkexec <pm> install -y <name>    (polkit elevation, no terminal password)
      3. Error — ask user to install PackageKit

    When dry_run=False the install runs in a background thread; this function
    returns immediately with a "please wait" message. *on_complete* is called
    from that thread with the final success/failure string.

    Args:
        name: Package name to install.
        dry_run: If True, return the planned command without running it.
        on_complete: Optional callback invoked with the result message when
                     the background install finishes.

    Returns:
        Command preview (dry_run) or "please wait" status (not dry_run).
    """
    cmd = _build_install_cmd(name)
    if cmd is None:
        return (
            "No install method available. "
            "Install PackageKit (`dnf install PackageKit` or `apt install packagekit`) and try again."
        )
    if dry_run:
        return f"Would run: {' '.join(cmd)}"
    threading.Thread(
        target=_run_install, args=(cmd, name, on_complete), daemon=True
    ).start()
    return f"Installing {name}… please wait."


def _run_install(
    cmd: list[str],
    name: str,
    on_complete: Callable[[str], None] | None,
) -> None:
    """Run *cmd* synchronously and report the outcome via *on_complete*."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            msg = f"✓ {name} installed successfully."
        else:
            msg = f"✗ Failed to install {name}. Check your internet connection or try again."
    except subprocess.TimeoutExpired:
        msg = f"✗ Install timed out for {name}."
    except Exception as exc:
        logger.error("_run_install failed: %s", exc)
        msg = f"✗ Install failed: {exc}"
    logger.debug("Install result for %s: %s", name, msg)
    if on_complete:
        on_complete(msg)


def _build_install_cmd(name: str) -> list[str] | None:
    """Return the best available install command for *name*, or None."""
    if shutil.which("pkcon"):
        return ["pkcon", "install", "-y", name]
    pm = _detect_package_manager()
    if pm and shutil.which("pkexec"):
        return ["pkexec", pm, "install", "-y", name]
    return None


def _detect_package_manager() -> str | None:
    """Return the first available package manager name, or None."""
    for pm in ("dnf", "apt", "pacman"):
        if shutil.which(pm):
            return pm
    return None
