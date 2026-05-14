#!/usr/bin/env bash
# hand-signal — one-shot setup for macOS / Linux.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "▸ hand-signal setup"
echo "  repo: $REPO_ROOT"

# ---- 1. venv + python deps ----
if [[ ! -d .venv ]]; then
  echo "  ▸ creating .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -e ".[dev]"

# ---- 2. first-run config ----
mkdir -p "$HOME/.config/hand-signal"
if [[ ! -f "$HOME/.config/hand-signal/config.toml" ]]; then
  handsignal init
else
  echo "  ✓ config already exists at ~/.config/hand-signal/config.toml"
fi

echo
echo "  ✓ setup complete."
echo
echo "  Try:"
echo "       source .venv/bin/activate"
echo "       handsignal doctor       # verify camera + deps"
echo "       handsignal listen       # watch for gestures (print mode)"
echo "       handsignal listen --keystrokes   # inject keystrokes (Accessibility required on macOS)"
echo
echo "  ! macOS: grant Camera + (optional) Accessibility access to your terminal app."
echo "    System Settings → Privacy & Security → Camera / Accessibility"
