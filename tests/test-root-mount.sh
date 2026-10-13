#!/bin/sh
# rcS's real root-filesystem block, run on files and command stubs: what a boot
# without the vendor initramfs must do to a kernel-mounted read-only root, and
# what a boot with it must leave alone. Compatible with BusyBox ash.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
RCS="$HERE/overlay/etc/init.d/rcS"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/bin"
export ROOT_TEST_TMP="$TMP"
fail() { echo "FAIL: $*" >&2; exit 1; }

awk '/^# Root filesystem\. The vendor initramfs/{copy=1} /^# \/usr\/lib\. A composed image/{copy=0} copy' "$RCS" \
	| sed -e "s|/proc/mounts|$TMP/mounts|g" \
		-e "s|/sys/fs/ext4/mmcblk0p5/errors_count|$TMP/errors_count|g" \
		-e "s|/usr/sbin/e2fsck|$TMP/bin/e2fsck|g" \
		-e "s|/bin/mount |$TMP/bin/mount |g" \
		-e "s|/dev/kmsg|$TMP/kmsg|g" > "$TMP/root-block"
grep -q 'remount,rw' "$TMP/root-block" || fail "rcS root block not found"

cat > "$TMP/bin/mount" <<'EOF'
#!/bin/sh
printf 'mount %s\n' "$*" >> "$ROOT_TEST_TMP/events"
case "$2" in *nobarrier*) [ ! -e "$ROOT_TEST_TMP/full-remount-fails" ] || exit 1 ;; esac
[ ! -e "$ROOT_TEST_TMP/every-remount-fails" ] || exit 1
EOF
chmod 755 "$TMP/bin/mount"
fsck_stub() {
	printf '#!/bin/sh\nprintf "e2fsck %%s\\n" "$*" >> "$ROOT_TEST_TMP/events"\nexit %s\n' "$1" > "$TMP/bin/e2fsck"
	chmod 755 "$TMP/bin/e2fsck"
}
run() {
	rm -f "$TMP/events" "$TMP/kmsg"
	: > "$TMP/events"
	sh "$TMP/root-block"
}
FULL='mount -o remount,rw,noatime,nodiratime,nobarrier,noauto_da_alloc /'
kernel_root() {
	printf 'rootfs / rootfs rw 0 0\n/dev/root / ext4 ro,relatime,data=ordered 0 0\nproc /proc proc rw 0 0\n' > "$TMP/mounts"
}

# With the vendor initramfs the root arrives writable: nothing to do.
printf 'rootfs / rootfs rw 0 0\n/dev/mmcblk0p5 / ext4 rw,noatime,nodiratime,nobarrier,noauto_da_alloc,data=ordered 0 0\n' > "$TMP/mounts"
echo 0 > "$TMP/errors_count"
fsck_stub 0
run
[ ! -s "$TMP/events" ] || fail "writable root was touched: $(cat "$TMP/events")"
echo 'ok: a root the initramfs already mounted writable is left alone'

# Kernel-mounted, clean: one remount with the options the initramfs used.
kernel_root
run
[ "$(cat "$TMP/events")" = "$FULL" ] || fail "clean root: $(cat "$TMP/events")"
[ ! -e "$TMP/kmsg" ] || fail "clean boot logged a message"
echo 'ok: a clean kernel-mounted root becomes writable with the previous options'

# A kernel that rejects an option still gets a writable root.
touch "$TMP/full-remount-fails"
run
[ "$(cat "$TMP/events")" = "$(printf '%s\nmount -o remount,rw,noatime /' "$FULL")" ] \
	|| fail "fallback remount: $(cat "$TMP/events")"
touch "$TMP/every-remount-fails"
run
grep -q 'stays read-only: remount failed' "$TMP/kmsg" || fail "failed remount not reported"
rm "$TMP/full-remount-fails" "$TMP/every-remount-fails"
echo 'ok: remount falls back to plain options and reports a failure'

# Recorded errors: check first. A checker that changed nothing permits writes.
echo 3 > "$TMP/errors_count"
run
[ "$(cat "$TMP/events")" = "$(printf 'e2fsck -y /dev/mmcblk0p5\n%s' "$FULL")" ] \
	|| fail "flagged root, clean check: $(cat "$TMP/events")"
grep -q 'had 3 recorded errors; e2fsck exit 0' "$TMP/kmsg" || fail "check not reported"
echo 'ok: recorded errors run the checker before the root becomes writable'

# A checker that repaired a mounted root (or could not) leaves it read-only.
for status in 1 3 4 8; do
	fsck_stub "$status"
	run
	[ "$(cat "$TMP/events")" = 'e2fsck -y /dev/mmcblk0p5' ] \
		|| fail "exit $status still remounted: $(cat "$TMP/events")"
	grep -q "e2fsck exit $status" "$TMP/kmsg" || fail "exit $status not reported"
done
echo 'ok: a repaired or unrepairable root stays read-only for this boot'

# Missing checker or unreadable counter: behave as a clean boot.
rm "$TMP/bin/e2fsck"
run
[ "$(cat "$TMP/events")" = "$FULL" ] || fail "missing checker: $(cat "$TMP/events")"
fsck_stub 1
rm "$TMP/errors_count"
run
[ "$(cat "$TMP/events")" = "$FULL" ] || fail "missing counter: $(cat "$TMP/events")"
echo 'ok: no checker or no error counter does not block a writable root'
echo 'root mount tests passed'
