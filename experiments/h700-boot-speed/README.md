# H700 boot-speed experiments on the RG SP, October 2026

These are the measurements behind the boot files described in
[docs/12](../../docs/12-kernel-gzip.md). Every change tested here alters an
input that the vendor boot0, U-Boot or kernel already reads. None changes
their code beyond the one U-Boot instruction that release 1.3.0 already
patched.

All timings come from one RG SP, restarted warm with USB attached and the Slot
frontend on TF2. The build derives the same changes for all eleven targets, and
each target's U-Boot passes the emulation tests, but only the RG SP has booted
them.

## Results

Each row adds one change to the row above it. Times are medians in seconds,
counted from the hardware counter's origin. `Combined` ends when BaseOS hands
over to the frontend.

| Variant | Boots | Before Linux | Linux to handoff | Combined |
|---|---:|---:|---:|---:|
| Release 1.3.0 | 3 | 3.456 | 2.262 | 5.727 |
| Kernel prints only panics to the serial port | 3 | 3.446 | 2.123 | 5.571 |
| Empty ramdisk instead of the vendor initramfs | 3 | 3.295 | 1.800 | 5.096 |
| U-Boot prints nothing | 3 | 3.035 | 1.887 | 4.935 |
| boot0 prints nothing | 3 | 2.756 | 1.857 | 4.613 |
| Fast RCU grace periods while the kernel starts | 3 | 2.729 | 1.708 | 4.437 |
| Two waits removed from `rcS` | 4 | 2.756 | 1.643 | 4.406 |
| The same, installed by a `.bosupd` and the migration | 4 | 2.718 | 1.704 | 4.412 |

The USB change came after those runs and was measured with TF2 removed, so
NextUI started from TF1. Medians of three boots each:

| Variant | Before Linux | Linux to handoff | Combined |
|---|---:|---:|---:|
| Everything above | 2.761 | 1.632 | 4.369 |
| Five USB host controllers started by a module | 2.774 | 1.336 | 4.165 |

The branch ships everything in both tables. That is about 1.5 s faster than
release 1.3.0. Three or four boots per row is a small sample. Kernel start-up
alone varies by about 0.15 s between identical boots, most of it in the PMIC
probe, which took between 89 and 175 ms.
[`evidence/results.json`](evidence/results.json) has every run.

About one boot in twelve spent 0.3 to 0.6 s longer before Linux. Three of
those four boots followed a large write to the card.

## What the tests showed

1. Serial output is the largest single cost. boot0, U-Boot and the kernel each
   print to the 115200 baud UART and wait for it. Switching all three off saved
   about 0.7 s. With `loglevel=1` the kernel still prints a panic.
2. The initramfs is not needed. With an empty ramdisk the kernel mounts
   `root=/dev/mmcblk0p5` read-only and runs `/init`. `rcS` then remounts the
   root with the options the initramfs used, and the 4.9 kernel accepts all of
   them on a remount.
3. U-Boot appends the command-line field of the boot image header to the
   kernel arguments, so BaseOS can add arguments without touching the env
   partition. The [emulation log](evidence/fast-boot-emulation.log) shows the
   same behaviour in every target's U-Boot.
4. A full kernel trace with `initcall_debug` found two more costs. Several
   trivial steps each waited about 50 ms for an RCU grace period, and
   `rcupdate.rcu_expedited=1` removed those waits. The kernel also takes 70 ms
   to start each of the three extra CPU cores. The traces are in
   [`evidence/`](evidence/kernel-initcalls-full.dmesg).
5. boot0 rewrites its own first sector on the card at every boot, with new
   memory-training values and a new checksum. A hash can therefore pin only
   the rest of boot0. The debug byte survives those rewrites, and boot0 copies
   it to its second copy at 256 KiB.
6. A faster boot exposed a race for the second card slot. TF2's card is ready
   about 0.4 s after the kernel starts its controller. Once the kernel finished
   earlier, `rcS` reached the card mount first and used TF1 as the frontend
   card in 3 of 6 boots. [`evidence/card-race-lost.txt`](evidence/card-race-lost.txt)
   shows one of them. `rcS` now waits while the kernel keeps the slot powered,
   and every boot since has used TF2. Nobody has tried it with an empty TF2
   slot.
7. A step-by-step trace of `rcS` found that unmounting TF1 after reading its
   settings takes about 60 ms, and that loading the Bluetooth wake driver
   takes about 40 ms. Both now run beside the rest of startup.
8. A faster boot reaches the Wi-Fi driver load sooner after the kernel cuts
   the radio's supply. That would shorten the power-off interval the radio has
   always had before its first power-up, and some radios need a long one.
   `rcS` now starts the first load no earlier than it used to, at 2.25 s. The
   load runs in the background, so the handoff does not wait for it.
9. This adbd ends a session as soon as nothing holds its terminal open. It cut
   off BusyBox `dd if=… of=… 2>/dev/null` after a few sectors. `lab.py`
   appends a marker to every command and rejects output without it.

## What did not help

- Starting the kernel with `maxcpus=1` and bringing the other cores up from
  `rcS` made the boot 0.2 s slower.
- A 16-pixel boot logo saved less than 20 ms before Linux.
- Reordering `rcS` further gave no measurable gain while TF2 is in use, because
  the card's own start-up time sets the pace.
  [`evidence/startup-reorder-tried.patch`](evidence/startup-reorder-tried.patch)
  keeps that attempt.

## USB host controllers

The kernel spends 0.3 s starting six USB host controllers before it runs init.
Three ways of avoiding that were tried.

- Disabling every controller of ports 2 and 3 saved 0.2 s, but the OTG port
  no longer enumerated as a device, so adb over USB stopped working.
- Disabling OHCI 2, EHCI 3 and OHCI 3 and keeping EHCI 2 saved 0.2 s and kept
  adb working. Those ports would have stayed off for good.
- Marking five controllers `late` and starting them from a module saved 0.3 s
  and left all six running 0.4 s after init starts. The branch ships this.
  [`src/h700-late-usb`](../../src/h700-late-usb/h700_late_usb.c) is the module.

The first version of the module wrote the new status into the device-tree
property and crashed, because property values still point into the boot-time
device-tree blob and that memory is read-only. The module now gives the
property a value of its own.

With the module the RG SP slept for 30 seconds and resumed with all six
controllers.

A USB audio adapter plugged into the OTG port worked as a host device.
[`evidence/usb-host-otg-test.txt`](evidence/usb-host-otg-test.txt) has the
kernel messages. The OTG port has host controllers of its own, EHCI 0 and
OHCI 0, which the kernel starts when a device is attached. That test therefore
shows that host mode still works on the one USB port the RG SP has. It does not
use any of the five controllers the module starts. The RG SP has no known
connector for those five, so nothing has been attached to one of them.

## All eleven targets

[`survey.py`](survey.py) compares the prepared firmware of every supported
model, and [its summary](evidence/all-targets-survey-summary.txt) lists what
matches. boot0's code is byte-identical on every target, and only its
per-board settings differ. boot0 and U-Boot use `debug_mode` 3 on every
target. The env
partition, the initramfs `/init` script and the empty boot-image command line
are identical everywhere. Every kernel has the `rcupdate` arguments, the ext4
options and error counter that `rcS` uses, and `initcall_blacklist`. None has
`usb_host_init_state` or `no-prescan-powerup`. Kernels, U-Boot builds and device trees differ per
model, so the build derives each target's files separately.

## What still needs kernel code

The SD controllers take 183 ms and the PMIC probe up to 175 ms, and this
kernel has no setting that shortens or defers them. The Wi-Fi SDIO controller
could be started late by a module, as the USB host controllers are, for about
90 ms. The Wi-Fi driver's power-up timing is delicate, and `rcS` already
carries a retry for radios that reset slowly, so the branch leaves it alone.

## Not done

- A compressed read-only rootfs. It would mostly help the frontend load its
  libraries, which happens after the handoff this work measures.
- A USB device on one of the five controllers the module starts. A model
  with a second USB port or an internal USB device would show it.

## Sleep and wake

The RG SP slept for 30 seconds with an RTC wake alarm set and resumed with the
frontend, Wi-Fi and GPU working, once before the USB change and once after it.
[`evidence/sleep-wake-rtc-alarm.txt`](evidence/sleep-wake-rtc-alarm.txt) has
the kernel messages of the first cycle. Both ran with the USB cable attached.

## Empty second slot and cold power-on

With TF2 removed, a cold power-on took 4.38 s to the handoff and used TF1. The
kernel reported the empty slot as powered off, so `rcS` did not wait for it.
[`evidence/hands-on-empty-slot-cold-boot.txt`](evidence/hands-on-empty-slot-cold-boot.txt)
has the details. That boot was before the USB change.

## The freeze

After 25 good restarts in the first session, the 26th left the device at the
boot logo on every power-on, with or without TF2. A copy of the card showed
why.

- boot0, the boot package and the boot image were intact and matched the
  variant under test. Both ext4 filesystems were clean.
- `/etc/init.d/rcS` and `/usr/sbin/frontend-session` had mode 0666.

The last deployment had replaced those two scripts with `cp` from files that
adb had pushed. adb creates files with mode 0666, and that deployment skipped
the `chmod` that the two earlier ones had run. init could execute neither
script, so nothing mounted, and neither adb nor a frontend started.
[`lab.py`](lab.py) now installs files with an explicit mode, checks it, and
refuses to restart the device unless the scripts that init runs are non-empty,
executable and parse.

`work/lab/fix-card.py` copied the card for that diagnosis. It then wrote back
the original boot areas from `work/lab/backup/` and the two original scripts.
git ignores that folder. The script runs with sudo on a Mac.

## Tools

- [`lab.py`](lab.py) backs up the boot areas, builds a variant, writes and
  verifies it, installs files with a checked mode, restarts the device and
  collects timings. It pauses the frontend, remounts `/data` and `/`
  read-only, and restarts with NextUI's `reboot_next`, as the earlier timing
  work did.
- [`fdt.py`](fdt.py) edits a device-tree value in place without changing its
  size, so no offset moves.
- [`survey.py`](survey.py) reads the prepared firmware of every target and
  reports what differs.
