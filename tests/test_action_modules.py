"""Tests for the action modules in src/actions/."""
from unittest.mock import patch

from src.actions import apps, errors, files, notes, search


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------

def _touch(path, text="x"):
    path.write_text(text, encoding="utf-8")
    return path


def test_organize_dry_run_moves_nothing(tmp_path):
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "b.mp3")
    preview = files.organize_files(str(tmp_path), dry_run=True)
    assert preview.startswith(files.PLAN_PREFIX)
    assert "images/" in preview and "music/" in preview
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.jpg", "b.mp3"]


def test_organize_never_overwrites(tmp_path):
    (tmp_path / "documents").mkdir()
    _touch(tmp_path / "documents" / "report.pdf", "old")
    _touch(tmp_path / "report.pdf", "new")
    files.organize_files(str(tmp_path), dry_run=False)
    assert (tmp_path / "documents" / "report.pdf").read_text() == "old"
    assert (tmp_path / "documents" / "report (1).pdf").read_text() == "new"


def test_organize_skips_hidden_partial_and_dirs(tmp_path):
    _touch(tmp_path / ".hidden.txt")
    _touch(tmp_path / "movie.mkv.part")
    _touch(tmp_path / "setup.crdownload")
    (tmp_path / "folder").mkdir()
    _touch(tmp_path / "notes.txt")
    files.organize_files(str(tmp_path), dry_run=False)
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [".hidden.txt", "documents", "folder", "movie.mkv.part", "setup.crdownload"]


def test_organize_unknown_extension_goes_to_other(tmp_path):
    _touch(tmp_path / "thing.xyz")
    files.organize_files(str(tmp_path), dry_run=False)
    assert (tmp_path / "other" / "thing.xyz").exists()


def test_organize_bad_path(tmp_path):
    assert "not a directory" in files.organize_files(str(tmp_path / "nope"))


def test_organize_empty_dir(tmp_path):
    assert "No files" in files.organize_files(str(tmp_path))


# ---------------------------------------------------------------------------
# apps
# ---------------------------------------------------------------------------

def test_valid_names():
    assert apps.is_valid_name("vlc")
    assert apps.is_valid_name("g++")
    assert apps.is_valid_name("python3.12-venv")
    assert not apps.is_valid_name("-y")
    assert not apps.is_valid_name("vlc; rm -rf ~")
    assert not apps.is_valid_name("")


def test_install_dry_run_shows_command():
    with patch.object(apps, "_build_install_cmd", return_value=["pkcon", "install", "-y", "vlc"]):
        msg = apps.install_app("vlc", dry_run=True)
    assert msg == "Would run: `pkcon install -y vlc`"


def test_install_without_backend():
    with patch.object(apps, "_build_install_cmd", return_value=None):
        assert "PackageKit" in apps.install_app("vlc", dry_run=True)


def test_open_app_resolves_alias():
    def which(name):
        return f"/usr/bin/{name}" if name == "konsole" else None

    with patch.object(apps.shutil, "which", side_effect=which), \
         patch.object(apps.subprocess, "Popen") as popen:
        msg = apps.open_app("Terminal")
    assert msg == "Launching konsole…"
    assert popen.call_args.args[0] == ["/usr/bin/konsole"]


def test_open_app_not_found():
    with patch.object(apps.shutil, "which", return_value=None), \
         patch.object(apps.subprocess, "Popen") as popen:
        msg = apps.open_app("nonexistent-app")
    assert "Could not find" in msg
    popen.assert_not_called()


def test_open_app_rejects_unsafe_names():
    with patch.object(apps.subprocess, "Popen") as popen:
        apps.open_app("../../bin/sh")
    popen.assert_not_called()


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

def test_missing_python_module():
    result = errors.explain_error("ModuleNotFoundError: No module named 'requests.adapters'")
    assert "requests" in result["explanation"]
    assert result["suggested_fix"] == "python3 -m pip install requests"


def test_command_not_found_names_the_command():
    result = errors.explain_error("bash: htop: command not found")
    assert "'htop'" in result["explanation"]


def test_apt_lock():
    result = errors.explain_error("E: Could not get lock /var/lib/dpkg/lock-frontend")
    assert "package manager" in result["explanation"]


def test_unknown_error_is_echoed():
    result = errors.explain_error("weird thing happened")
    assert "weird thing happened" in result["explanation"]
    assert result["suggested_fix"] is None


def test_empty_error():
    assert "Paste" in errors.explain_error("   ")["explanation"]


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------

def test_save_and_list_notes(isolated_notes_dir):
    msg = notes.save_note("buy milk", title="Shopping list!")
    assert str(isolated_notes_dir) in msg
    saved = notes.list_notes()
    assert len(saved) == 1
    assert saved[0].name.endswith("_Shopping_list.md")


def test_same_second_notes_do_not_collide():
    with patch.object(notes, "_filename", return_value="2026-01-01_120000"):
        notes.save_note("one")
        notes.save_note("two")
    contents = sorted(p.read_text(encoding="utf-8").strip() for p in notes.list_notes())
    assert contents == ["one", "two"]


def test_empty_note_rejected():
    assert notes.save_note("  ") == "Cannot save an empty note."
    assert notes.list_notes() == []


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def test_search_opens_browser():
    with patch.object(search.webbrowser, "open") as open_:
        msg = search.google_search("linux tips & tricks")
    open_.assert_called_once_with("https://www.google.com/search?q=linux+tips+%26+tricks")
    assert "linux tips & tricks" in msg


def test_empty_search():
    with patch.object(search.webbrowser, "open") as open_:
        assert "What should I search" in search.google_search(" ")
    open_.assert_not_called()
