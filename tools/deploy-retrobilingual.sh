#!/bin/sh
# Install the RetroBilingual overlay core, driver config and optional pack.
# Requires an authorized ADB device. Makes timestamped backups first.
# This script is provided for the user; it is not run by the build.
set -eu

SERIAL=${PJOS_ADB_SERIAL:-}
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CORE="$HERE/overlay/usr/share/pocketshell/System/compat/lib/libretro/mgba-retrobilingual_libretro.so"
DRIVER="$HERE/overlay/usr/share/pocketshell/System/compat/share/retroarch/driver.cfg"
DEVICE_CORE=/storage/System/compat/lib/libretro/mgba-retrobilingual_libretro.so
DEVICE_DRIVER=/storage/System/compat/share/retroarch/driver.cfg
CONFIG_DIR=/storage/.config/pocketjs

usage() {
    echo "usage: $0 [--check] [--pack <retrobilingual.pack>]" >&2
    exit 2
}

CHECK=0
PACK=
while [ "$#" -gt 0 ]; do
    case "$1" in
    --check) CHECK=1 ;;
    --pack) shift; [ "$#" -gt 0 ] || usage; PACK=$1 ;;
    *) usage ;;
    esac
    shift
done

[ -s "$CORE" ] || { echo "missing core: $CORE (run tools/build-retrobilingual-mgba-h700.sh)" >&2; exit 1; }
[ -s "$DRIVER" ] || { echo "missing driver config: $DRIVER" >&2; exit 1; }
[ -z "$PACK" ] || [ -s "$PACK" ] || { echo "missing pack: $PACK" >&2; exit 1; }

if [ -z "$SERIAL" ]; then
    SERIAL=$(adb devices | awk 'NR > 1 && $2 == "device" { print $1; exit }')
fi
[ -n "$SERIAL" ] || { echo "no authorized ADB device" >&2; exit 1; }

adb -s "$SERIAL" shell 'test -d /storage/System/compat/lib/libretro' \
    || { echo "unexpected device layout (no /storage/System/compat/lib/libretro)" >&2; exit 1; }

host_hash=$(sha256sum "$CORE" | awk '{print $1}')
driver_hash=$(sha256sum "$DRIVER" | awk '{print $1}')

if [ "$CHECK" = 1 ]; then
    echo "core sha256: $host_hash"
    echo "driver sha256: $driver_hash"
    exit 0
fi

stamp=$(date +%Y%m%d-%H%M%S)
backup=/storage/pjs/retrobilingual-backup-$stamp
adb -s "$SERIAL" shell "mkdir -p '$backup' && { [ ! -f '$DEVICE_CORE' ] || cp '$DEVICE_CORE' '$backup/' ; } && { [ ! -f '$DEVICE_DRIVER' ] || cp '$DEVICE_DRIVER' '$backup/' ; } && mkdir -p '$CONFIG_DIR'"
echo "backup: $backup"

tmp=/storage/.config/pocketjs/.retrobilingual-core.new
adb -s "$SERIAL" push "$CORE" "$tmp" >/dev/null
adb -s "$SERIAL" shell "chmod 0644 '$tmp' && mv -f '$tmp' '$DEVICE_CORE'"
installed=$(adb -s "$SERIAL" shell sha256sum "$DEVICE_CORE" | awk '{print $1}')
[ "$installed" = "$host_hash" ] || { echo "core hash mismatch after install" >&2; exit 1; }

adb -s "$SERIAL" push "$DRIVER" /storage/System/compat/share/retroarch/.driver.cfg.new >/dev/null
adb -s "$SERIAL" shell "mv -f /storage/System/compat/share/retroarch/.driver.cfg.new '$DEVICE_DRIVER'"

if [ -n "$PACK" ]; then
    adb -s "$SERIAL" push "$PACK" "$CONFIG_DIR/retrobilingual.pack" >/dev/null
fi

echo "installed core $installed"
echo "installed driver.cfg"
[ -z "$PACK" ] || echo "installed pack $CONFIG_DIR/retrobilingual.pack"
echo "start the Japanese ROM through PocketShell; X opens the menu, L+Select toggles subtitles"
