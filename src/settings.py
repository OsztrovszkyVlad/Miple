"""Persistent user settings (a small JSON file in the OS config folder).

Locations:
    Linux   $XDG_CONFIG_HOME/miple/settings.json  (default ~/.config/miple)
    Windows %APPDATA%\\Miple\\settings.json
    macOS   ~/Library/Application Support/Miple/settings.json
Override with ``MIPLE_CONFIG_DIR``.
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def config_dir() -> Path:
    """Folder holding Miple's settings."""
    custom = os.environ.get("MIPLE_CONFIG_DIR")
    if custom:
        return Path(custom).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Miple"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Miple"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "miple"


def settings_path() -> Path:
    """The settings file."""
    return config_dir() / "settings.json"


def load() -> dict[str, Any]:
    """Return saved settings ({} if none or unreadable)."""
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable settings file %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def get(key: str, default: Any = None) -> Any:
    """Read one setting."""
    return load().get(key, default)


def update(**values: Any) -> None:
    """Merge *values* into the settings file (written atomically)."""
    data = load()
    data.update(values)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
