#!/usr/bin/env bash
# Drop-in shell wrapper. Call this from any Claude Code PreToolUse hook (or by hand)
# to pop the gesture confirmation. Returns the gesture decision via exit code.
#
# Usage:
#   scripts/claude-approve.sh "Run npm install?"
#
# Exit codes:
#   0  approve   (thumbs up)
#   1  deny      (thumbs down)
#   2  manual    (fist — user will handle it)
#   3  timeout
#   4  cancelled
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT="${1:-Approve this action?}"
TIMEOUT="${HANDSIGNAL_TIMEOUT:-15}"

# Activate the venv so `handsignal` is on PATH.
# shellcheck disable=SC1091
source "$REPO_ROOT/.venv/bin/activate"
exec handsignal ask "$PROMPT" --timeout "$TIMEOUT"
