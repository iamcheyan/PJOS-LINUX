#!/usr/bin/env python3
"""Compare the boot inputs of every prepared H700 target. Reads files only.

Usage: survey.py WORK_DIR [target ...]
WORK_DIR holds <target>/boot-prefix.img as restored by fetch-prepared.sh.
Prints one JSON object per target and a summary of what differs.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import struct
import sys
import tarfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "tools"))
import fdt  # noqa: E402
from kernel_gzip import checksum, word  # noqa: E402

BOOT0_OFFSET = 8 * 1024
TOC1_OFFSET, TOC1_SIZE = 0x1004000, 0x140000
ENV_LBA, BOOT_LBA = 270336, 303104
KERNEL_SWITCHES = [b"usb_host_init_state", b"no-prescan-powerup", b"initcall_blacklist",
                   b"ehci_enable", b"Waiting for root device %s...", b"rcu_expedited",
                   b"rcu_normal_after_boot", b"errors_count", b"noauto_da_alloc", b"nobarrier"]


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:16]


def toc1_items(package: bytes) -> dict:
    items = {}
    for i in range(word(package, 32)):
        pos = 64 + 368 * i
        name = package[pos:pos + 64].split(b"\0")[0].decode()
        start, size = struct.unpack_from("<2I", package, pos + 64)
        items[name] = package[start:start + size]
    return items


def cpio_member(archive: bytes, wanted: str) -> bytes | None:
    pos = 0
    while archive[pos:pos + 6] == b"070701":
        fields = [int(archive[pos + 6 + 8 * i:pos + 14 + 8 * i], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        name = archive[pos + 110:pos + 110 + namesize - 1].decode()
        data = (pos + 110 + namesize + 3) & ~3
        if name == wanted:
            return archive[data:data + size]
        if name == "TRAILER!!!":
            break
        pos = (data + size + 3) & ~3
    return None


def u32(value: bytes | None):
    return None if value is None or len(value) != 4 else struct.unpack(">I", value)[0]


def survey(target: str, prefix: Path) -> dict:
    with prefix.open("rb") as handle:
        handle.seek(BOOT0_OFFSET)
        boot0 = handle.read(0x20000)
        handle.seek(TOC1_OFFSET)
        package = handle.read(TOC1_SIZE)
        handle.seek(ENV_LBA * 512)
        env = handle.read(0x20000)
        handle.seek(BOOT_LBA * 512)
        boot = handle.read(64 * 1024 * 1024)
    out = {"target": target}

    length = word(boot0, 0x10)
    out["boot0"] = {
        "magic": boot0[4:12].decode("latin1"), "length": length, "sha": sha(boot0[:length]),
        "checksum_ok": checksum(boot0[:length], 12) == word(boot0, 12),
        "debug_mode": boot0[0x34],
        # The first instruction jumps to 0x1300; everything from there on is
        # code and constant data, the part before it is per-board settings.
        "code_sha": sha(boot0[0x1300:length]),
    }

    items = toc1_items(package)
    dtb = items["dtb"]
    out["uboot_sha"] = sha(items["u-boot"])
    out["monitor_sha"] = sha(items["monitor"])
    out["dtb"] = {
        "sha": sha(dtb), "slack": len(dtb) - fdt.total_size(dtb),
        "uboot_debug_mode": u32(fdt.get(dtb, "platform", "debug_mode")),
        "boot_clock": u32(fdt.get(dtb, "target", "boot_clock")),
        "lcd_driver": (fdt.get(dtb, "lcd0@01c0c000", "lcd_driver_name") or b"").rstrip(b"\0").decode(),
        "pmic_bus_hz": u32(fdt.get(dtb, "twi@0x05003400", "clock-frequency")),
    }
    ports = {}
    for n in (1, 2, 3):
        gpio = fdt.get(dtb, f"usbc{n}@0", "usb_drv_vbus_gpio")
        status = lambda node: (fdt.get(dtb, node, "status") or b"?").rstrip(b"\0").decode()
        ehci = next((p for p, name, _o, _v in fdt.walk(dtb) if name == "compatible" and f"ehci{n}-controller" in p), None)
        ohci = next((p for p, name, _o, _v in fdt.walk(dtb) if name == "compatible" and f"ohci{n}-controller" in p), None)
        ports[f"usb{n}"] = {
            "power_pin": bool(gpio), "usbc": status(f"usbc{n}@0"),
            "ehci": status(ehci.split("/")[-1]) if ehci else "absent",
            "ohci": status(ohci.split("/")[-1]) if ohci else "absent",
        }
    out["usb_hosts"] = ports

    text = env[4:].split(b"\0\0")[0].split(b"\0")
    variables = dict(line.decode("latin1").split("=", 1) for line in text if b"=" in line)
    out["env"] = {"sha": sha(env), "loglevel": variables.get("loglevel"),
                  "bootdelay": variables.get("bootdelay"), "console": variables.get("console"),
                  "quiet_after_loglevel": " quiet" in variables.get("setargs_mmc", "")}

    ksize, rsize = word(boot, 8), word(boot, 16)
    kernel_raw = boot[2048:2048 + ksize]
    kernel = gzip.decompress(kernel_raw) if kernel_raw[:2] == b"\x1f\x8b" else kernel_raw
    roff = 2048 + ((ksize + 2047) & ~2047)
    ramdisk = boot[roff:roff + rsize]
    archive = zlib.decompress(ramdisk, 31)
    init = cpio_member(archive, "init")
    banner = kernel[kernel.index(b"Linux version "):][:120].split(b"\n")[0].decode("latin1")
    out["boot_image"] = {
        "header_cmdline": boot[0x40:0x240].rstrip(b"\0").decode("latin1"),
        "kernel_sha": sha(kernel), "kernel_bytes": len(kernel), "kernel": banner,
        "ramdisk_sha": sha(ramdisk), "ramdisk_bytes": rsize, "ramdisk_unpacked": len(archive),
        "initramfs_init_sha": sha(init) if init else None,
        "dtb_bytes": word(boot, 0x670),
    }
    out["kernel_has"] = {s.decode(): s in kernel for s in KERNEL_SWITCHES}
    return out


def main() -> None:
    work = Path(sys.argv[1])
    targets = sys.argv[2:] or sorted(p.parent.name for p in work.glob("*/boot-prefix.img"))
    rows = [survey(t, work / t / "boot-prefix.img") for t in targets]
    for row in rows:
        print(json.dumps(row))

    def flat(row, prefix=""):
        for key, value in row.items():
            if isinstance(value, dict):
                yield from flat(value, prefix + key + ".")
            else:
                yield prefix + key, value

    table = {}
    for row in rows:
        for key, value in flat(row):
            table.setdefault(key, {})[row["target"]] = value
    print("\n== identical on every target ==", file=sys.stderr)
    for key, values in table.items():
        if key != "target" and len({json.dumps(v) for v in values.values()}) == 1:
            print(f"  {key} = {next(iter(values.values()))}", file=sys.stderr)
    print("\n== differs ==", file=sys.stderr)
    for key, values in table.items():
        if key != "target" and len({json.dumps(v) for v in values.values()}) > 1:
            groups = {}
            for target, value in values.items():
                groups.setdefault(json.dumps(value), []).append(target)
            print(f"  {key}:", file=sys.stderr)
            for value, members in groups.items():
                print(f"     {value[:70]:70s} {' '.join(members)}", file=sys.stderr)


if __name__ == "__main__":
    main()
