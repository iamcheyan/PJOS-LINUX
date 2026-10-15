#!/bin/sh
# Host-only, real ext4/packer/updater behavior in a disposable container.
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
. "$HERE/tools/docker-platform.sh"
[ "$#" -eq 2 ] || { echo "usage: $0 NATIVE_DIR ROOTFS_TAR (both inside this checkout)" >&2; exit 2; }
relative() { python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[2]).resolve().relative_to(Path(sys.argv[1]).resolve()))' "$HERE" "$1"; }
NATIVE="$(relative "$1")"
ROOTFS="$(relative "$2")"
docker run --rm --platform "$BASEOS_DOCKER_PLATFORM_HOST" -v "$HERE":/repo:ro \
  -e BASEOS_NATIVE_FIXTURE="/repo/$NATIVE" -e BASEOS_ROOTFS_FIXTURE="/repo/$ROOTFS" \
  -e BASEOS_DISPOSABLE_TEST_CONTAINER=1 alpine:3.20 sh -euc '
  apk add -q python3 e2fsprogs-extra squashfs-tools
  python3 /repo/tests/test-sequential-update.py
'
