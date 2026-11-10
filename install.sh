#!/usr/bin/env bash
# Miple installer for Linux (and macOS).
#
#   curl -fsSL https://raw.githubusercontent.com/OsztrovszkyVlad/Miple/main/install.sh | bash
#   ./install.sh                  # from a checkout
#   ./install.sh --uninstall      # remove Miple (keeps your notes and settings)
#
# Options: --no-autostart  --no-launch  --uninstall
# Env:     MIPLE_BRANCH (default: main)  MIPLE_HOME (default: ~/.local/share/miple)
#
# Everything goes into your home folder; sudo is only used (after asking) to
# install missing system packages such as python3-venv.
set -euo pipefail

REPO="OsztrovszkyVlad/Miple"
BRANCH="${MIPLE_BRANCH:-main}"
MIPLE_HOME="${MIPLE_HOME:-$HOME/.local/share/miple}"
APP_DIR="$MIPLE_HOME/app"
VENV_DIR="$MIPLE_HOME/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/miple"
DESKTOP_FILE="$HOME/.local/share/applications/miple.desktop"
AUTOSTART_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/miple.desktop"
ICON_FILE="$HOME/.local/share/icons/hicolor/scalable/apps/miple.svg"

AUTOSTART=1
LAUNCH=1
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    --no-launch) LAUNCH=0 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

ask() {  # ask "Question?" → 0 for yes (default yes); works under curl | bash
  local reply
  if [ -r /dev/tty ]; then
    printf '%s [Y/n] ' "$1" > /dev/tty
    read -r reply < /dev/tty || reply=""
  else
    reply="y"
  fi
  case "$reply" in [nN]*) return 1 ;; *) return 0 ;; esac
}

uninstall() {
  say "Removing Miple"
  pkill -f "$APP_DIR/main.py" 2>/dev/null || true
  rm -rf "$MIPLE_HOME" "$LAUNCHER" "$DESKTOP_FILE" "$AUTOSTART_FILE" "$ICON_FILE"
  say "Done. Your notes (~/Documents/miple-notes) and settings were kept."
  say "Ollama and its models were left installed; remove them with your package manager if you like."
}

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      command -v "$candidate"; return 0
    fi
  done
  return 1
}

missing_packages() {  # prints distro package names this machine still needs
  local py="${1:-}"
  local need=()
  if command -v apt-get >/dev/null 2>&1; then
    [ -z "$py" ] && need+=(python3)
    if [ -n "$py" ] && ! "$py" -c 'import ensurepip, venv' 2>/dev/null; then
      need+=("python3-venv")
    fi
    ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0' || need+=(libxcb-cursor0)
  elif command -v dnf >/dev/null 2>&1; then
    [ -z "$py" ] && need+=(python3)
    ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0' || need+=(xcb-util-cursor)
  elif command -v pacman >/dev/null 2>&1; then
    [ -z "$py" ] && need+=(python)
    ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0' || need+=(xcb-util-cursor)
  fi
  echo "${need[@]:-}"
}

install_packages() {
  local pkgs="$1"
  [ -z "$pkgs" ] && return 0
  if ! ask "Miple needs these system packages: $pkgs. Install them now with sudo?"; then
    warn "Skipping. Install them yourself if Miple doesn't start: $pkgs"
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y $pkgs
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y $pkgs
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm $pkgs
  fi
}

# ---------------------------------------------------------------------------
# App files
# ---------------------------------------------------------------------------

fetch_app() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
  rm -rf "$APP_DIR.new"
  mkdir -p "$APP_DIR.new"
  if [ -n "$here" ] && [ -f "$here/main.py" ] && [ -d "$here/src" ]; then
    say "Installing from $here"
    (cd "$here" && tar --exclude=.git --exclude=.venv --exclude=venv --exclude=floorplan \
        --exclude='__pycache__' -cf - .) | tar -xf - -C "$APP_DIR.new"
  else
    say "Downloading Miple ($BRANCH)"
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" |
      tar -xzf - -C "$APP_DIR.new" --strip-components=1
  fi
  rm -rf "$APP_DIR"
  mv "$APP_DIR.new" "$APP_DIR"
}

make_venv() {
  local py="$1"
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    say "Creating Python environment"
    "$py" -m venv "$VENV_DIR"
  fi
  say "Installing Python packages (PyQt6, httpx)"
  "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
  "$VENV_DIR/bin/python" -m pip install --quiet -r "$APP_DIR/requirements.txt"
}

write_launchers() {
  mkdir -p "$BIN_DIR" "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON_FILE")"
  cat > "$LAUNCHER" <<EOF
#!/bin/sh
exec "$VENV_DIR/bin/python" "$APP_DIR/main.py" "\$@"
EOF
  chmod +x "$LAUNCHER"
  cp "$APP_DIR/assets/miple.svg" "$ICON_FILE"

  desktop_entry() {
    cat <<EOF
[Desktop Entry]
Type=Application
Name=Miple
GenericName=AI Assistant
Comment=Your AI, locally — a sidebar assistant that runs on your computer
Exec=$LAUNCHER $1
Icon=miple
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
  }
  desktop_entry "--open" > "$DESKTOP_FILE"
  if [ "$AUTOSTART" = 1 ]; then
    mkdir -p "$(dirname "$AUTOSTART_FILE")"
    { desktop_entry ""; echo "X-GNOME-Autostart-enabled=true"; } > "$AUTOSTART_FILE"
  else
    rm -f "$AUTOSTART_FILE"
  fi
  command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database -q "$(dirname "$DESKTOP_FILE")" 2>/dev/null || true
}

main() {
  if [ "$UNINSTALL" = 1 ]; then uninstall; exit 0; fi
  [ "$(id -u)" = 0 ] && die "Run this as your normal user, not root."
  command -v curl >/dev/null 2>&1 || die "curl is required."

  local py=""
  py="$(find_python || true)"
  install_packages "$(missing_packages "$py")"
  [ -z "$py" ] && py="$(find_python || true)"
  [ -z "$py" ] && die "Python 3.11 or newer is required. Install it with your package manager and run this again."
  say "Using $("$py" --version) ($py)"

  mkdir -p "$MIPLE_HOME"
  fetch_app
  make_venv "$py"
  write_launchers

  say "Miple is installed."
  echo "    Start it from your app menu, or run: miple"
  [ "$AUTOSTART" = 1 ] && echo "    It will also start automatically when you log in."
  case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not on your PATH; use the app menu or $LAUNCHER" ;; esac
  echo "    On first start Miple checks your computer, installs Ollama if needed and"
  echo "    downloads the AI model that fits it best — just follow the sidebar."

  if [ "$LAUNCH" = 1 ]; then
    say "Starting Miple"
    nohup "$LAUNCHER" --open >/dev/null 2>&1 &
  fi
}

main
