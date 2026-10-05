#!/usr/bin/env bash
# Speak the current primary selection (whatever text is highlighted anywhere
# on screen) via say_daemon.py's persistent TTS server. Meant to be bound to a
# global keyboard shortcut so reading text aloud is "select it, press a key"
# instead of opening a terminal and pasting into say_onnx.py.
#
# say_client.py starts the daemon on first use (announcing via espeak-ng while
# it loads) and reuses it on every press after that. Pressing the shortcut
# again while it's still talking interrupts the old text and speaks the new
# selection; the daemon handles that, not this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

text=$(wl-paste --primary --no-newline 2>/dev/null || true)
[[ -z "$text" ]] && exit 0

"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/say_client.py" "$text" &
disown
