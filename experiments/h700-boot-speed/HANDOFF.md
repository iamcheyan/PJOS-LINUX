# Handoff: where the pre-Linux time goes, and the counter-stamp measurement

Written 2026-10-15 for whoever continues. Nothing in this worktree is committed
yet (branch `uboot-trace`, worktree `work/uboot-trace`). The `work` entry in
the worktree is a symlink to `../boot-speed/work`, which holds the prepared
firmware of all eleven targets and the lab backups; it is excluded from git.

## The question

BaseOS 1.4.0 boots to the frontend handoff in about 4.1 s on the RG SP and
5.8 s on the RG34XX SP. The kernel-to-handoff part is 1.4 s on both. The rest
is before Linux: 2.7 s and 4.4 s from the counter origin to the kernel's clock.
The user wants to know how that time splits, on every model, to decide whether
BaseOS should replace the vendor U-Boot with its own loader (keeping boot0 and
the monitor so that DRAM and panel detection stay stock; see
`variant-survey/README.md`).

## What is established

- Films at 240 fps: the logo appears 0.54 s (RG SP) and 0.66 s (RG34XX SP)
  after the power LED. The emulation shows the backlight comes on 0.51 s after
  U-Boot's display init, so the LED is most likely switched on by U-Boot's PMIC
  init, not at power-on; the film does not see boot0 or DRAM training.
- The USB cable changes nothing (no-cable boots logged the same pre-kernel).
- The RG SP and RG34XX SP U-Boot items are the same program; only the build
  date string differs (`uboot-trace-notes/delays/diff.md`). Environment
  partitions are identical. Device trees differ only in ADC, keys and battery
  capacity, which U-Boot does not read.
- Under emulation (`uboot-trace.py`, all eleven builds, both strap values,
  `evidence/uboot-trace-notes.md`): from display init to the kernel jump U-Boot
  spends about 1.04 s of modelled time: 0.51 s panel sequence (285 to 465 ms of
  busy delays in interrupt context, which block the bitmap load), 17 ms of
  vendor post-logo steps, 363 ms card read of the 7.2 MB boot image at an
  assumed 20 MB/s, 265 ms gunzip at an assumed 1 GHz. The shape is the same on
  every build. Panel delays are the only per-build variable.
- So on hardware roughly 1.7 s (RG SP) and 3.2 s (RG34XX SP) between the logo
  and the kernel clock are outside what the model can see: the card's real
  speed under U-Boot's driver, the CPU clock U-Boot runs at, the monitor call
  and early kernel, and on the RG34XX SP something more. The RG34XX SP reads
  its panel strap low (`lcd_type=boe`, 465 ms table) where the RG SP reads it
  high (285 ms): 180 ms of its gap, before the logo. Its PMIC readings are
  healthy and the vendor battery check takes the fast path
  (`uboot-trace-notes/battery/eval_regs.py` on `work/rg34xxsp-live/`).

## The measurement in progress: counter stamps in U-Boot

A patched boot package for the rg34xxsp target records the 24 MHz generic
counter at six points of the vendor U-Boot flow (stubs placed in the dead help
text of `sunxi_nand_test`; call sites redirected; checksums refreshed):

| slot | where | meaning |
|---|---|---|
| 0 | 0x2B22 | logo routine returned |
| 1 | 0xF13E | vendor post-logo steps done, main_loop entered |
| 2 | 0xC1FC | card read of the boot image starts |
| 3 | 0x7E80 | card read done, bootm starts |
| 4 | 0x152A | kernel unpacked, boot_prep_linux |
| 5 | boot_jump_linux | about to jump |

Together with the boot log's `pre-kernel` figure (counter at the kernel's
clock origin) this splits the time into: vendor steps, card read, gunzip,
monitor plus early kernel. The LED-to-logo film and slot 0 give the pre-logo
part. Files: `work/rg34xxsp-stamp/` (build-stamped.py, verify-stamped.py,
stamps.json, NOTES.md, read-stamps.py, the packages). Copy the scripts into
`experiments/h700-boot-speed/uboot-stamp/` before committing; the .bin files
are derived.

State on 2026-10-15 evening: v1 (`boot-package-stamped.bin`, stamps stored at
0x40000100) is on the RG34XX SP's card and boots normally, but the kernel
reuses that page before it can be read, so the stamps were unreadable. A v2
was requested from the build agent: the final stub runs after the FDT copy to
0x44000000 and copies the stamp block (magic 0x5354414D plus six 64-bit
stamps) into the last 64 bytes of the device tree, which the kernel reserves
and exposes at `/sys/firmware/fdt`. `stamp-run.py read` already expects that
layout.

### How to run it (RG34XX SP, adb serial 1c00103dc2840671ed3)

The lab tooling lives in the boot-speed worktree. From `work/uboot-trace`:

    set -a; . ../boot-speed/work/lab/rg34sp.env; set +a
    /tmp/uboot-venv/bin/python experiments/h700-boot-speed/stamp-run.py install [boot-package-stamped-v2.bin]
    /tmp/uboot-venv/bin/python experiments/h700-boot-speed/stamp-run.py restart
    /tmp/uboot-venv/bin/python experiments/h700-boot-speed/stamp-run.py read
    /tmp/uboot-venv/bin/python experiments/h700-boot-speed/stamp-run.py restore   # the build's own package back
    /tmp/uboot-venv/bin/python experiments/h700-boot-speed/stamp-run.py restart

`install` refuses unless the card holds the build's package or a known stamped
one; writes are read back and verified. `restart` is the lab's safe path
(pause the frontend, remount read-only, run reboot_next); never plain `reboot`.
The device sometimes drops off adb for no visible reason; a power cycle brings
it back. If `/tmp/uboot-venv` is gone: `python3 -m venv` and install
`experiments/rgsp-kernel-gzip/requirements.txt`.

If the device stops booting after a write: the boot package has no second copy.
Restore `work/rg34xxsp/boot-gzip/boot-package.bin` at byte offset 16793600 of
the card from a card reader (the lab's `fix-card.py` in the boot-speed worktree,
or dd), length 1310720.

### What to do with the numbers

Report the split per bucket and compare with the emulation's assumptions: card
bytes per second under U-Boot (7.25 MB over slot 2 to 3), gunzip time (slot 3
to 4, 17.7 MB unpacked), monitor plus early kernel (slot 5 to the kernel clock
origin), vendor steps (slot 0 to 1, expected about 17 ms plus panel interrupt
stalls). The RG SP was in use by another agent on 2026-10-15; the same package
built for rgsp (identical U-Boot, so the same patch applies; rebuild from
`work/rgsp/boot-gzip/boot-package.bin` with build-stamped.py) would give the
RG SP's split for comparison.

## Other artifacts in this worktree

- `uboot-trace.py`: the tracer (phases init, pre, late, main; models listed in
  its MODELLED string). About 75 s per target.
- `uboot-trace-notes/`: routine map of the rgsp U-Boot, the SD driver
  specification, the per-build delay inventory, the battery-check evaluator,
  the analysis scripts.
- `variant-survey/`: how boot0 detects DRAM and U-Boot detects the panel, with
  the scripts and their output; the shape of a replacement loader.
- `evidence/uboot-trace-all.json`, `uboot-trace-pe6-low.json`,
  `uboot-trace-notes.md`: the emulation results.

## Open items

1. Read the stamps (v2), on the RG34XX SP and ideally on the RG SP.
2. Write the per-bucket budget into `evidence/` and the architecture
   recommendation: a loader behind boot0 and the monitor that overlaps the
   panel sequence with the kernel read, reads fewer bytes, and avoids gunzip.
3. Commit the worktree (plain-language message; do not push).
4. The 1.5 s RG34XX SP gap is a hardware-bound part of the budget; the stamps
   say which bucket. 180 ms of it is the panel strap.

## Update, end of 2026-10-15: the split is measured, next step is the loader

See `uboot-stamp/RESULTS.md`. On the RG34XX SP the kernel clock starts 4.39 s
after the counter origin; 1.01 s of that is after the logo (0.1 vendor steps
and panel stalls, 0.30 card read at 24 MB/s, 0.39 gunzip, 0.04 prep, 0.17
monitor and early kernel) and 3.38 s before it (boot0, DRAM, U-Boot init,
logo). The pre-logo split between boot0 and U-Boot was not captured (v3
stamps did not surface). The user's decision: stop measuring and build the
replacement, then measure with it.

Loader plan (keeps boot0 and the monitor, replaces only the 32-bit U-Boot item
of the TOC1 package; see `variant-survey/README.md` for what it must do):
1. Entry at 0x4A000000 with the Allwinner `uboot` header so boot0 fills in the
   DRAM block; AArch32 code; stack in SRAM or low DRAM; counter stamp at entry
   (this measures boot0).
2. SD host driver for SMHC0 (spec in `uboot-trace-notes/uboot-mmc-rgsp.md`):
   card is already initialised by boot0? No: boot0 initialises the card to
   load the package but the loader must re-init (CMD0..CMD7, 4-bit, high
   speed) unless it reuses boot0's state; use DMA with large descriptors.
3. Read the kernel in one sequential transfer; store it uncompressed (17.7 MB
   at 24 MB/s is 0.74 s) or LZ4 (about 9 MB, 0.37 s plus 0.1 s decode); gzip
   costs 0.39 s today. Read the DT item from the package.
4. Panel: start the power sequence (power on, 30 ms, init with the PE6
   strap, 50 ms, tcon, 100 ms, backlight) with a hardware timer and overlap
   it with the card read; or leave the panel to the kernel's disp driver and
   draw the splash from rcS (black screen until about 1 s).
5. Command line as the vendor builds it (partitions map, snum from SID,
   bootreason from PMIC reg 0x20, lcd_type from PE6, disp_reserve only with a
   splash), /dram and /memory from the header block, then the monitor call as
   `boot_jump_linux` does (0x14E4 via 0xB58 when the monitor is present).
6. Emulate under Unicorn with the tracer's models before any card write;
   deploy with `stamp-run.py`-style verified writes on the RG34XX SP.
Expected result: kernel clock at about 0.6 s plus boot0 (unknown, measured by
the loader's first stamp) instead of 4.4 s; the same on every model.
