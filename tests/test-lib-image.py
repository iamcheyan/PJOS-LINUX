#!/usr/bin/env python3
"""The /usr/lib squashfs image: kernel support and one agreed file name.

A kernel without the loop driver or LZ4 squashfs would boot with an empty
/usr/lib, so every target's kernel is asked. Needs prepared firmware in
work/<target>; optional target names.
"""
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lib_image

# The configuration reader, on a stand-in kernel.
def kernel(*options):
    return b"\0" * 64 + b"IKCFG_ST" + gzip.compress("\n".join(options).encode()) + b"IKCFG_ED" + b"\0" * 64

assert lib_image.missing(kernel(*lib_image.REQUIRED, "CONFIG_EXT4_FS=y")) == []
assert lib_image.missing(kernel("CONFIG_SQUASHFS=y", "CONFIG_BLK_DEV_LOOP=y", "CONFIG_SQUASHFS_ZLIB=y")) \
    == ["CONFIG_SQUASHFS_LZ4=y"]
# A module is not enough: nothing can load it before the libraries are there.
assert lib_image.missing(kernel("CONFIG_SQUASHFS=m", "CONFIG_BLK_DEV_LOOP=y", "CONFIG_SQUASHFS_LZ4=y")) \
    == ["CONFIG_SQUASHFS=y"]
assert lib_image.missing(kernel("# CONFIG_BLK_DEV_LOOP is not set")) == list(lib_image.REQUIRED)
try:
    lib_image.missing(b"\0" * 256)
except ValueError:
    pass
else:
    raise AssertionError("a kernel without a configuration passed")
print("configuration reader finds missing options")

# The build, startup and the device check name the same file, and
# the build uses the compressor the kernel check asks for.
build = (ROOT / "build-image.sh").read_text()
startup = (ROOT / "overlay/etc/init.d/rcS").read_text()
assert f"LIB_IMAGE={lib_image.IMAGE}\n" in build and "-comp lz4 -Xhc" in build
assert 'python3 "$HERE/tools/lib_image.py" check "$TARGET"' in build
assert f"usr_lib_image={lib_image.IMAGE}\n" in startup
assert '/bin/mount -t squashfs -o loop,ro,nodev,nosuid "$usr_lib_image" /usr/lib' in startup
assert "/usr/lib squashfs ro" in (ROOT / "validate-on-device.sh").read_text()
print("build, startup and device check agree on the image")

catalog = json.loads((ROOT / "manifest/kernel-gzip.json").read_text())
for target in sys.argv[1:] or catalog["profiles"]:
    absent = lib_image.missing(lib_image.target_kernel(target))
    assert not absent, (target, absent)
    print(f"{target}: kernel has the loop driver and LZ4 squashfs built in")
print("/usr/lib image tests passed")
