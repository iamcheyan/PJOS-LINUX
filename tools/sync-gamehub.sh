#!/bin/sh
# Update the default PJOS image with a built GameHub PocketJS app.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=${1:-$ROOT/apps/pocket-gamehub/dist/gamehub.pocket}
DST="$ROOT/overlay/usr/share/pocketshell/System/pocketjs/apps/gamehub.pocket"
[ -s "$SRC" ] || { echo "sync-gamehub: missing package: $SRC" >&2; exit 1; }
mkdir -p "${DST%/*}"
cp -f "$SRC" "$DST.new"
mv -f "$DST.new" "$DST"
sync
printf 'synced %s (%s bytes; sha256 %s)\n' "$DST" "$(wc -c < "$DST" | tr -d ' ')" "$(sha256sum "$DST" | cut -d' ' -f1)"
