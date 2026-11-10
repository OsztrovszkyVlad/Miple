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
- **Fully local.** While you chat, the only network traffic is to your Ollama
  server (`localhost` by default), plus your browser when you ask for a web
  search. Setup downloads Ollama and the model only after you click the button.

---

## Install

Works on Linux desktops (the main target: Ubuntu 24.04+, Fedora, Debian
derivatives, Arch) and Windows 10/11; macOS runs from a checkout. Any machine
with 8 GB of RAM or more works; a graphics card makes it faster.

One command. It needs no admin rights for Miple itself, and it doesn't ask you
to install Python packages, Ollama or a model by hand.

**Linux** (Ubuntu, Debian, Mint, Pop!_OS, Fedora, Arch…):

```bash
curl -fsSL https://raw.githubusercontent.com/OsztrovszkyVlad/Miple/main/install.sh | bash
```

**Windows 10/11** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/OsztrovszkyVlad/Miple/main/install.ps1 | iex
```

The installer:

1. finds Python 3.11+, or installs it (Linux: asks once before using `sudo`
   for missing system packages such as `python3-venv` and Qt's
   `libxcb-cursor0`; Windows: a per-user Python via `winget`);
2. installs Miple into your user folder (`~/.local/share/miple` or
   `%LOCALAPPDATA%\Miple`) in its own Python environment;
3. adds **Miple** to your app menu / Start menu, with an icon;
4. sets Miple to **start automatically when you log in**;
5. starts Miple.

Installer options: `--no-autostart`, `--no-launch`, `--uninstall` (Linux) /
`-NoAutostart`, `-NoLaunch`, `-Uninstall` (Windows). Uninstalling keeps your
notes and settings, as well as Ollama and its models.

### First start: automatic setup

The first time it opens, the sidebar walks you through setup, at most two clicks:

| Step | What happens | You |
|---|---|---|
| Check your computer | Detects RAM, graphics card and its memory, CPU threads and free disk | — |
| Ollama | Starts Ollama if it's installed but not running. If it's missing, offers to install it (`winget` on Windows; the official installer via the system password prompt on Linux) | click **Install Ollama** |
| Pick a model | Chooses the best model your computer can run comfortably (table below) and explains why | — |
| Download | Downloads it with a progress bar; if you already have another model, you can use that instead | click **Download** |
| Ready | Remembers the choice; later starts skip straight to the chat | — |

On later starts all of this runs silently in the background, including
starting Ollama if it isn't running.

**How the model is chosen.** Miple picks the largest model that either fits
entirely in your graphics card's memory (fast), or runs comfortably shared
between the graphics card and RAM (the smaller models only). It then makes
sure the download fits on your disk.

| Your computer | Model | Download |
|---|---|---|
| 8 GB RAM, no graphics card | Gemma 3 1B | 0.8 GB |
| 12 GB RAM | Gemma 4 E2B | 4.6 GB |
| 16 GB+ RAM, or a 4–10 GB graphics card | Gemma 4 E4B | 6.6 GB |
| 12–20 GB graphics card | Gemma 4 12B | 8.0 GB |
| 24 GB graphics card · Mac with 36 GB+ | Gemma 4 26B (MoE) | 18 GB |
| 32 GB+ graphics card | Gemma 4 31B | 20 GB |

To force a model, set `MIPLE_MODEL` (e.g. `MIPLE_MODEL=llama3.2:3b`). To
let Miple choose again, for example after a hardware upgrade, start it with
`miple --reset-model`.

### Using it

Click the **‹** tab on the right edge of the screen to open the drawer, and
press **Esc** (or click **›**) to close it. Launching Miple again from the
menu just opens the drawer of the copy that's already running.

The drawer has three tabs:

- **Chat**: talk to Miple. One request can take several steps: Miple runs an
  action, reads the result, and continues until the request is done (at most
  5 steps). Actions that change files or install software always stop and
  wait for **Yes, do it**.
- **Notes**: the notes Miple has saved.
- **AI**: whether Ollama is installed and running, which model is in use and
  whether it's loaded (GPU/CPU), the best model for your computer, and your
  downloaded models. From here you can start or install Ollama, load the
  model, switch models, or download the recommended one. If chat says it
  can't reach Ollama, look here first.

After setup, Miple loads the model in the background and asks Ollama to keep
it in memory for 30 minutes, so replies start quickly.

### Command-line options

```
miple [--open] [--debug] [--reset-model]

  --open          start with the drawer already open
  --debug         verbose logging (same as MIPLE_DEBUG=1)
  --reset-model   forget the chosen model and pick one for this computer again
```

### Configuration

Everything is optional and set through environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `MIPLE_MODEL` | chosen automatically | Force a specific Ollama model |
| `MIPLE_OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `MIPLE_NOTES_DIR` | `~/Documents/miple-notes` | Where notes are saved |
| `MIPLE_TIMEOUT` | `300` | Seconds to wait for a reply (the first load of a model is slow) |
| `MIPLE_LOAD_TIMEOUT` | `900` | Seconds to wait when loading a model ahead of time |
| `MIPLE_KEEP_ALIVE` | `30m` | How long Ollama keeps the model in memory after the last message |
| `MIPLE_CONFIG_DIR` | see below | Where settings and the log file live |
| `MIPLE_DEBUG` | unset | `1` turns on debug logging |

Settings (the chosen model), a rotating log file `miple.log` and
`agent-steps.jsonl` (one JSON line per agent step: the model's output, the
action, its result and how long it took; it stays on your machine) are kept in
`~/.config/miple/` on Linux, `%APPDATA%\Miple\` on Windows and
`~/Library/Application Support/Miple/` on macOS.

### Running from a checkout (developers)

```bash
git clone https://github.com/OsztrovszkyVlad/Miple.git && cd Miple
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python main.py --open
```

`./install.sh` (or `.\install.ps1`) run from a checkout installs that
checkout instead of downloading it.

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
src/settings.py          saved settings (chosen model) in the OS config folder
src/agent/
  ollama.py              async Ollama client: streaming, model detection, friendly errors
  parser.py              find and strip the action block in a reply
  actions.py             normalise and dispatch actions; preview vs. confirm
  session.py             conversation state, agent loop (≤ 5 steps), background event loop
  step_log.py            JSON-lines log of every agent step
  ai_manager.py          status + controls behind the AI tab
  setup.py               start-up checks: start/install Ollama, pick + download a model
  models.py              model catalogue and hardware-based recommendation
src/actions/             everything that touches the system lives here
  files.py               organise a folder by file type (dry run, no overwrites)
  apps.py                open apps, install packages via PackageKit / pkexec
  search.py              web search in the default browser
  notes.py               save and list Markdown notes
  errors.py              heuristic error explanations
  system.py              detect RAM, GPU memory, CPU threads, free disk
  ollama_runtime.py      find, start and install Ollama
src/ui/                  PyQt6 widgets only, no business logic
  drawer.py              the sliding window, input row, confirm flow
  chat.py                message bubbles, typing indicator
  notes.py               notes browser / reader
  quickactions.py        quick-action pill buttons
  setup.py               first-run setup panel
  ai_settings.py         AI tab: Ollama status, models, download
assets/                  app icon (svg, png, ico)
install.sh, install.ps1  one-command installers
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
| *"The AI model is taking longer than expected"* | The model was still loading. Wait a moment and try again, or click **Load now** in the AI tab. |
| Setup says Ollama didn't start | Restart the computer; on Linux check `systemctl status ollama`. Also check `MIPLE_OLLAMA_URL`. |
| *"Ollama doesn't have the model …"* | Start Miple with `--reset-model` to run setup again, or set `MIPLE_MODEL` to a model you have (`ollama list`). |
| Automatic Ollama install isn't offered | Your system has no `winget` (Windows) or `pkexec` + `curl` (Linux): install Ollama from https://ollama.com/download and click **Retry**. |
| Something else | Look in `miple.log` (see *Configuration*), or start with `--debug`. |
| The first reply is very slow | The model is loading into memory; later replies are much faster. Raise `MIPLE_TIMEOUT` if it times out. |
| The drawer isn't on the screen edge | You're on native Wayland. Unset `QT_QPA_PLATFORM` so Miple can use XWayland. |
| *"No install method available"* | Install PackageKit: `sudo apt install packagekit` or `sudo dnf install PackageKit`. |
| `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` | `sudo apt install libxcb-cursor0` (Ubuntu/Debian). |

## Roadmap

- System info chat action (reuse `src/actions/system.py`)
- Undo for file organization
- Streaming replies token by token
- `.deb` / Flatpak packaging
