#!/usr/bin/env python3
"""What the vendor kernel needs to mount the /usr/lib squashfs image.

build-image.sh stores /usr/lib as an LZ4 squashfs file inside the ext4 root and
rcS mounts it through a loop device. A kernel without one of these built in
would start with no libraries at all, so the build asks before it composes.

Usage: lib_image.py check TARGET
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import kernel_abi  # noqa: E402

IMAGE = "/usr/share/baseos/usr-lib.sqfs"
REQUIRED = ("CONFIG_BLK_DEV_LOOP=y", "CONFIG_SQUASHFS=y", "CONFIG_SQUASHFS_LZ4=y")


def kernel_config(kernel: bytes) -> set[str]:
    """The options of the configuration the kernel carries (CONFIG_IKCONFIG)."""
    start = kernel.find(b"IKCFG_ST")
    end = kernel.find(b"IKCFG_ED", start)
    if start < 0 or end < 0:
        raise ValueError("kernel carries no configuration")
    return set(gzip.decompress(kernel[start + 8:end]).decode().splitlines())


def missing(kernel: bytes) -> list[str]:
    config = kernel_config(kernel)
    return [option for option in REQUIRED if option not in config]


def target_kernel(target: str) -> bytes:
    work = ROOT / "work" / target
    layout = json.loads((work / "source.json").read_text(encoding="utf-8"))["layout"]
    boot = next(p for p in layout["partitions"] if p["number"] == 4)
    return kernel_abi.extract_kernel(work / "boot-prefix.img", boot["start_sector"])


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        raise SystemExit(__doc__.strip().splitlines()[-1])
    target = sys.argv[2]
    absent = missing(target_kernel(target))
    if absent:
        raise SystemExit(f"{target}: the kernel cannot mount the /usr/lib image, it lacks {' '.join(absent)}")
    print(f"{target}: kernel mounts LZ4 squashfs through a loop device")


if __name__ == "__main__":
    main()
