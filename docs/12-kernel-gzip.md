# 12 — Boot files and the one-update migration

BaseOS keeps the vendor boot0, U-Boot and kernel code and changes only what
they are given. All supported H700 images ship the same set of changes, derived
per target from pinned vendor firmware. `manifest/kernel-gzip.json` pins each
target's original boot0, boot package, U-Boot and boot partition by SHA-256.
Unknown firmware is refused by the builder; a new vendor build requires a new
audit and profile rather than a speculative binary patch.

## What changes

| Where | Change | Why |
| --- | --- | --- |
| U-Boot, in the boot package | One Thumb instruction selects gzip for Android images | The kernel is stored gzip-compressed; less to read from the card |
| Boot image, kernel | gzip level 9, fixed timestamp | As above. The decompressed kernel is byte-identical |
| Boot image, ramdisk | A 512-byte empty archive replaces the vendor initramfs | The kernel mounts the root partition itself; `rcS` does what the initramfs did (see below) |
| Boot image, header command line | `loglevel=1 rcupdate.rcu_expedited=1 rcupdate.rcu_normal_after_boot=1` | U-Boot appends this field to the kernel arguments. Only panics are printed to the serial port; RCU grace periods are fast while the kernel starts and normal afterwards |
| Boot package, device tree | `/soc/platform` `debug_mode` 3 → 0 | U-Boot stops printing to the serial port |
| boot0 header | `debug_mode` byte 3 → 0 | boot0 stops printing to the serial port |

Nothing else differs: U-Boot's other code, the monitor, the device trees'
hardware description, the environment partition and the kernel are unchanged.
The serial port stays usable after startup; `dmesg` is complete.

### What the initramfs did

The vendor initramfs ran `e2fsck -y` on the root partition, mounted it with
`rw,noatime,nodiratime,noauto_da_alloc,barrier=0,data=ordered` and switched to
it. Without it the kernel mounts the partition read-only with default options
and has already replayed the journal. `rcS` then:

1. runs the bundled static `e2fsck -y` only if the filesystem carries recorded
   errors (`/sys/fs/ext4/mmcblk0p5/errors_count`);
2. remounts the root `rw,noatime,nodiratime,nobarrier,noauto_da_alloc`, unless
   that check changed anything, in which case the root stays read-only until
   the next restart rather than being written through stale cached state.

On a card that still boots through the initramfs the root arrives writable and
this block does nothing, so one rootfs serves every boot set below.

## Build contract

`tools/kernel_gzip.py` derives three pieces from the pristine prepared inputs
and checks that only the intended bytes changed in each:

- the boot package: the selector instruction, four device-tree bytes and the
  U-Boot and package checksums;
- the boot image: header sizes, command line and image ID, the gzip kernel and
  the empty ramdisk. Load addresses and the appended device tree are kept;
- boot0: the debug byte and its checksum, in the first copy at 8 KiB. boot0
  keeps a second copy at 256 KiB and rewrites the first sector of both on every
  boot, so that copy follows at the first start (seen on the RG SP).

It also still derives the gzip-only pair that release 1.3.0 shipped, so the
migration can recognise cards that carry it.

`build-image.sh` installs and verifies all three in fresh images.
`build-rootfs.sh` includes the package, the boot image and a manifest in
`/usr/share/baseos/boot-gzip/`, so the unchanged `baseos-update/1` archive
format can deliver the migration to existing installations. The payload adds
roughly 8 MiB to the rootfs.

## Migration of existing cards

Copy the target's normal `.bosupd` onto the frontend card and restart. The
existing updater installs the rootfs. Its first boot shows an
optimising-startup message, replaces the boot files, continues to the frontend
and confirms the rootfs trial. The running kernel is identical in every boot
set, so no extra restart is needed; the next ordinary boot uses the new files.

`baseos-boot-migrate` recognises three audited states of the boot package and
boot image, by hash, and refuses anything else:

| Installed | Meaning | Steps |
| --- | --- | --- |
| original | Vendor files, uncompressed kernel | Both files are written, then verified. Not bootable in between |
| gzip | The pair release 1.3.0 installed | Boot image written and verified, then the package written and verified. Every state in between boots |
| fast | The current set | Nothing to write |

A boot image is recognised by a hash over exactly the bytes its header
describes; whatever follows it in the partition is ignored and left alone. A
gzip half beside a fast half, as an interrupted earlier run leaves behind, is
recognised and completed.

boot0 is handled last and separately. boot0 rewrites its own first sector on
the card at every boot (checksum and memory-training values), so only the
bytes after that sector are pinned by hash. The migration checks the magic,
length, a checksum that reproduces and the pinned body, then rewrites that one
sector with the debug byte cleared and the checksum adjusted, and reads all of
boot0 back. A boot0 that fails any check is left untouched; the rest of the
migration still completes and the result records why.

### Checks, failure handling and recovery

Before writing, the migration checks target identity, partition geometry, the
replacement files' hashes, persistent writable userdata and power: external
power or at least 50% battery, otherwise it defers to a later boot without
leaving a marker. Charging-only and USB-storage sessions do not migrate.

A recovery copy is on userdata before the first write: the original pair saved
by the first migration under `/data/boot-gzip-v1/` if it is intact, otherwise
the installed package and the installed image's own bytes under
`/data/boot-pair-v2/`. Nothing in `/data/boot-gzip-v1/` is modified.

A failed write or readback puts the previous files back and verifies them. If
that cannot be verified, frontend startup and trial confirmation stop, the
display asks to keep power on and ADB remains available. Do not restart in that
condition; the previous contents are kept in `/tmp`.

**The update is not power-loss-safe.** The shared boot areas are outside rootfs
A/B protection. The boot package has no second copy; boot0 has one, but whether
the boot ROM falls back to it has not been tested. Coming from the gzip pair, power lost between
steps still leaves a bootable card; power lost during a write can leave a
component torn, as can any power loss while coming from the original pair.
Repair then means writing the saved files back from another computer or
reflashing the card.

`/data/boot-pair-v2/migration.log` records the operation; `complete` contains
`installed`, `already-installed`, `rolled-back` or a `skipped:` reason,
followed by a note if boot0 was left unchanged. Completed boots execute one
shell-builtin existence check and start no helper.

An older rootfs started on the new boot files, which only a manual slot flip
can produce, still boots, but it lacks the wait for the second card slot
described in [rootfs and init](01-rootfs-and-init.md) and may pick TF1 as the
frontend card.

## Validation and timing

Each target's own U-Boot is run under Unicorn against the exact boot image the
build ships (`tests/test-fast-boot-emulation.py`,
`tests/test-kernel-gzip-emulation.py`): the card is asked for exactly the
image's bytes, the kernel unpacks to the original, the 512-byte ramdisk is
copied, and the header command line is appended to `bootargs`. Hardware
operations are modelled: this is function-level emulation, not a whole boot,
and it says nothing about how each kernel takes the changes. Every target's
kernel contains the arguments used.

`tests/test-kernel-gzip.py` checks the derived files and the corruption gates
for every target. `tests/test-boot-migration.sh` runs the real migration script
on ordinary files in a disposable Alpine container: every transition, injected
write failures at each write, rollback, the boot0 patch arithmetic, and one
end-to-end run with the files the build produces for the RG SP.
`tests/test-root-mount.sh` covers the root-partition handling in `rcS`.

The RG SP is the physical test device. There the migration script itself
replaced a 1.3.0 card's files, and warm restarts with USB attached measured
(medians, seconds from the hardware counter's origin):

| | Before Linux | Linux to handoff | Combined |
| --- | ---: | ---: | ---: |
| Release 1.3.0 | 3.46 | 2.26 | 5.73 |
| This set, with the `rcS` changes | 2.76 | 1.64 | 4.41 |

Measured one change at a time: about 0.7 s is serial output in the three
stages, 0.5 s the initramfs, 0.2 s the RCU arguments and under 0.1 s `rcS`.
Those were separate runs and do not sum exactly. Other models still need
physical acceptance tests. See [experiments](../experiments/h700-boot-speed/README.md)
for the individual measurements and [boot profiling](09-boot-profiling.md) for
how the stages are measured.
