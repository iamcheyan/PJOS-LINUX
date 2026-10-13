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
release 1.3.0. The final build, installed from its `.bosupd` by the normal
updater, took 4.02, 4.10 and 4.18 s over three boots and passed all 39 checks
of `validate-on-device.sh`. Three or four boots per row is a small sample. Kernel start-up
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

## After the handoff: squashfs and reading ahead

Everything above stops at the handoff. These tests also timed the first frame
NextUI draws, to find out whether a compressed root filesystem would help.
[`first-frame.py`](first-frame.py) ran them, and
[`evidence/first-frame-squashfs-preload.txt`](evidence/first-frame-squashfs-preload.txt)
has every boot.

Before the handoff there is little to gain. Startup reads 3.3 MiB from the
root partition, and the card is busy for 0.19 s. The kernel mounts the ext4
root in 11 ms.

After the handoff NextUI takes 3.4 s to draw its first frame, and the card is
busy for 2.8 s of that. The card runs in SD high-speed mode at about 20 MB/s,
so the number of bytes decides the time. NextUI reads 28 MiB from the root
partition, most of it the 19 MB GPU library, and 12 MiB from its own card.

The table gives medians of three boots, in seconds of kernel uptime. The time
before Linux, about 2.77 s, comes on top.

| Variant | Handoff | First frame | Read from the card by then |
|---|---:|---:|---:|
| ext4, as the branch ships | 1.35 | 4.76 | 43.6 MiB |
| `/usr/lib` from a squashfs image | 1.41 | 4.18 | 33.7 MiB |
| The `/usr/lib` image as BaseOS now ships it, four boots | 1.35 | 4.05 | 33.6 MiB |
| ext4, libraries read ahead from the start of `rcS` | 2.38 | 4.37 | 45.5 MiB |
| The same at idle I/O priority | 2.35 | 4.28 | 45.5 MiB |
| ext4, libraries read ahead from the end of `rcS` | 1.45 | 4.45 | 45.5 MiB |
| ext4 with a 1024 KiB read-ahead window | 1.39 | 4.87 | 54.4 MiB |
| squashfs, libraries read ahead from the start of `rcS` | 1.78 | 4.43 | 33.6 MiB |
| squashfs with a 1024 KiB read-ahead window | 1.44 | 4.44 | 41.1 MiB |

- With `/usr/lib` served from squashfs the first frame came 0.58 s earlier.
  The handoff came 0.06 s later, because `rcS` first set up a loop device and
  two mounts. The image used LZ4 HC, which the processor unpacks faster than
  the card delivers. gzip and xz images are smaller, but unpacking them costs
  more time than the smaller read saves.
- Reading the libraries ahead on ext4 brought the first frame 0.3 to 0.5 s
  earlier. Started early, it delayed the handoff by a full second, because
  `rcS` waited for the card behind it. Idle I/O priority did not prevent that.
  Started at the end of `rcS`, it gained 0.3 s.
- A larger read-ahead window read more from the card and gained nothing.

The squashfs test kept the ext4 root. It wrote a squashfs image of the rootfs
to the unused slot, mounted it through a loop device and bound its `/usr/lib`
over the real one. Every file in it had the same hash as its ext4 copy.
[`evidence/first-frame-test-rcS.patch`](evidence/first-frame-test-rcS.patch)
is the startup script the tests used.

BaseOS now ships the squashfs variant in a simpler form. `build-image.sh`
stores `/usr/lib` as a squashfs file inside the ext4 root, and `rcS` mounts
that file directly over the directory. With one mount and no bind the handoff
is no later than on ext4, and the first frame came about 0.7 s earlier than in
the ext4 row. The update to that build went through the normal updater, and
the build passed all 41 checks of `validate-on-device.sh` and a 30-second
sleep. [`evidence/lib-image-update-install.txt`](evidence/lib-image-update-install.txt)
has the record, and [rootfs and init](../../docs/01-rootfs-and-init.md#the-usrlib-image)
describes the image. Reading ahead and the larger read-ahead window stay out.

### What a squashfs root would need

Three things stand in the way of making the whole root squashfs.

- The vendor initramfs mounts the root with `-t ext4`. A card on release 1.3.0
  or earlier takes its first boot of a new rootfs through that initramfs,
  because the migration runs inside the new rootfs. A squashfs root therefore
  cannot arrive in the update that removes the initramfs. It needs a release
  in between and an update format that older updaters refuse.
- Nothing recovers a slot the kernel cannot mount. The kernel panics and
  stays there, and no watchdog restarts it. The rollback after three failed
  boots starts in `rcS`, which never runs.
- `tools/mkupdate.py` looks for the version stamp in the raw bytes of the
  slot, `build-image.sh` checks the slot with `e2fsck`, and root's home
  directory is on the root filesystem.

Serving only `/usr/lib` from an image stored in the ext4 root avoids all
three, which is why BaseOS ships that form. The root stays ext4 and writable,
the updater handles the same kind of slot image, and the first boot through
the initramfs works as before. Every supported kernel has squashfs with LZ4
and the loop driver built in, and the build checks that.

## Not done

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
- [`first-frame.py`](first-frame.py) restarts the device with the libraries
  served in different ways and reports when the first frontend frame appears.
