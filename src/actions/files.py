"""File organiser — scans a folder and sorts files into typed subfolders."""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

PLAN_PREFIX = "Here's what I'll do in"
"""Every successful dry-run preview starts with this string."""

_FILE_TYPES: dict[str, list[str]] = {
    "documents": [
        "pdf", "doc", "docx", "txt", "md", "odt", "ods", "odp", "rtf",
        "xls", "xlsx", "csv", "ppt", "pptx", "epub",
    ],
    "images": ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "heic", "tiff"],
    "music": ["mp3", "wav", "flac", "ogg", "m4a", "opus", "aac"],
    "video": ["mp4", "mkv", "avi", "mov", "wmv", "webm"],
    "archives": ["zip", "tar", "gz", "tgz", "bz2", "xz", "rar", "7z"],
    "code": [
        "py", "js", "ts", "html", "css", "json", "yaml", "yml", "toml",
        "sh", "cpp", "c", "h", "rs", "go", "java",
    ],
    "installers": ["deb", "rpm", "appimage", "flatpakref", "iso"],
}

# Files that are still being written by a browser or downloader — never move.
_PARTIAL_SUFFIXES = {"part", "crdownload", "download", "tmp", "partial"}

# Reverse map: extension → category
_EXT_MAP: dict[str, str] = {
    ext: cat for cat, exts in _FILE_TYPES.items() for ext in exts
}


def organize_files(path: str, dry_run: bool = True) -> str:
    """Scan *path* and sort files into category subfolders.

    Args:
        path: Target directory path (~ is expanded).
        dry_run: If True, return a preview plan without moving anything.
                 If False, execute the moves.

    Returns:
        Human-readable summary string.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        return f"'{path}' is not a directory or doesn't exist."

    plan: dict[str, list[Path]] = {}
    for f in sorted(resolved.iterdir()):
        if not _should_move(f):
            continue
        category = _EXT_MAP.get(f.suffix.lstrip(".").lower(), "other")
        plan.setdefault(category, []).append(f)

    if not any(plan.values()):
        return f"No files found in {resolved}."

    if dry_run:
        return _format_plan(plan, resolved)
    return _execute_plan(plan, resolved)


def _format_plan(plan: dict[str, list[Path]], base: Path) -> str:
    """Build a human-readable dry-run preview string."""
    lines = [f"{PLAN_PREFIX} {base}:\n"]
    total = 0
    for category, files in sorted(plan.items()):
        lines.append(f"  {category}/  ({len(files)} files)")
        for f in files[:5]:
            lines.append(f"    {f.name}")
        if len(files) > 5:
            lines.append(f"    … and {len(files) - 5} more")
        total += len(files)
    lines.append(f"\nTotal: {total} files across {len(plan)} folders.")
    return "\n".join(lines)


def _execute_plan(plan: dict[str, list[Path]], base: Path) -> str:
    """Move files according to plan. Returns a result summary."""
    moved = 0
    errors = 0
    for category, files in plan.items():
        dest_dir = base / category
        dest_dir.mkdir(exist_ok=True)
        for f in files:
            try:
                shutil.move(str(f), str(_unique_destination(dest_dir, f.name)))
                moved += 1
            except OSError as exc:
                logger.error("Failed to move %s: %s", f, exc)
                errors += 1
    msg = f"Done! Moved {moved} files into {len(plan)} folders in {base}."
    if errors:
        msg += f" ({errors} errors — check logs for details.)"
    return msg


def _should_move(f: Path) -> bool:
    """Return True for regular, visible, fully-downloaded files."""
    if not f.is_file() or f.is_symlink() or f.name.startswith("."):
        return False
    return f.suffix.lstrip(".").lower() not in _PARTIAL_SUFFIXES


def _unique_destination(dest_dir: Path, name: str) -> Path:
    """Return a path in *dest_dir* for *name* that won't overwrite anything.

    ``report.pdf`` becomes ``report (1).pdf``, ``report (2).pdf`` … on clashes.
    """
    target = dest_dir / name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while target.exists():
        target = dest_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    return target
