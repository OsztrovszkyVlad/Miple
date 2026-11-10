# Miple

**A local-first AI sidebar for the Linux desktop.**

Miple lives as a slim pull tab on the right edge of your screen. Click it and a
chat drawer slides out, backed by a language model running **entirely on your
machine** through [Ollama](https://ollama.com). Ask it to tidy your Downloads
folder, install or open an app, search the web, explain an error, or jot down a
note. Nothing you type leaves your computer.

```
                                   ┌──────────────────────────────┐
                                ┌──┤  (M) Miple                    │
                                │› │      your AI, locally         │
                                │  ├──────────────────────────────┤
                                │  │ [organize files] [install app]│
                                │  │ [open app] [google search] …  │
                                │  │                               │
                                │  │        tidy my downloads  ▐█▌ │
                                │  │ ▐ Here's what I'll do in …    │
                                │  │                               │
                                │  │ [ Ask Miple anything…  ][Send]│
                                └──┴──────────────────────────────┘
                                 tab           drawer (430 px)
```

---

## Features

| Ask for… | What Miple does | Needs confirmation? |
|---|---|---|
| *"My downloads folder is a mess, fix it"* | Sorts files into `documents/`, `images/`, `music/`, `video/`, `archives/`, `code/`, `installers/`, `other/` | **Yes**: shows the full plan first |
| *"Install vlc"* | Installs through PackageKit (`pkcon`) or `pkexec <apt\|dnf\|pacman>`, never plain `sudo` | **Yes**: shows the exact command first |
| *"Open the terminal"* | Launches the app; understands generic names like *terminal*, *files*, *browser*, *editor* | No |
| *"Search for rust tutorials"* | Opens a Google search in your default browser | No |
| *"Fix this error: …"* | Explains common Linux/Python errors and *shows* a suggested fix (never runs it) | n/a |
| *"Remind me to buy milk"* | Saves a Markdown note to `~/Documents/miple-notes/`, browsable in the **Notes** tab | No |

### Safety model

- **Destructive actions are always previewed.** Organizing files and installing
  packages run as a dry run first; nothing happens until you click **Yes, do it**.
- **Nothing is overwritten.** If `documents/report.pdf` already exists, the
  incoming file becomes `report (1).pdf`. Hidden files, folders, symlinks and
  in-progress downloads (`.part`, `.crdownload`, …) are never moved.
- **Commands from the model are never executed.** Shell commands and error fixes
  are shown as copyable text only. Package and app names are validated, so they
  can't be smuggled in as command-line flags.
- **Fully local.** The only network traffic is to your Ollama server
  (`localhost` by default), plus your browser when you ask for a web search.

---

## Requirements

- Linux desktop (developed on Fedora; targets Ubuntu 24.04+ and other Debian/Ubuntu derivatives)
- Python **3.11+**
- [Ollama](https://ollama.com/download) running locally
- Recommended model: **Gemma 4 E4B** (`gemma4:e4b`). Any installed model works as a fallback.
- Roughly 4 GB VRAM / 16 GB RAM for the default model
- For app installs: **PackageKit** (`pkcon`) or **polkit** (`pkexec`). Both are present on most desktops.

## Quick start

```bash
# 1. Get a model
ollama pull gemma4:e4b

# 2. Get Miple
git clone https://github.com/OsztrovszkyVlad/Miple.git
cd Miple
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Run it
python main.py
```

Click the **‹** tab on the right edge of the screen to open the drawer, and
press **Esc** (or click **›**) to close it.

### Command-line options

```
python main.py [--open] [--debug]

  --open    start with the drawer already open
  --debug   verbose logging to stderr (same as MIPLE_DEBUG=1)
```

### Configuration

Everything is configured through environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MIPLE_OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `MIPLE_MODEL` | `gemma4:e4b` | Preferred model; falls back to the first installed one |
| `MIPLE_NOTES_DIR` | `~/Documents/miple-notes` | Where notes are saved |
| `MIPLE_TIMEOUT` | `120` | Seconds to wait for a reply (the first load of a model is slow) |
| `MIPLE_DEBUG` | unset | `1` turns on debug logging |

Example: `MIPLE_MODEL=llama3.2:3b python main.py`

### Wayland

Wayland doesn't let applications place their own windows, so on a Wayland
session Miple runs through **XWayland** (`QT_QPA_PLATFORM=xcb`) to stay
anchored to the screen edge. To force native Wayland anyway, set
`QT_QPA_PLATFORM=wayland`; the drawer will then appear wherever your compositor
puts it.

---

## How it works

```
 ┌─────────── GUI thread (PyQt6) ───────────┐        ┌──── background ────┐
 │ DrawerWindow ─ ChatView / NotesView      │ submit │ AssistantSession   │
 │      ▲            QuickActionBar         ├───────►│  asyncio loop      │
 │      │ Qt signals                        │        │   └ OllamaClient ──┼──► Ollama /api/chat
 │      └───────────────────────────────────┤◄───────┤  parser.split_action
 └──────────────────────────────────────────┘ Reply  │  actions.dispatch ─┼──► src/actions/*
                                                     └────────────────────┘
```

1. You type a message. `AssistantSession` sends it, along with the recent
   history, to Ollama on a single long-lived asyncio loop.
2. The model is prompted to end each reply with an action block such as
   `{action: 'open_app', params: {name: 'vlc'}}`. `parser.split_action` pulls it
   out, accepting both strict JSON and the looser JS-style form small models
   tend to produce, and returns the remaining prose for display.
3. `actions.dispatch` maps aliases (`install` → `install_app`, `remind_me` →
   `save_note`, …) onto canonical actions. Safe actions run straight away;
   destructive ones return a dry-run preview plus a pending action.
4. If you confirm, `actions.confirm` runs the pending action on a worker
   thread, and installs report back when they finish.

### Project layout

```
main.py                  entry point (CLI flags, logging, Qt platform)
src/config.py            environment-driven settings
src/agent/
  ollama.py              async Ollama client: streaming, model detection, friendly errors
  parser.py              find and strip the action block in a reply
  actions.py             normalise and dispatch actions; preview vs. confirm
  session.py             conversation state + background event loop
src/actions/             everything that touches the system lives here
  files.py               organise a folder by file type (dry run, no overwrites)
  apps.py                open apps, install packages via PackageKit / pkexec
  search.py              web search in the default browser
  notes.py               save and list Markdown notes
  errors.py              heuristic error explanations
src/ui/                  PyQt6 widgets only, no business logic
  drawer.py              the sliding window, input row, confirm flow
  chat.py                message bubbles, typing indicator
  notes.py               notes browser / reader
  quickactions.py        quick-action pill buttons
tests/                   pytest suite (UI tests run headless)
```

---

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

The UI tests use Qt's `offscreen` platform (set automatically in
`tests/conftest.py`), so the whole suite runs without a display, including
over SSH and in CI. None of the tests need Ollama or touch your real files:
the notes directory is redirected to a temp folder, and the client is faked.

Adding a new action:

1. Implement it in `src/actions/<name>.py`. If it changes anything, give it a `dry_run` mode.
2. Register it in `src/agent/actions.py`, in `_IMMEDIATE_HANDLERS` (safe) or
   `_PREVIEW_HANDLERS` plus `confirm()` (destructive), and add any aliases.
3. Teach the model about it with an example line in `SYSTEM_PROMPT` (`src/agent/ollama.py`).
4. Add tests.

## Troubleshooting

| Symptom | Fix |
|---|---|
| *"I couldn't connect to Ollama"* | Start it with `ollama serve` (or `systemctl start ollama`), and check `MIPLE_OLLAMA_URL`. |
| *"Ollama doesn't have the model …"* | `ollama pull gemma4:e4b`, or set `MIPLE_MODEL` to a model you have (`ollama list`). |
| The first reply is very slow | The model is loading into memory; later replies are much faster. Raise `MIPLE_TIMEOUT` if it times out. |
| The drawer isn't on the screen edge | You're on native Wayland. Unset `QT_QPA_PLATFORM` so Miple can use XWayland. |
| *"No install method available"* | Install PackageKit: `sudo apt install packagekit` or `sudo dnf install PackageKit`. |
| `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` | `sudo apt install libxcb-cursor0` (Ubuntu/Debian). |

## Roadmap

- System info action (distro, disk, memory) via a `system.py` module
- Undo for file organization
- Streaming replies token by token
- `.deb` / Flatpak packaging and autostart entry
