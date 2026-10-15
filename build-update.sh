#!/bin/sh
# Build the .bosupd system-update payload for one target from its composed
# image. Users copy the result onto their card; the next boot applies it to the
# inactive rootfs slot without touching their ROMs, saves or settings.
# Usage: ./build-update.sh <target> [--sequential]
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/docker-platform.sh
. "$HERE/tools/docker-platform.sh"
TARGET="${1:?usage: $0 <target>}"
[ "$#" -eq 1 ] || { [ "$#" -eq 2 ] && [ "$2" = --sequential ]; } || {
  echo "usage: $0 <target> [--sequential]" >&2; exit 2;
}

WORK="$HERE/work/$TARGET"
IMAGE="$WORK/baseos-$TARGET.img"
PANEL_IMAGE=
if [ "${2:-}" = --sequential ]; then
  IMAGE="$WORK/baseos-$TARGET-old.img"
  PANEL_IMAGE="$WORK/baseos-$TARGET-boe.img"
  [ -f "$PANEL_IMAGE" ] || { echo "missing $PANEL_IMAGE (compose both internal panel variants)" >&2; exit 1; }
fi
[ -f "$IMAGE" ] || { echo "missing $IMAGE (run build-image.sh $TARGET)" >&2; exit 1; }

BASEOS_VERSION="$(tr -d ' \n' < "$HERE/VERSION")"
BASEOS_BUILD="$(git -C "$HERE" describe --always --dirty 2>/dev/null || echo unknown)"
OUT="$WORK/baseos-$TARGET-$BASEOS_VERSION.bosupd"

# Read filesystem metadata with the same ext4 tools used to compose the image.
docker run --rm --platform "$BASEOS_DOCKER_PLATFORM_HOST" \
  -v "$WORK":/work -v "$HERE/tools":/tools:ro alpine:3.20 sh -euc '
  apk add -q python3 e2fsprogs-extra
  if [ -n "$6" ]; then
    python3 /tools/mkupdate.py "/work/$1" "$2" "$3" "$4" "/work/$5" --panel-image "/work/$6"
  else
    python3 /tools/mkupdate.py "/work/$1" "$2" "$3" "$4" "/work/$5"
  fi
' sh "$(basename "$IMAGE")" "$TARGET" "$BASEOS_VERSION" "$BASEOS_BUILD" "$(basename "$OUT")" "${PANEL_IMAGE:+$(basename "$PANEL_IMAGE")}"

echo
echo "Copy $(basename "$OUT") to the root of the card and power on."
