#!/bin/sh
# keyboardd launch glue for the PJOS Universal Input Framework.
#
# Starts the keyboardd backend service and returns immediately. The service owns
# the on-screen keyboard: applications reach it through the Input API instead of
# drawing their own keyboard.
#
# It is safe from the frontend session because the service is fully detached:
# its own session (setsid when available) and stdin from /dev/null, so the
# frontend's later `exec` cannot take it down with the shell.
#
# Env:
#   KEYBOARDD_ADDR  loopback listen address (default 127.0.0.1:8787)
#   KEYBOARDD_DB    sqlite path; only meaningful in a -tags sqlite build
#   KEYBOARDD_BIN   path to the binary (default /usr/bin/keyboardd)
#
# Never blocks the boot, never renders a keyboard itself, and never touches
# other services or the display stack.
set -eu

KEYBOARDD_BIN="${KEYBOARDD_BIN:-/usr/bin/keyboardd}"
KEYBOARDD_ADDR="${KEYBOARDD_ADDR:-127.0.0.1:8787}"

if [ ! -x "$KEYBOARDD_BIN" ]; then
	echo "keyboardd: not installed at $KEYBOARDD_BIN; keyboard stays with the app" >&2
	exit 0
fi

# Already running? Nothing to do.
if command -v pidof >/dev/null 2>&1 && pidof keyboardd >/dev/null 2>&1; then
	echo "keyboardd: already running" >&2
	exit 0
fi

echo "keyboardd: starting at $KEYBOARDD_ADDR" >&2

# Detach from the caller's session. A bare `cmd &` would be reaped when the
# frontend session execs its launcher.
if command -v setsid >/dev/null 2>&1; then
	KEYBOARDD_ADDR="$KEYBOARDD_ADDR" KEYBOARDD_DB="${KEYBOARDD_DB:-}" \
		setsid "$KEYBOARDD_BIN" </dev/null >/tmp/keyboardd.log 2>&1 &
else
	KEYBOARDD_ADDR="$KEYBOARDD_ADDR" KEYBOARDD_DB="${KEYBOARDD_DB:-}" \
		"$KEYBOARDD_BIN" </dev/null >/tmp/keyboardd.log 2>&1 &
fi
