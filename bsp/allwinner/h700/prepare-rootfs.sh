# Sourced by build-rootfs.sh after the target and artifact gates.
python3 "$HERE/tools/verify_harvest.py" "$WORK/stock-harvest.tar" \
  "$HERE/manifest/harvest.list" "$HERE/devices.json" "$TARGET"
python3 "$HERE/tools/kernel_gzip.py" prepare "$TARGET" "$WORK/boot-prefix.img" "$WORK/boot-gzip"

# Every released rootfs must contain the module built for this exact vendor kernel.
"$HERE/build-audio-module.sh" "$TARGET"
