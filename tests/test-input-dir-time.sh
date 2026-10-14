#!/bin/sh
# rcS's real /dev/input line, run by BusyBox on a directory whose modification
# time is zero, as the kernel leaves it when the gamepad registers within the
# first second. SDL's scan without udev finds no gamepad at that value.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=tools/docker-platform.sh
. "$HERE/tools/docker-platform.sh"

docker run --rm -i --platform "$BASEOS_DOCKER_PLATFORM_HOST" \
  -v "$HERE/overlay/etc/init.d/rcS":/rcS:ro alpine:3.20 sh -eu <<'TEST'
line=$(grep -n '^/bin/touch -c -d @1 /dev/input' /rcS | cut -d: -f1)
[ -n "$line" ] || { echo 'FAIL: rcS does not set the /dev/input time'; exit 1; }
# It must run once /dev is mounted and before anything that could start a frontend.
mounted=$(grep -n 'mount -t devtmpfs dev /dev' /rcS | cut -d: -f1)
first_program=$(grep -nE '^[^#]*(insmod|frontend|baseos-update|adbd)' /rcS | head -1 | cut -d: -f1)
[ "$mounted" -lt "$line" ] && [ "$line" -lt "$first_program" ] \
	|| { echo "FAIL: /dev/input time is set at line $line, outside $mounted..$first_program"; exit 1; }

mkdir -p /fake/input
sed -n "${line}p" /rcS | sed 's|/dev/input|/fake/input|' > /tmp/line
for start in 0 1 1791938430; do
	touch -d "@$start" /fake/input
	[ "$(stat -c %Y /fake/input)" = "$start" ]
	sh /tmp/line
	[ "$(stat -c %Y /fake/input)" = 1 ] || { echo "FAIL: time $start became $(stat -c %Y /fake/input)"; exit 1; }
done
echo 'ok: a zero time becomes 1, the value a stock boot has'
# Without the directory nothing may appear in its place: a file of that name
# would stop the kernel from creating the directory for a later device.
rmdir /fake/input
sh /tmp/line || true
[ ! -e /fake/input ] || { echo 'FAIL: the line created something at the missing path'; exit 1; }
echo 'ok: a missing directory is left missing'
echo '/dev/input time tests passed'
TEST
