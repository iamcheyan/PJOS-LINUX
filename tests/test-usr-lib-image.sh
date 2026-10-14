#!/bin/sh
# rcS's real /usr/lib block, run on files and a mount stub: an image built by
# build-image.sh gets its squashfs file mounted, a bare tree is left alone, and
# a failed mount is reported. Compatible with BusyBox ash.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
RCS="$HERE/overlay/etc/init.d/rcS"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin" "$TMP/usr/share/baseos"
export LIB_TEST_TMP="$TMP"
fail() { echo "FAIL: $*" >&2; exit 1; }
IMAGE=/usr/share/baseos/usr-lib.sqfs

awk '/^# \/usr\/lib\. A composed image/{copy=1} /^\/bin\/mkdir -p \/dev\/pts/{copy=0} copy' "$RCS" \
	| sed -e "s|=$IMAGE|=$TMP$IMAGE|" \
		-e "s|/bin/mount |$TMP/bin/mount |g" \
		-e "s|/dev/kmsg|$TMP/kmsg|g" > "$TMP/lib-block"
grep -q 'squashfs' "$TMP/lib-block" || fail "rcS /usr/lib block not found"

cat > "$TMP/bin/mount" <<'STUB'
#!/bin/sh
printf 'mount %s\n' "$*" >> "$LIB_TEST_TMP/events"
[ ! -e "$LIB_TEST_TMP/mount-fails" ]
STUB
chmod 755 "$TMP/bin/mount"
run() {
	rm -f "$TMP/kmsg"
	: > "$TMP/events"
	sh "$TMP/lib-block"
}

# A bare tree keeps its libraries in the directory: nothing to mount.
run
[ ! -s "$TMP/events" ] || fail "mounted without an image: $(cat "$TMP/events")"
[ ! -e "$TMP/kmsg" ] || fail "a bare tree logged a message"
echo 'ok: a rootfs without the image file is left alone'

# A directory of that name is not an image.
mkdir "$TMP$IMAGE"
run
[ ! -s "$TMP/events" ] || fail "mounted a directory: $(cat "$TMP/events")"
rmdir "$TMP$IMAGE"

# The image is mounted once, read-only, through a loop device, over /usr/lib.
: > "$TMP$IMAGE"
run
[ "$(cat "$TMP/events")" = "mount -t squashfs -o loop,ro,nodev,nosuid $TMP$IMAGE /usr/lib" ] \
	|| fail "image mount: $(cat "$TMP/events")"
[ ! -e "$TMP/kmsg" ] || fail "a good mount logged a message"
echo 'ok: the image is mounted read-only over /usr/lib'

# A failed mount is reported and does not stop startup.
touch "$TMP/mount-fails"
run || fail "a failed mount stopped the block"
grep -q 'the /usr/lib image did not mount' "$TMP/kmsg" || fail "failed mount not reported"
echo 'ok: a failed mount is reported and startup continues'

# Only static programs may run before the mount: the shell with its builtins,
# the BusyBox applets and the bundled e2fsck. A new command above the block
# needs the same property.
before=$(awk '/^# \/usr\/lib\. A composed image/{exit} {print}' "$RCS" | grep -v '^[[:space:]]*#' \
	| grep -oE '(^|[[:space:];|&(])/(usr/)?s?bin/[A-Za-z0-9_.-]+' | grep -oE '/.*' | sort -u | tr '\n' ' ')
[ "$before" = '/bin/mount /bin/touch /usr/sbin/e2fsck ' ] || fail "programs run before the /usr/lib mount: $before"
echo 'ok: only BusyBox mount and touch and the static e2fsck run before the mount'
echo '/usr/lib image tests passed'
