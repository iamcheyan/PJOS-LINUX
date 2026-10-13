#!/usr/bin/env python3
"""Run every target's vendor U-Boot against the faster boot image, under emulation.

The faster image is the shipped gzip boot image with two changes: the ramdisk is
a 512-byte empty cpio archive, and the Android header's command-line field holds
"loglevel=1". It has booted on one RG SP. This test asks whether the U-Boot of
every other supported model treats that image the same way.

For each target it loads the pinned, gzip-patched vendor U-Boot into Unicorn and
executes, instruction by instruction, the two commands the stock environment
uses to start Linux (`boot_normal`):

    sunxi_flash read 45000000 boot
    bootm 45000000

`bootm` runs from the command entry to the point where U-Boot would jump into
the kernel. Checked per target:

  same code  the build is the same instruction stream as the RG SP's wherever
             this test names an address, and uses the same strings there
  shipped    the image shipped today behaves as known: ramdisk copied whole,
             kernel unpacked, boot reaches the kernel jump
  1 card     the card is asked for exactly the bytes of the new image
  2 kernel   the boot reaches the kernel jump; the unpacked kernel is the original
  3 ramdisk  exactly the 512 ramdisk bytes are written to 0x42000000, and every
             record U-Boot keeps of the ramdisk (environment, device tree) spans
             512 bytes
  4 cmdline  the header command line ends up at the end of `bootargs`, in the
             environment and in the device tree handed to the kernel
  4 control  with an empty header field nothing but the separating space is added

Items 1 to 4 are checked with U-Boot's console at the stock level and switched
off. Printed as information only: what in this path depends on the ramdisk size,
and what a zero-length ramdisk would do differently.

What this is not: a whole-machine boot. Only U-Boot's own code runs, and only
from the two commands on. The pieces that touch hardware, or state built earlier
in the boot, are replaced by small models, listed in MODELLED below. The kernel
never runs here, so nothing is said about how each model's kernel takes the
empty ramdisk.

Needs Linux, the unicorn pinned in experiments/rgsp-kernel-gzip/requirements.txt
and prepared firmware in work/<target>/boot-prefix.img. The RG SP firmware must
be present even when other targets are named, because every build is compared
with it.

    python3 tests/test-fast-boot-emulation.py [target ...]

KERNEL_GZIP_TOOL names the kernel_gzip.py that derives the pinned U-Boot and
gzip image (default: tools/kernel_gzip.py in this checkout).
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import platform
import struct
import sys
import zlib
from pathlib import Path

import unicorn
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MODE_THUMB, Uc, UcError
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R9, UC_ARM_REG_SP

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments/h700-boot-speed"))
import fdt  # noqa: E402

REFERENCE = "rgsp"                      # the model the new image has booted on
# The exact image that booted on the RG SP (evidence/variants.json, noinitrd-quiet).
REFERENCE_IMAGE_SHA256 = "0e101c5348a540023b9b86811966605c31152194a94bbdab5f9133e1a0ec7f0b"
HEADER_CMDLINE = "loglevel=1"
EMPTY_CPIO = (b"070701" + b"%08X" * 13 % (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 11, 0)
              + b"TRAILER!!!\0").ljust(512, b"\0")
# What `bootargs` holds when the Android handler runs: the RG SP's recorded
# kernel command line before the header field is added, serial number blanked.
KNOWN_BOOTARGS = (
    "earlyprintk=sunxi-uart,0x05000000 initcall_debug=0 console=ttyS0,115200 loglevel=4"
    " root=/dev/mmcblk0p5 rootwait quiet splash init=/init partitions=special@mmcblk0p1:"
    "boot-resource@mmcblk0p2:env@mmcblk0p3:boot@mmcblk0p4:rootfs@mmcblk0p5:UDISK@mmcblk0p6:"
    "primary@mmcblk0p7 cma=64M snum=0000000000000000000 mac_addr= wifi_mac= bt_mac= selinux=0"
    " specialstr= gpt=1 androidboot.mode=normal androidboot.serialno=0000000000000000000"
    " androidboot.hardware=sun50iw9p1 boot_type=1 androidboot.boot_type=1"
    " androidboot.secure_os_exist=0 gpt=1 uboot_message=2018.05(06/24/2026-19:09:39)"
    " disp_reserve=1382400,0x7bf24800 bootreason=unknow lcd_type=old")
ENV_SECTOR, ENV_BYTES = 270336, 0x20000
STOCK_CONSOLE, QUIET_CONSOLE = 3, 0     # the device tree's debug_mode: stock, and switched off

# ---------------------------------------------------------------- memory map
RAM, RAM_BYTES = 0x40000000, 0x10000000
UBOOT = 0x4A000000          # link address of the vendor binary
IMAGE = 0x45000000          # where boot_normal loads the boot image
KERNEL = 0x40080000         # kernel load address in the image header
RAMDISK = 0x42000000        # ramdisk load address in the image header
FDT = 0x44000000            # U-Boot's device tree in this model
HEAP = 0x48000000           # model heap for the binary's malloc calls
STRINGS = 0x4E000000        # command arguments and environment values
GD = 0x4F000000             # U-Boot global data (r9)
BOARD = GD + 0x1000         # board info: memory bank start and size
CARD = GD + 0x8000          # fake block device handed to sunxi_flash
CARD_READ = GD + 0xA000     # address of its read routine (model)
RETURN = 0x4FFF0000         # return address of a top-level call
STACK = 0x4FFFF000
GUARD = 32
WATCHED = 0x10000           # every write this close to the ramdisk address is noted

# ---------------------------------------------------------------- vendor code
# Offsets of routines in the vendor U-Boot, found in the RG SP build from the
# strings they use and from how they call each other. The binaries carry no
# symbols; names follow mainline U-Boot 2018.05 where the code matches it.
# Nothing here is taken on trust for another build: see same_code and
# STRING_SITES.
SUNXI_FLASH = 0xC1E8                # do_sunxi_flash(cmdtp, flag, argc, argv)
BOOTM = 0x7E70                      # do_bootm(cmdtp, flag, argc, argv)
UPDATE_BOOTARGS = 0x5734            # vendor: rebuilds bootargs before the states run
ANDROID_GET_KERNEL = 0x12404        # android_image_get_kernel: appends the header field
ANDROID_GET_RAMDISK = 0x12600       # android_image_get_ramdisk
ANDROID_GET_RAMDISK_EMPTY = 0x12618  # ... its "size is zero" exit
ENV_GET, ENV_SET = 0xE8F8, 0xE620
MALLOC, FREE = 0x11728, 0x115CC
MEMMOVE_WD = 0x12104                # memmove_wd(to, from, len, chunk)
FDT_INITRD = 0xFDA4                 # fdt_initrd(fdt, start, end)
FDT_CHOSEN = 0xFED8                 # fdt_chosen(fdt): bootargs -> /chosen
BOOT_JUMP_LINUX = 0x1470            # boot_jump_linux(images, flag): the kernel jump
PUTS, PR_MSG = 0x110FA, 0x111E8     # console text; vendor leveled message
FLUSH_CACHE, IRQ_OFF, IRQ_ON = 0x1814, 0x1600, 0x15E4
BLK_GET_DEV = 0x17734               # block device by type name
PART_GET_INFO = 0x466C              # partition geometry by name
BOOTM_RAMDISK_CALL = 0x7F16         # do_bootm's call of fdt_initrd for the ramdisk
HANG_CALL = 0x1418                  # boot_prep_linux's call of hang(), which lies beyond the limit
IMAGES_LITERAL = 0x7F96             # do_bootm: ldr r3, =images
WORKING_FDT_LITERALS = (0x7F10, 0x8680)   # do_bootm, set_working_fdt_addr: =working_fdt
SELECTOR = 0xF698                   # the gzip patch: os.comp selector for Android images
# All offsets above lie below this. Up to here every build must be the same
# instruction stream as the RG SP's.
SAME_CODE_LIMIT = 0x26000

# Replaced by a model instead of running the vendor code, and why.
MODELLED = """\
  env_get, env_set        environment kept in a Python dict, started from the env
                          partition (the hash table is set up by earlier boot code
                          that does not run here); env_set_hex and every string
                          operation run as vendor code
  malloc, free            bump allocator with guard bytes after every block
  update_bootargs         vendor step that runs before the Android handler and writes
                          the final bootargs; here it stores KNOWN_BOOTARGS
  block device            sunxi_flash gets a fake card serving the boot partition;
                          device lookup, partition lookup and sector read are models
  puts, pr_msg            text is collected instead of going to the serial port;
                          printf formats it as vendor code
  flush_cache, interrupts no-ops (processor state only)
  boot_jump_linux         the jump into the kernel: recorded, then emulation stops
  hang                    U-Boot's endless loop after a fatal error: reported as a failure
  starting state          global data holds only the fields this path reads: board
                          memory bank, device-tree pointer and size, console level,
                          secure-boot flag 0; working_fdt points at the bootloader
                          package's device tree as packed (on a device, startup code
                          at 0xef5c, not run here, first adds 4096 spare bytes)"""

# How the ramdisk size is used on this path, read from the disassembly. The "5 info"
# lines show, per target, that only these routines read the size field.
SIZE_NOTES = """  android_image_get_end      rounds every part up to the 2048-byte page to get the image
                             length, for the card read and for bootm; 512 bytes take one
                             page, 0 bytes none
  android_image_get_ramdisk  size 0: returns -1 with address and length 0. Otherwise the
                             address after the kernel's pages and the size as it is; no
                             minimum, no rounding
  do_bootm                   ignores that return value: always calls memmove_wd(0x42000000,
                             address, length) and sets initrd_start and initrd_end; calls
                             fdt_initrd(tree, 0x42000000, 0x42000000 + size) only if the
                             size is not 0
  fdt_initrd                 returns at once when start equals end"""

# The string each of these instructions loads, in every build.
STRING_SITES = {
    "do_sunxi_flash": [(0xC202, "boot0"), (0xC222, "read"), (0xC22C, "read"), (0xC25A, "boot_from_partion"),
                       (0xC262, "sunxi_flash"), (0xC2A6, "ANDROID!")],
    "do_bootm": [(0x7E7E, "boot_from_partion"), (0x7ED4, "initrd_start"), (0x7EDE, "initrd_end"),
                 (0x7F6A, "Trying to execute a command out of order\n")],
    "update_bootargs": [(0x5754, "verifiedbootstate"), (0x575C, "bootargs"), (0x5966, " androidboot.mode=normal"),
                        (0x5936, " lcd_type=%s"), (0x5948, "bootargs")],
    "android_image_get_kernel": [(0x1242A, "Android's image name: %s\n"), (0x12440, "bootargs"),
                                 (0x1245A, "Error: malloc in android_image_get_kernel failed!\n"),
                                 (0x12478, " "), (0x12492, "bootargs")],
    "env_set": [(0xE622, "setenv")],
    "env_set_hex": [(0xE67E, "%lx")],
    "fdt_initrd": [(0xFDBE, "chosen"), (0xFE4C, "linux,initrd-start"), (0xFE7A, "linux,initrd-start"),
                   (0xFE94, "linux,initrd-end")],
    "fdt_chosen": [(0xFEF2, "chosen"), (0xFF00, "bootargs"), (0xFF1E, "bootargs")],
    "bootm_find_other": [(0xF35C, "0xffffffff"), (0xF35E, "fdt_high")],
    "set_working_fdt_addr": [(0x8686, "fdtaddr")],
    "boot_prep_linux": [(0x1400, "bootargs"), (0x1412, "FDT creation failed! hanging...")],
    "boot_jump_linux": [(0x147E, "machid"), (0x14BC, "Starting kernel ...%s\n\n")],
}
# Used to name the code that reads a header field.
ROUTINES = {
    "do_sunxi_flash": (0xC1E8, 0xC304), "do_bootm": (0x7E70, 0x7FA4),
    "do_bootm_states": (0xF43C, 0xF982), "android_image_get_kernel": (ANDROID_GET_KERNEL, 0x124DA),
    "android_image_get_end": (0x12500, 0x125C0), "android_image_get_kload": (0x125C0, 0x125FC),
    "android_image_get_ramdisk": (ANDROID_GET_RAMDISK, 0x12666),
}


class Failed(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Failed(message)


def word(blob: bytes, at: int) -> int:
    return struct.unpack_from("<I", blob, at)[0]


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------- the images
def page_align(size: int) -> int:
    return (size + 2047) & ~2047


def image_id(parts: list[bytes]) -> bytes:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part)
        digest.update(struct.pack("<I", len(part)))
    return digest.digest() + bytes(12)


def split_boot(boot: bytes):
    """Header and the five parts (kernel, ramdisk, second, recovery dtbo, dtb). As lab.py."""
    require(boot[:8] == b"ANDROID!" and word(boot, 36) == 2048 and word(boot, 40) == 2, "unexpected boot image")
    parts, pos = [], 2048
    for at in (8, 16, 24, 0x660, 0x670):
        parts.append(boot[pos:pos + word(boot, at)])
        pos += page_align(word(boot, at))
    require(boot[0x240:0x260] == image_id(parts), "boot image ID does not reproduce")
    return bytearray(boot[:2048]), parts


def join_boot(header: bytearray, parts: list[bytes]) -> bytes:
    for at, part in zip((8, 16, 24, 0x660, 0x670), parts):
        struct.pack_into("<I", header, at, len(part))
    header[0x240:0x260] = image_id(parts)
    return bytes(header) + b"".join(part + bytes(page_align(len(part)) - len(part)) for part in parts)


def variant(boot: bytes, ramdisk: bytes, cmdline: str) -> bytes:
    """The shipped image with another ramdisk and header command line."""
    header, parts = split_boot(boot)
    parts[1] = ramdisk
    header[0x40:0x240] = cmdline.encode().ljust(512, b"\0")
    image = join_boot(header, parts)
    require(split_boot(image)[1][0] == split_boot(boot)[1][0], "kernel bytes changed")
    return image


def ramdisk_of(image: bytes) -> tuple[int, bytes]:
    """Offset of the ramdisk in the image, and its bytes."""
    return 2048 + page_align(word(image, 8)), split_boot(image)[1][1]


def header_cmdline(image: bytes) -> str:
    return image[0x40:0x240].split(b"\0")[0].decode()


# ---------------------------------------------------------------- static checks
def branch_target(code: bytes, at: int) -> int | None:
    """Target offset of a Thumb-2 BL, BLX or B.W at `at`, or None for anything else."""
    first, second = struct.unpack_from("<HH", code, at)
    if first & 0xF800 != 0xF000 or not (second & 0xC000 == 0xC000 or second & 0xD000 == 0x9000):
        return None
    sign = (first >> 10) & 1
    i1, i2 = 1 - (((second >> 13) & 1) ^ sign), 1 - (((second >> 11) & 1) ^ sign)
    offset = (sign << 24) | (i1 << 23) | (i2 << 22) | ((first & 0x3FF) << 12) | ((second & 0x7FF) << 1)
    if sign:
        offset -= 1 << 25
    return at + 4 + offset


def literal(code: bytes, at: int) -> int:
    """Value loaded by the 16-bit `ldr rX, [pc, #n]` at `at`."""
    instruction = struct.unpack_from("<H", code, at)[0]
    require(instruction & 0xF800 == 0x4800, f"no literal load at {at:#x}")
    return word(code, ((at + 4) & ~3) + (instruction & 0xFF) * 4)


def same_strings(code: bytes) -> int:
    count = 0
    for name, sites in STRING_SITES.items():
        for at, expected in sites:
            start = literal(code, at) - UBOOT
            require(0 <= start < len(code), f"{name}: literal at {at:#x} is not in the binary")
            found = code[start:code.index(b"\0", start)].decode("latin1")
            require(found == expected, f"{name}: instruction at {at:#x} loads {found!r}, not {expected!r}")
            count += 1
    return count


def same_code(reference: bytes, code: bytes) -> dict:
    """Require the same instruction stream as the reference below SAME_CODE_LIMIT.

    Two builds may differ there only where the linker placed something else
    beyond the limit: in the target of a call or jump that leaves the region,
    and in address constants that point outside it. Each outside routine of the
    reference must correspond to exactly one routine of the other build.
    """
    outside, constants, at = {}, 0, 16
    while at < SAME_CODE_LIMIT:
        if reference[at:at + 2] == code[at:at + 2]:
            at += 2
            continue
        for start in (at, at - 2):
            mine, theirs = branch_target(reference, start), branch_target(code, start)
            if mine is not None and theirs is not None and reference[start:start + 4] != code[start:start + 4]:
                require(mine >= SAME_CODE_LIMIT and theirs >= SAME_CODE_LIMIT,
                        f"call at {start:#x} into the compared region differs")
                require(outside.setdefault(mine, theirs) == theirs,
                        f"routine {mine:#x} of the reference has two counterparts")
                at = start + 4
                break
        else:
            aligned = at & ~3
            mine, theirs = word(reference, aligned), word(code, aligned)
            low, high = UBOOT + SAME_CODE_LIMIT, UBOOT + 0x200000
            require(low <= mine < high and low <= theirs < high, f"code differs at {at:#x}: "
                    f"{reference[aligned:aligned + 4].hex()} / {code[aligned:aligned + 4].hex()}")
            constants += 1
            at = aligned + 4
    require(len(set(outside.values())) == len(outside), "two reference routines share a counterpart")
    return {"outside": len(outside), "constants": constants}


# ---------------------------------------------------------------- emulator
class Machine:
    def __init__(self, code: bytes, tree: bytes, environment: dict[str, str], console: int):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self.uc.mem_map(RAM, RAM_BYTES)
        self.uc.mem_write(UBOOT, code)
        self.uc.reg_write(UC_ARM_REG_R9, GD)
        self.put32(GD, BOARD)
        self.uc.mem_write(BOARD + 0x50, struct.pack("<QQ", RAM, 0x40000000))
        self.uc.mem_write(FDT, tree)
        self.put32(GD + 0x5C, FDT)
        self.put32(GD + 0x68, fdt.total_size(tree))
        self.put32(GD + 0x10C, console)
        working = {literal(code, at) for at in WORKING_FDT_LITERALS}
        require(len(working) == 1, "working_fdt is not one variable")
        self.put32(working.pop(), FDT)
        self.images = literal(code, IMAGES_LITERAL)
        self.env = dict(environment)
        self.env_reads: list[str] = []
        self.env_writes: list[tuple[str, str, int]] = []
        self.blocks: list[tuple[int, int, int]] = []
        self.heap = HEAP
        self.strings = STRINGS
        self.order: list[str] = []
        self.calls: dict[str, list] = {}
        self.console: list[str] = []
        self.messages: list[str] = []
        self.readers: dict[str, set[int]] = {}
        self.written: dict[str, list[int]] = {}
        self.jump, self.hung = None, False
        hang = branch_target(code, HANG_CALL)
        require(hang is not None and hang >= SAME_CODE_LIMIT, "hang() not found")
        self.replace(hang, self.hang)
        self.replace(ENV_GET, self.env_get)
        self.replace(ENV_SET, self.env_set)
        self.replace(MALLOC, self.malloc)
        self.replace(FREE, lambda: 0)
        self.replace(PUTS, lambda: self.console.append(self.text(self.arg(0))))
        self.replace(PR_MSG, lambda: self.messages.append(self.text(self.arg(1))))
        for at in (FLUSH_CACHE, IRQ_OFF, IRQ_ON):
            self.replace(at, lambda: 0)
        self.replace(BOOT_JUMP_LINUX, self.kernel_jump)

    # -- registers and memory
    def arg(self, n: int) -> int:
        return self.uc.reg_read(UC_ARM_REG_R0 + n)

    def caller(self) -> int:
        return (self.uc.reg_read(UC_ARM_REG_LR) & ~1) - UBOOT

    def get32(self, address: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def put32(self, address: int, value: int) -> None:
        self.uc.mem_write(address, struct.pack("<I", value))

    def read(self, address: int, size: int) -> bytes:
        return bytes(self.uc.mem_read(address, size))

    def text(self, address: int) -> str:
        if not RAM <= address < RAM + RAM_BYTES - 4096:
            return ""
        return self.read(address, 4096).split(b"\0")[0].decode("latin1")

    def keep(self, text: str) -> int:
        address = self.strings
        self.uc.mem_write(address, text.encode("latin1") + b"\0")
        self.strings += (len(text) + 16) & ~15
        return address

    # -- hooks
    def replace(self, at: int, model) -> None:
        """Run `model` instead of the routine at `at` and return its value."""
        def hook(uc, _address, _size, _data):
            result = model()
            uc.reg_write(UC_ARM_REG_R0, (result or 0) & 0xFFFFFFFF)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        address = at if at >= RAM else UBOOT + at
        self.uc.hook_add(UC_HOOK_CODE, hook, begin=address, end=address)

    def record(self, name: str, at: int, arguments: int = 0) -> None:
        """Note each time execution reaches `at`; the vendor code runs unchanged."""
        self.calls[name] = []

        def hook(*_):
            self.order.append(name)
            self.calls[name].append(tuple(self.arg(n) for n in range(arguments)) + (self.caller(),))
        self.uc.hook_add(UC_HOOK_CODE, hook, begin=UBOOT + at, end=UBOOT + at)

    def watch_reads(self, name: str, start: int, size: int) -> None:
        """Remember which vendor instructions read the bytes at start..start+size."""
        self.readers[name] = set()
        self.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, *_: self.readers[name].add(
            uc.reg_read(UC_ARM_REG_PC) - UBOOT), begin=start, end=start + size - 1)

    def watch_writes(self, name: str, start: int, size: int) -> None:
        """Remember the lowest and highest address written inside start..start+size."""
        self.written[name] = []

        def hook(_uc, _access, address, length, _value, _data):
            span = self.written[name]
            span[:] = [min(span[0], address), max(span[1], address + length)] if span else [address, address + length]
        self.uc.hook_add(UC_HOOK_MEM_WRITE, hook, begin=start, end=start + size - 1)

    # -- models
    def env_get(self) -> int:
        name = self.text(self.arg(0))
        self.env_reads.append(name)
        return 0 if name not in self.env else self.keep(self.env[name])

    def env_set(self) -> int:
        name, value = self.text(self.arg(0)), self.text(self.arg(1)) if self.arg(1) else ""
        self.env_writes.append((name, value, self.caller()))
        if value:
            self.env[name] = value
        else:
            self.env.pop(name, None)
        return 0

    def malloc(self) -> int:
        address, size = self.heap, self.arg(0)
        self.heap = ((address + size + 15) & ~15) + GUARD
        self.uc.mem_write(address + size, b"\xA5" * (self.heap - address - size))
        self.blocks.append((address, size, self.heap))
        return address

    def heap_intact(self) -> bool:
        return all(set(self.read(address + size, end - address - size)) == {0xA5}
                   for address, size, end in self.blocks)

    def hang(self) -> int:
        self.hung = True
        self.uc.emu_stop()
        return 0

    def kernel_jump(self) -> int:
        images, flag = self.arg(0), self.arg(1)
        self.jump = {"flag": flag, "entry": self.get32(images + 0x60), "fdt": self.get32(images + 0x6C)}
        self.uc.emu_stop()
        return 0

    # -- running vendor code
    def call(self, at: int, arguments: list[int]) -> int | None:
        """Call the routine at `at`. None means it stopped at the kernel jump."""
        self.uc.reg_write(UC_ARM_REG_SP, STACK)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
        for n, value in enumerate(arguments):
            self.uc.reg_write(UC_ARM_REG_R0 + n, value)
        self.jump = None
        try:
            self.uc.emu_start((UBOOT + at) | 1, RETURN, timeout=120 * 1000000)
        except UcError as error:
            raise Failed(f"emulation stopped: {error} at pc {self.uc.reg_read(UC_ARM_REG_PC):#x}, "
                         f"lr {self.uc.reg_read(UC_ARM_REG_LR):#x}; console {self.console[-3:]}")
        require(not self.hung, f"U-Boot gave up and hung; console {self.console[-3:]}")
        if self.jump is not None:
            return None
        require(self.uc.reg_read(UC_ARM_REG_PC) == RETURN,
                f"did not return: pc {self.uc.reg_read(UC_ARM_REG_PC):#x}; console {self.console[-3:]}")
        return self.arg(0)

    def command(self, at: int, *words: str) -> int | None:
        argv = self.strings
        self.strings += 64
        self.uc.mem_write(argv, struct.pack(f"<{len(words) + 1}I", *[self.keep(w) for w in words], 0))
        return self.call(at, [0, 0, len(words), argv])


# ---------------------------------------------------------------- one boot
class Target:
    def __init__(self, name: str, derived: dict, environment: dict[str, str]):
        self.name, self.environment = name, environment
        # The build's tool ships the fast image as "boot" and keeps the image of
        # the previous release as "gzip_boot". An older tool, named through
        # KERNEL_GZIP_TOOL, only knows that previous image.
        self.code, self.kernel = derived["uboot"], derived["kernel"]
        self.shipped = derived.get("gzip_boot", derived["boot"])
        self.built = derived["boot"] if "gzip_boot" in derived else None
        profile = derived["profile"]
        self.partition = (profile["boot_partition_start"], profile["boot_partition_sectors"])
        package = derived["package"]
        for i in range(word(package, 32)):
            at = 64 + 368 * i
            if package[at:at + 64].split(b"\0")[0] == b"dtb":
                start = word(package, at + 64)
                self.tree = package[start:start + fdt.total_size(package[start:start + 8])]
                break
        else:
            raise Failed("no device tree in the bootloader package")


def boot(target: Target, image: bytes, console: int = STOCK_CONSOLE) -> dict:
    """Run `sunxi_flash read 45000000 boot; bootm 45000000` and report what happened."""
    m = Machine(target.code, target.tree, target.environment, console)
    start, sectors = target.partition
    card = image + b"\xFF" * (sectors * 512 - len(image))
    reads = []

    def device() -> int:
        require(m.text(m.arg(0)) == "sunxi_flash", "unexpected block device")
        return CARD

    def partition() -> int:
        require(m.text(m.arg(1)) == "boot", "unexpected partition")
        m.uc.mem_write(m.arg(2), struct.pack("<4I", start, sectors, 512, 0))
        return 0

    def read_sectors() -> int:
        sector, count, to = m.arg(1), m.arg(2), m.arg(3)
        offset = (sector - start) * 512
        require(0 <= offset and offset + count * 512 <= len(card), f"read outside the partition: {sector} +{count}")
        reads.append((offset, count * 512, to))
        m.uc.mem_write(to, card[offset:offset + count * 512])
        return count

    def update_bootargs() -> int:
        m.order.append("update_bootargs")
        m.env["bootargs"] = KNOWN_BOOTARGS
        return 0

    m.replace(BLK_GET_DEV, device)
    m.replace(PART_GET_INFO, partition)
    m.put32(CARD + 0x78, CARD_READ | 1)
    m.replace(CARD_READ, read_sectors)
    m.replace(UPDATE_BOOTARGS, update_bootargs)
    m.record("android_image_get_kernel", ANDROID_GET_KERNEL, 1)
    m.record("android_image_get_ramdisk", ANDROID_GET_RAMDISK, 1)
    m.record("ramdisk_size_is_zero", ANDROID_GET_RAMDISK_EMPTY)
    m.record("memmove_wd", MEMMOVE_WD, 3)
    m.record("fdt_initrd", FDT_INITRD, 3)
    m.record("fdt_chosen", FDT_CHOSEN, 1)
    m.record("ramdisk_into_tree", BOOTM_RAMDISK_CALL)
    m.watch_reads("ramdisk_size", IMAGE + 16, 4)
    m.watch_reads("header_cmdline", IMAGE + 0x40, 512)
    m.watch_writes("ramdisk", RAMDISK - WATCHED, 2 * WATCHED)

    out = {"machine": m, "image": image, "reads": reads}
    out["flash_result"] = m.command(SUNXI_FLASH, "sunxi_flash", "read", f"{IMAGE:x}", "boot")
    out["loaded"] = m.read(IMAGE, len(image)) == image and m.read(IMAGE + len(image), 512) == bytes(512)
    out["bootm_result"] = m.command(BOOTM, "bootm", f"{IMAGE:x}")
    out["jump"] = m.jump
    out["tree"] = m.read(FDT, fdt.total_size(m.read(FDT, 8)))
    out["images"] = {name: m.get32(m.images + at) for name, at in
                     (("rd_start", 0x64), ("rd_end", 0x68), ("initrd_start", 0x74), ("initrd_end", 0x78))}
    out["compression"] = m.read(m.images + 0x5C, 1)[0]
    return out


def reserved(tree: bytes) -> list[tuple[int, int]]:
    at, entries = struct.unpack_from(">I", tree, 16)[0], []
    while True:
        address, size = struct.unpack_from(">QQ", tree, at)
        if not address and not size:
            return entries
        entries.append((address, size))
        at += 16


def chosen(tree: bytes, name: str) -> bytes | None:
    return fdt.get(tree, "chosen", name)


def initrd_span(tree: bytes) -> tuple[int, int]:
    return tuple(int.from_bytes(chosen(tree, name), "big") for name in ("linux,initrd-start", "linux,initrd-end"))


def spare(tree: bytes) -> int:
    total, structure, strings = struct.unpack_from(">3I", tree, 4)
    strings_size, structure_size = struct.unpack_from(">2I", tree, 32)
    return total - max(strings + strings_size, structure + structure_size)


def readers(machine: Machine, name: str) -> str:
    """Name the routines whose instructions read a watched header field."""
    names = set()
    for pc in machine.readers[name]:
        names.add(next((routine for routine, (start, end) in ROUTINES.items() if start <= pc < end),
                       f"unnamed code at {pc:#x}" if pc < SAME_CODE_LIMIT else "string routines"))
    return ", ".join(sorted(names)) or "nothing"


def ramdisk_copies(run: dict) -> list[tuple[int, int, int]]:
    """What do_bootm passed to memmove_wd: the ramdisk copy."""
    first, last = ROUTINES["do_bootm"]
    return [(to, source, size) for to, source, size, caller in run["machine"].calls["memmove_wd"]
            if first <= caller < last]


# What each check requires of one emulated boot. They raise Failed with the reason.
def expect_card(run: dict) -> str:
    image, reads, at = run["image"], run["reads"], 0
    require(run["flash_result"] == 0, f"sunxi_flash returned {run['flash_result']}")
    for offset, size, to in reads:
        require(offset == at and to == IMAGE + at, f"reads are not consecutive: {reads}")
        at += size
    require(at == len(image), f"{at} bytes requested, image is {len(image)}")
    require(run["loaded"], "memory does not hold exactly the image")
    require(run["machine"].env.get("boot_from_partion") == "boot", "partition name not recorded")
    return f"{at} bytes in {len(reads)} reads ({' + '.join(str(size // 512) for _, size, _ in reads)} sectors)"


def expect_kernel(run: dict, kernel: bytes) -> str:
    m, jump = run["machine"], run["jump"]
    require(run["bootm_result"] is None and jump is not None,
            f"bootm returned {run['bootm_result']} without reaching the kernel jump; console {m.console[-4:]}")
    require(jump == {"flag": 0x400, "entry": KERNEL, "fdt": FDT}, f"unexpected jump {jump}")
    require(run["compression"] == 1, "kernel not marked gzip")
    require(len(m.calls["android_image_get_kernel"]) == 1, "Android handler did not run exactly once")
    loaded = m.read(KERNEL, len(kernel))
    require(loaded == kernel, f"kernel differs: {sha(loaded)[:16]}")
    require(m.read(KERNEL + len(kernel), 4096) == bytes(4096), "bytes were written after the kernel")
    require(m.heap_intact(), "a heap block was overrun")
    return f"reached the kernel jump; {len(kernel)} bytes at {KERNEL:#x} are the original kernel"


def expect_ramdisk(run: dict, before: bytes) -> str:
    """The ramdisk of the image is at 0x42000000 and recorded with its exact size."""
    m = run["machine"]
    at, ramdisk = ramdisk_of(run["image"])
    size, source = len(ramdisk), IMAGE + at
    require(size > 0, "image has no ramdisk")
    require(ramdisk_copies(run) == [(RAMDISK, source, size)], f"ramdisk copies: {ramdisk_copies(run)}")
    require(len(m.calls["memmove_wd"]) == 1, f"other copies: {m.calls['memmove_wd']}")
    require(m.written["ramdisk"] == [RAMDISK, min(RAMDISK + size, RAMDISK + WATCHED)],
            f"bytes written around {RAMDISK:#x}: {[hex(a) for a in m.written['ramdisk']]}")
    require(m.read(RAMDISK, size) == ramdisk, "0x42000000 does not hold the ramdisk")
    require(m.read(RAMDISK + size, WATCHED) == bytes(WATCHED), "bytes follow the ramdisk")
    first, last = int(m.env["initrd_start"], 16), int(m.env["initrd_end"], 16)
    require((first, last) == (source, source + size), f"environment: {first:#x}..{last:#x}")
    calls = [call[:3] for call in m.calls["fdt_initrd"]]
    require(calls == [(FDT, RAMDISK, RAMDISK + size), (FDT, 0, 0)], f"fdt_initrd calls: {calls}")
    require(len(m.calls["ramdisk_into_tree"]) == 1 and not m.calls["ramdisk_size_is_zero"], "zero-size path taken")
    require(not any(run["images"].values()), f"bootm ramdisk fields set: {run['images']}")
    span = initrd_span(run["tree"])
    require(span == (RAMDISK, RAMDISK + size), f"device tree: {span}")
    require(set(reserved(run["tree"])) - set(reserved(before)) == {(RAMDISK, size)},
            f"reserved memory: {reserved(run['tree'])}")
    return (f"{size} bytes copied once, {source:#x} -> {RAMDISK:#x}, nothing else written there; environment"
            f" initrd_start..initrd_end {first:#x}..{last:#x} ({last - first}); device tree linux,initrd-start..end"
            f" {span[0]:#x}..{span[1]:#x} ({span[1] - span[0]}), {size} bytes reserved there")


def expect_bootargs(run: dict, expected: str) -> str:
    m = run["machine"]
    first, last = ROUTINES["android_image_get_kernel"]
    writes = [(value, caller) for name, value, caller in m.env_writes if name == "bootargs"]
    require(len(writes) == 1 and first <= writes[0][1] < last,
            f"bootargs writes: {[(hex(caller), value[-24:]) for value, caller in writes]}")
    steps = [name for name in m.order if name in ("update_bootargs", "android_image_get_kernel", "fdt_chosen")]
    require(steps == ["update_bootargs", "android_image_get_kernel", "fdt_chosen"], f"order of steps: {steps}")
    require(m.env["bootargs"] == expected, f"bootargs ends {m.env['bootargs'][-40:]!r}")
    require(run["jump"] is not None, "boot did not reach the kernel jump")
    in_tree = chosen(run["tree"], "bootargs")
    require(in_tree == expected.encode() + b"\0", f"device tree bootargs ends {(in_tree or b'')[-40:]!r}")
    return f"bootargs ends {expected[-24:]!r}"


# ---------------------------------------------------------------- one target
def check_target(target: Target, reference_code: bytes, say) -> dict:
    results: dict[str, str] = {}
    name, code, shipped, kernel, tree = target.name, target.code, target.shipped, target.kernel, target.tree
    runs: dict[str, dict] = {}

    def check(item: str, body) -> None:
        try:
            detail, results[item] = body(), "PASS"
        except (Failed, KeyError, ValueError, TypeError, IndexError, struct.error) as error:
            detail, results[item] = f"{type(error).__name__}: {error}", "FAIL"
        say(f"{name}  {item:<10} {results[item]}  {detail}")

    def run_of(image: bytes, console: int = STOCK_CONSOLE) -> dict:
        key = sha(image) + str(console)
        if key not in runs:
            try:
                runs[key] = boot(target, image, console)
            except Failed as error:
                runs[key] = {"failed": str(error)}
        require("failed" not in runs[key], f"emulated boot broke off: {runs[key].get('failed')}")
        return runs[key]

    fast = variant(shipped, EMPTY_CPIO, HEADER_CMDLINE)
    say(f"{name}  u-boot {sha(code)[:16]}, shipped image {len(shipped)} bytes {sha(shipped)[:16]},"
        f" fast image {len(fast)} bytes {sha(fast)[:16]}, kernel {len(kernel)} bytes {sha(kernel)[:16]}")
    require(gzip.decompress(split_boot(fast)[1][0]) == kernel, "fast image does not hold the original kernel")
    if target.built is not None:
        require(fast == target.built, "the image emulated here is not the image the build ships")
        say(f"{name}  the fast image emulated here is byte-identical to the one the build ships")
    if name == REFERENCE:
        require(sha(fast) == REFERENCE_IMAGE_SHA256, "the RG SP image built here is not the one that booted")
        say(f"{name}  the fast image built here is byte-identical to the one that booted on the device")

    def static() -> str:
        require(code[SELECTOR:SELECTOR + 4] == bytes.fromhex("40f20123"), "gzip selector is not patched")
        strings, same = same_strings(code), same_code(reference_code, code)
        if name == REFERENCE:
            return f"this is the reference build; {strings} string uses as expected"
        return (f"same instructions as the RG SP below {SAME_CODE_LIMIT:#x}: differs only in the targets of"
                f" calls to {same['outside']} routines placed beyond it and in {same['constants']} address"
                f" constants pointing beyond it; {strings} string uses as expected")
    check("same code", static)
    if results["same code"] != "PASS":
        for item in ITEMS[1:]:
            results[item] = "FAIL"
        say(f"{name}  nothing else was run: this build is not the code the offsets describe")
        return results

    def shipped_today() -> str:
        run = run_of(shipped)
        return "; ".join((expect_card(run), expect_kernel(run, kernel), expect_ramdisk(run, tree),
                          expect_bootargs(run, f"{KNOWN_BOOTARGS} {header_cmdline(shipped)}")))
    check("shipped", shipped_today)

    def fast_boot(expect) -> str:
        """The new image must pass with the console at the stock level and switched off."""
        details = {expect(run_of(fast, console)) for console in (STOCK_CONSOLE, QUIET_CONSOLE)}
        require(len(details) == 1, f"console on and off differ: {sorted(details)}")
        return details.pop()
    check("1 card", lambda: fast_boot(expect_card))
    check("2 kernel", lambda: fast_boot(lambda run: expect_kernel(run, kernel)))

    def ramdisk(run: dict) -> str:
        require(ramdisk_of(fast)[1] == EMPTY_CPIO and len(EMPTY_CPIO) == 512, "not the empty archive")
        return expect_ramdisk(run, tree)
    check("3 ramdisk", lambda: fast_boot(ramdisk))

    def cmdline(run: dict) -> str:
        expect_bootargs(run, f"{KNOWN_BOOTARGS} {HEADER_CMDLINE}")
        return (f"bootargs = known string + ' {HEADER_CMDLINE}' in the environment and in the device tree's"
                f" /chosen; written once, by the Android handler, after update_bootargs; {spare(run['tree'])}"
                f" of {spare(tree)} spare device-tree bytes left")
    check("4 cmdline", lambda: fast_boot(cmdline))

    def control() -> str:
        run = run_of(variant(shipped, EMPTY_CPIO, ""))
        expect_bootargs(run, KNOWN_BOOTARGS + " ")
        expect_kernel(run, kernel)
        read = {pc - ANDROID_GET_KERNEL for pc in run["machine"].readers["header_cmdline"]}
        require(read == {0x2C, 0x7C}, f"header field read at {sorted(map(hex, read))}")
        return ("same image with the header field empty: bootargs = known string + ' '. The handler always"
                f" adds the separating space and only looks at the field's first byte; no '{HEADER_CMDLINE}'")
    check("4 control", control)

    def information() -> None:
        run = run_of(fast)
        m = run["machine"]
        say(f"{name}  5 info     ramdisk size field is read by: {readers(m, 'ramdisk_size')}")
        say(f"{name}  5 info     header command line is read by: {readers(m, 'header_cmdline')}")
        say(f"{name}  5 info     environment read: {', '.join(dict.fromkeys(m.env_reads))}; written: "
            + ", ".join(f"{n}={v if len(v) < 20 else '...' + v[-12:]}" for n, v, _ in m.env_writes))
        say(f"{name}  5 info     console text: {m.console}; allocations: {[size for _, size, _ in m.blocks]} bytes")
        empty = variant(shipped, b"", HEADER_CMDLINE)
        run = run_of(empty)
        m = run["machine"]
        say(f"{name}  5 info     zero-length ramdisk (not for shipping): {expect_card(run)};"
            f" android_image_get_ramdisk left by its zero-size exit {len(m.calls['ramdisk_size_is_zero'])}x;"
            f" copy request {[(hex(to), hex(source), size) for to, source, size in ramdisk_copies(run)]},"
            f" bytes written near {RAMDISK:#x}: {m.written['ramdisk'] or 'none'};"
            f" environment initrd_start..initrd_end {m.env.get('initrd_start')}..{m.env.get('initrd_end')};"
            f" do_bootm's fdt_initrd call ran {len(m.calls['ramdisk_into_tree'])}x;"
            f" device tree linux,initrd-start..end {initrd_span(run['tree'])},"
            f" reserved {[(hex(a), b) for a, b in reserved(run['tree'])]};"
            f" {expect_kernel(run, kernel)}; {expect_bootargs(run, f'{KNOWN_BOOTARGS} {HEADER_CMDLINE}')}")
        say(f"{name}  5 info     package device tree before boot: linux,initrd-start..end {initrd_span(tree)},"
            f" reserved {[(hex(a), b) for a, b in reserved(tree)]}, {spare(tree)} spare bytes")
    try:
        information()
    except (Failed, KeyError, ValueError, TypeError, IndexError, struct.error) as error:
        say(f"{name}  5 info     could not be collected: {type(error).__name__}: {error}")
    return results


ITEMS = ["same code", "shipped", "1 card", "2 kernel", "3 ramdisk", "4 cmdline", "4 control"]


def stored_environment(prefix: Path) -> dict[str, str]:
    with prefix.open("rb") as handle:
        handle.seek(ENV_SECTOR * 512)
        raw = handle.read(ENV_BYTES)
    require(zlib.crc32(raw[4:]) == word(raw, 0), "environment partition checksum")
    lines = raw[4:].split(b"\0\0")[0].split(b"\0")
    return dict(line.decode("latin1").split("=", 1) for line in lines if b"=" in line)


def main() -> int:
    tool = Path(os.environ.get("KERNEL_GZIP_TOOL", REPO / "tools/kernel_gzip.py")).resolve()
    sys.path.insert(0, str(tool.parent))    # the tool may import its neighbours
    spec = importlib.util.spec_from_file_location("kernel_gzip_pinned", tool)
    kernel_gzip = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kernel_gzip)
    targets = sys.argv[1:] or list(json.loads(kernel_gzip.CATALOG.read_text())["profiles"])

    def say(text: str) -> None:
        print(text, flush=True)

    def load(name: str) -> Target:
        prefix = REPO / "work" / name / "boot-prefix.img"
        environment = stored_environment(prefix)
        require(environment.get("boot_normal") == f"sunxi_flash read {IMAGE:x} boot;bootm {IMAGE:x}",
                f"{name}: boot_normal is not the command pair emulated here")
        return Target(name, kernel_gzip.derive(name, prefix), environment)

    say(f"fast-boot emulation: python {platform.python_version()} on {platform.system()} {platform.machine()},"
        f" unicorn {unicorn.__version__}")
    say(f"pinned firmware derived by {os.path.relpath(tool, REPO)} (sha256 {sha(tool.read_bytes())[:16]},"
        f" catalog {sha(kernel_gzip.CATALOG.read_bytes())[:16]})")
    say("modelled instead of run as vendor code:\n" + MODELLED)
    say("how the ramdisk size is used on this path:\n" + SIZE_NOTES)
    say("items 1-4 are checked twice, with U-Boot's console at the stock level and switched off")
    reference = load(REFERENCE).code
    table = {name: check_target(load(name), reference, say) for name in targets}

    say("\n" + "target".ljust(12) + "".join(item.ljust(11) for item in ITEMS))
    for name, results in table.items():
        say(name.ljust(12) + "".join(results[item].ljust(11) for item in ITEMS))
    failed = [f"{name}: {item}" for name, results in table.items() for item in ITEMS if results[item] != "PASS"]
    say(f"\n{len(table)} targets, " + ("every check passed" if not failed else "FAILED " + ", ".join(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failed as error:
        sys.exit(f"fast-boot emulation: {error}")
