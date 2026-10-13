# H700 boot-speed experiments — RG SP, 2026-10-13

Measured attempts to shorten startup without changing the vendor kernel,
U-Boot or boot0 code. Every change here is an input those programs already
read: the ramdisk beside the kernel, the kernel argument line, values in the
device tree, and one byte in the boot0 header.

**Status: stopped early.** After 25 good restarts, the 26th left the device
frozen at the boot logo on every power-on. The cause is not yet known; see
[Device state and recovery](#device-state-and-recovery). Nothing here is ready
to ship.

## Results

Warm restarts with USB attached, Slot on TF2. Times are medians in seconds from
the hardware counter origin; `combined` ends at frontend handoff. Each row
includes the changes of the rows above it.

| Variant | Boots | Before Linux | Linux to handoff | Combined | Saved |
|---|---:|---:|---:|---:|---:|
| Unchanged (gzip kernel, vendor initramfs) | 3 | 3.456 | 2.262 | 5.727 | — |
| + kernel serial output quiet (`loglevel=1`) | 3 | 3.446 | 2.123 | 5.571 | 0.16 |
| + no initramfs (empty ramdisk) | 3 | 3.295 | 1.800 | 5.096 | 0.48 |
| + U-Boot serial output off (`debug_mode` 3 → 0) | 3 | 3.035 | 1.887 | 4.935 | 0.26 before Linux |
| + boot0 serial output off (header byte 3 → 0) | 3 | 2.756 | 1.857 | 4.613 | 0.28 before Linux |
| + USB: OHCI 2, EHCI 3 and OHCI 3 off | 3 | 2.734 | 1.674 | 4.400 | 0.21 |

Total: 5.73 s to 4.40 s, about 1.3 s. Three boots per row is a small sample;
the ranges are in [`evidence/results.json`](evidence/results.json). Kernel
start-up alone varies by about 0.15 s between identical boots, mostly in the
PMIC probe (89–175 ms).

## Findings

1. **Serial output is the largest single cost.** boot0, U-Boot and the kernel
   all print to the 115200 baud UART and wait for it. Turning all three off
   saved about 0.7 s. With `loglevel=1` the kernel still prints panics.
2. **The initramfs can go.** With an empty ramdisk the kernel mounts
   `root=/dev/mmcblk0p5` itself and runs `/init`. The root filesystem then
   comes up read-only, and BaseOS ran that way for 19 boots without a
   complaint. The automatic `e2fsck` is lost.
3. **U-Boot appends the boot image's own command-line field** to the kernel
   arguments, so arguments can be added without touching the env partition.
4. **USB ports 2 and 3 cannot simply be switched off.** Disabling both pairs of
   controllers saved 0.2 s but stopped USB device mode (adb) on the OTG port.
   Keeping EHCI 2 on and disabling OHCI 2, EHCI 3 and OHCI 3 kept adb working
   and saved 0.17–0.2 s. Nothing was plugged into a host port, so host mode is
   untested.
5. **boot0 rewrites its own header on the card during boot** (memory training
   values and checksum), so it cannot be pinned by hash. The debug byte
   survives those rewrites.
6. **A faster boot exposed a card race.** TF2's card is ready about 0.4 s after
   its controller starts. Once the kernel finished earlier, `rcS` reached the
   card mount first and used TF1 as the frontend card: 1 of 3 boots without the
   initramfs, 2 of 3 with the USB change
   ([`evidence/card-race-lost.txt`](evidence/card-race-lost.txt)). The same
   race decides which disk USB-storage mode exports. `rcS` now waits while the
   kernel still has the slot powered; 4 of 4 boots then used TF2. The wait was
   tested inside a larger rework, not in the form committed here, and never
   with an empty TF2 slot.
7. **Reordering `rcS` gave no measurable gain with TF2 in use**, because the
   card's own start-up time sets the pace. The rework is kept as
   [`evidence/startup-reorder-tried.patch`](evidence/startup-reorder-tried.patch).
   Step timings are in
   [`evidence/startup-steps-before.txt`](evidence/startup-steps-before.txt):
   58 ms to start init, 46 ms to mount `/data`, 37 ms to mount exFAT, and
   roughly 5 ms for every append to the card's log.
8. **This adbd cuts off a lone command with all three standard streams
   redirected**, such as BusyBox `dd if=… of=… 2>/dev/null`. `lab.py` ends
   every command with a marker and refuses output without it.

## All eleven targets

[`survey.py`](survey.py) compares the prepared firmware of every supported
model ([summary](evidence/all-targets-survey-summary.txt)). Identical
everywhere: boot0 and U-Boot `debug_mode` 3, the env partition, the initramfs
`/init` script, an empty boot-image command line, USB port 1 with a power pin
and ports 2 and 3 without, and a kernel that has `initcall_blacklist` but
neither `usb_host_init_state` nor `no-prescan-powerup`. Kernels, U-Boot builds
and device trees differ per model, so each needs its own derived files. Only
the RG SP was booted.

## Not possible without new kernel code

The SD controllers (183 ms), PMIC probe and the many small driver starts have
no configuration switch in this kernel. Deferring USB ports or the Wi-Fi SDIO
controller would need a helper module that creates those devices after handoff.

## Not done

- A compressed read-only rootfs (squashfs). It needs the initramfs gone first,
  and the device became unreachable before it could be tried.
- Any measurement with TF1 as the only card, or from a cold power-on.

## Device state and recovery

The RG SP was left with experimental boot areas and startup scripts:

- boot image: empty ramdisk, `loglevel=1` in the header command line;
- bootloader package: `debug_mode` 0, OHCI 2, EHCI 3 and OHCI 3 marked `fail`;
- boot0: `debug_mode` 0;
- `/etc/init.d/rcS` and `/usr/sbin/frontend-session`: the reworked versions
  with temporary step markers.

Every change except the step markers had booted at least four times. The
failing restart followed 25 restarts that each detached TF2 while Slot was
still writing to it, so a damaged exFAT volume on TF2 is one suspect; the last script
deploy is the other.

Backups of the original bytes are in `work/lab/backup/` of this checkout
(ignored by git): `boot.bin` (all of p4), `toc1.bin`, `boot0.bin`, `env.bin`.
The original scripts are in `work/lab/device-files/`.

With the device reachable over adb: `lab.py restore`, then copy the two
original scripts back. With TF1 in a card reader on a Mac (replace `N`):

```sh
diskutil unmountDisk /dev/diskN
sudo dd if=work/lab/backup/toc1.bin of=/dev/rdiskN bs=512 seek=32800 conv=notrunc
sudo dd if=work/lab/backup/boot.bin of=/dev/rdiskNs4 bs=1m
```

That restores the bootloader package and boot partition. boot0 keeps its quiet
setting, which is harmless. The two scripts live on ext4, which macOS cannot
write; reflashing BaseOS replaces everything.

## Tools

- [`lab.py`](lab.py): backup, build a variant, write and verify it, restart,
  collect timings. It restarts with NextUI's `reboot_next` after remounting
  `/data` and `/` read-only, as the earlier timing work did.
- [`fdt.py`](fdt.py): same-size device-tree edits, so no offset moves.
- [`survey.py`](survey.py): read-only comparison of prepared firmware.
