#!/bin/sh
# keyboardd launch glue for the PJOS Universal Input Framework.
#
# Starts the keyboardd backend service and (when the PocketKeyboardProvider is
# installed) the keyboard UI provider. The backend is the only hard dependency:
# applications use the Input API and the keyboard only appears when an input is
# focused. Desktop Debug Mode runs the same binary with no device needed.
#
# Env:
#   KEYBOARDD_ADDR    loopback listen addr (default 127.0.0.1:8787)
#   KEYBOARDD_DB      optional sqlite path; requires -tags sqlite build
#   KEYBOARDD_BIN     path to the keyboardd binary (default /usr/bin/keyboardd)
#
# This script never renders a keyboard itself and never touches other services.
set -eu

KEYBOARDD_BIN="${KEYBOARDD_BIN:-/usr/bin/keyboardd}"
KEYBOARDD_ADDR="${KEYBOARDD_ADDR:-127.0.0.1:8787}"

if [ ! -x "$KEYBOARDD_BIN" ]; then
	echo "keyboardd: binary not found at $KEYBOARDD_BIN; skipping" >&2
	exit 0
fi

# Already running? Reuse it.
if command -v pgrep >/dev/null 2>&1 && pgrep -f "$KEYBOARDD_BIN" >/dev/null 2>&1; then
	echo "keyboardd: already running" >&2
	exit 0
fi

echo "keyboardd: starting at $KEYBOARDD_ADDR" >&2
KEYBOARDD_ADDR="$KEYBOARDD_ADDR" KEYBOARDD_DB="${KEYBOARDD_DB:-}" \
	"$KEYBOARDD_BIN" &
