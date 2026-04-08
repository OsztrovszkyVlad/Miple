# Miple — Project Context

## What this is
A local-first AI desktop assistant for Linux.
A GTK4 sidebar drawer that slides in from the right side of the screen.
Runs Gemma 4 (E4B) via Ollama entirely on the user's machine.
No data leaves the user's machine. Ever.
Built to be sold to a Linux distro company or privacy-focused tech company.

## Product vision
- The pull tab is always visible on the right screen edge
- Clicking it slides open a 300px drawer — the tab moves WITH the drawer
- Only the pull tab is visible when closed
- Feels native, unobtrusive, always accessible

## Stack
- Python 3.11+
- GTK4 via PyGObject
- Ollama at http://localhost:11434
- Primary model: Gemma 4 E4B (gemma4:e4b)
- Fallback: any available Ollama model
- Display server: Wayland (GTK4 native — no X11 assumptions)

## Target OS
- Development machine: Fedora 43
- Primary release target: Ubuntu 24.04 LTS (Noble Numbat) — current stable
- Forward compatible: Ubuntu 26.04 LTS (Resolute Raccoon) — April 23 2026
- Supported: Any Debian/Ubuntu-based distro (Mint, Zorin, Pop!_OS, elementary)
- Stretch goal: Fedora, Arch (requires package manager detection)
- Package manager: detect at runtime — apt / dnf / pacman

## Minimum hardware
- 4GB VRAM GPU (GTX 1650 era or newer)
- 16GB RAM
- SSD strongly preferred
- Any machine from 2019 onwards

## Architecture
- src/ui/drawer.py — GTK4 drawer widget + pull tab + animation
- src/ui/chat.py — chat bubble components
- src/ui/quickactions.py — quick action pill buttons
- src/agent/ollama.py — Ollama API client + streaming
- src/agent/parser.py — extract action JSON from model response
- src/agent/actions.py — central action dispatcher
- src/actions/files.py — file organization
- src/actions/apps.py — app install + open
- src/actions/search.py — Google search via browser
- src/actions/notes.py — note writer to ~/Documents/miple-notes/
- src/actions/errors.py — error explainer + auto-fix
- src/actions/system.py — package manager detection + system info
- tests/ — one test file per module

## Features — v1
1. File organization — scan folder, sort into subfolders by type (documents, images, music, video, archives, code)
2. App installation — detect package manager, run install command
3. Open app — launch any application by name
4. Google search — open default browser with search query
5. Error fixer — user pastes error, Miple explains and attempts auto-fix
6. Note writer — create/save plain text notes to ~/Documents/miple-notes/

## AI integration
- All messages go to Ollama /api/chat endpoint
- System prompt: "You are Miple, a local AI assistant running on the user's Linux machine. You help with file organization, app installation, opening apps, searching the web, fixing errors, and taking notes. When you need to perform an action, include a JSON block in your response like this: {action: 'organize_files', params: {path: '~/Downloads'}}. Keep responses short and friendly. Never perform destructive actions without user confirmation."
- Parse model response for action JSON and execute via actions dispatcher
- Show typing indicator while waiting for response
- Handle Ollama not running gracefully — friendly error in chat, never crash

## Rules — never break these
- Never execute destructive commands without explicit user confirmation
- Always show the user what command will run before running it
- Never hardcode paths — use pathlib and Path.home() resolution
- Every action module must have a dry_run=True mode
- UI and logic must be completely separate — zero business logic in UI files
- All subprocess calls go through src/actions/ modules only
- Never crash on missing Ollama — handle gracefully with friendly message
- All file operations must be reversible or confirmed before execution

## Coding style
- Type hints on every function signature
- Docstrings on every class and every public method
- No print() statements — use Python logging module throughout
- Max function length: 40 lines — split if longer
- One responsibility per file — no multipurpose modules

## Session strategy
- Use Plan mode at the start of every complex multi-file task
- Split work into focused sessions — one feature per session
- Use subagents for parallel work (ui-agent, action-agent, ollama-agent)
- Never carry unrelated context between sessions

## Current phase
Phase 1 — GTK4 drawer UI with pull tab animation + Ollama connection + file organization action

## Demo goal
User types: "My downloads folder is a mess, fix it"
Miple scans, confirms plan, organizes 847 files into 5 folders, opens file manager.
Total time on screen: 90 seconds. Jaw drops.