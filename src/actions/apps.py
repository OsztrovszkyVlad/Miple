"""App launcher and installer."""
import logging
import re
import shutil
import subprocess
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

_INSTALL_TIMEOUT_S = 600  # big packages + time to answer the polkit prompt

INSTALL_PREVIEW_PREFIX = "Would run:"
"""Every successful install dry-run preview starts with this string."""

# Package / executable names: letters, digits and . + _ - ; must not start
# with '-' so a name can never be interpreted as a command-line option.
_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,99}$")

_FILE_MANAGERS = ["nautilus", "nemo", "thunar", "dolphin", "caja", "pcmanfm"]

_COMMON_APPS: dict[str, list[str]] = {
    "files": _FILE_MANAGERS,
    "file": _FILE_MANAGERS,
    "file_browser": _FILE_MANAGERS,
    "file_manager": _FILE_MANAGERS,
    "file manager": _FILE_MANAGERS,
    "terminal": [
        "gnome-terminal", "kgx", "ptyxis", "konsole", "xfce4-terminal",
        "alacritty", "kitty", "xterm",
    ],
    "browser": ["firefox", "chromium", "chromium-browser", "google-chrome", "brave-browser"],
    "web browser": ["firefox", "chromium", "chromium-browser", "google-chrome", "brave-browser"],
    "editor": ["gnome-text-editor", "gedit", "kate", "mousepad", "xed", "pluma"],
    "text editor": ["gnome-text-editor", "gedit", "kate", "mousepad", "xed", "pluma"],
    "calculator": ["gnome-calculator", "kcalc", "galculator", "qalculate-gtk"],
    "settings": ["gnome-control-center", "systemsettings", "xfce4-settings-manager"],
    "code": ["code", "codium"],
    "vscode": ["code", "codium"],
}


def is_valid_name(name: str) -> bool:
    """Return True if *name* is a safe package / executable name."""
    return bool(_VALID_NAME_RE.match(name))


def open_app(name: str) -> str:
    """Launch *name* as a detached subprocess.

    Generic names like 'files' or 'terminal' are resolved to the first
    installed candidate from *_COMMON_APPS* before launching. Only
    executables found on PATH are launched.

    Args:
        name: Executable name or a common alias ('files', 'terminal', …).

    Returns:
        Human-readable status string.
    """
    key = name.lower().strip()
    if not key:
        return "Which app should I open?"
    candidates = _COMMON_APPS.get(key, [key.replace(" ", "-")])
    for candidate in candidates:
        if not is_valid_name(candidate):
            continue
        executable = shutil.which(candidate)
        if executable is None:
            continue
        try:
            subprocess.Popen(
                [executable],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.warning("Failed to launch %s: %s", executable, exc)
            continue
        logger.debug("Launched: %s", executable)
        return f"Launching {candidate}…"
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
    name = name.strip()
    if not is_valid_name(name):
        return f"'{name}' doesn't look like a valid package name."
    cmd = _build_install_cmd(name)
    if cmd is None:
        return (
            "No install method available. "
            "Install PackageKit (`dnf install PackageKit` or `apt install packagekit`) and try again."
        )
    if dry_run:
        return f"{INSTALL_PREVIEW_PREFIX} `{' '.join(cmd)}`"
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
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_INSTALL_TIMEOUT_S
        )
        if result.returncode == 0:
            msg = f"✓ {name} installed successfully."
        else:
            logger.warning("Install of %s failed: %s", name, result.stderr.strip())
            detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
            msg = f"✗ Failed to install {name}."
            if detail:
                msg += f" {detail[0]}"
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
