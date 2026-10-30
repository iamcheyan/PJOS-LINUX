#!/bin/sh
# Copy the built PocketShell package into the BaseOS card payload.
#
# Launcher work happens in the pocketshell repository; this image only needs to
# ship the artifact. A launcher change is therefore `make deploy` in that repo —
# this script is only for rebuilding an image that must carry the new package.
#
#   tools/sync-pocketshell.sh [path/to/pocketshell.pocket]
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=${1:-${POCKETSHELL_PKG:-$HOME/development/pocketshell/dist/pocketshell.pocket}}
DST="$ROOT/overlay/usr/share/pocketshell/System/pocketjs/apps/boot.pocket"
VERSION="$ROOT/overlay/usr/share/pocketshell/System/pocketjs/version"

[ -f "$SRC" ] || {
	printf 'sync-pocketshell: no package at %s\n' "$SRC" >&2
	printf 'build it first: make build in the pocketshell checkout\n' >&2
	exit 1
}

cp -f "$SRC" "$DST"
sync

SIZE=$(wc -c < "$DST" | tr -d ' ')
SHA=$(sha256sum "$DST" | cut -d' ' -f1)

# Keep the runtime lines as they are; only the launcher facts are ours.
grep -v '^Launcher package ' "$VERSION" > "$VERSION.tmp" || true
{
	cat "$VERSION.tmp"
	printf 'Launcher package source: pocketshell repository\n'
	printf 'Launcher package size: %s bytes\n' "$SIZE"
	printf 'Launcher package SHA-256: %s\n' "$SHA"
} > "$VERSION"
rm -f "$VERSION.tmp"

printf 'synced %s\n  %s bytes\n  sha256 %s\n' "$DST" "$SIZE" "$SHA"
