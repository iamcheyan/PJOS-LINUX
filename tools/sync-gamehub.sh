#!/bin/sh
# Update the default PJOS image with a built GameHub PocketJS app and Apotris homebrew.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=${1:-$ROOT/apps/pocket-gamehub/dist/gamehub.pocket}
DST="$ROOT/overlay/usr/share/pocketshell/System/pocketjs/apps/gamehub.pocket"
ROM_SRC=${POCKET_GAMEHUB_ROM:-$ROOT/apps/pocket-gamehub/roms/apotris.gba}
ROM_DST="$ROOT/overlay/usr/share/pocketshell/System/pocketjs/apps/apotris.gba"
[ -s "$SRC" ] || { echo "sync-gamehub: missing package: $SRC" >&2; exit 1; }
[ -s "$ROM_SRC" ] || { echo "sync-gamehub: missing Apotris ROM: $ROM_SRC" >&2; exit 1; }
mkdir -p "${DST%/*}"
cp -f "$SRC" "$DST.new"
mv -f "$DST.new" "$DST"
cp -f "$ROM_SRC" "$ROM_DST.new"
mv -f "$ROM_DST.new" "$ROM_DST"
sync
printf 'synced %s (%s bytes; sha256 %s)\n' "$DST" "$(wc -c < "$DST" | tr -d ' ')" "$(sha256sum "$DST" | cut -d' ' -f1)"
printf 'synced %s (%s bytes)\n' "$ROM_DST" "$(wc -c < "$ROM_DST" | tr -d ' ')"
