# Project instructions

<!-- private agent notes are kept outside this repository -->

## RG34XX test device

- Device: BaseOS RG34XX, hostname `rg34xx`.
- Wi-Fi SSH: `root@<device-lan-ip>`, port `22`.
- The development image uses a fixed throwaway password; it is not recorded in this repository.
- Prefer USB ADB when connected: run `adb devices -l`, then `adb -s <device-serial> shell 'hostname; id'`. Use the password-assisted Wi-Fi SSH command below if the USB transport is absent/offline or intentionally disabled. Do not stop diagnosis at an empty ADB list.
- Example: `ssh root@<device-lan-ip>`.
- Verified noninteractive login (2026-11-12):
  ```sh
  sshpass -p "$PJOS_DEV_PW" ssh -o ConnectTimeout=5 -o UserKnownHostsFile=/tmp/pjos-debug-known-hosts -o StrictHostKeyChecking=accept-new root@<device-lan-ip> 'hostname; id'
  ```
  Expected output includes `rg34xx` and `uid=0(root)`. A bare `ssh` command does not supply the documented password automatically; use `sshpass` for noninteractive tools. Do not use `BatchMode=yes` for password login.
- Verified USB ADB on 2026-11-12 after manual `usb-gadget-adb setup` recovery: Debian sees serial `<device-serial>` as `device`, the handheld returns `rg34xx`/`uid=0(root)`, UDC state is `configured`, and `g1/UDC` contains `5100000.udc-controller`. The previously observed empty UDC was a gadget binding/OTG state issue, not proof that `adbd` was dead.
- ADB is USB-only: no TCP listener on port 5555 is expected. `/data/no-adb` is its persistent opt-out. The new `usb-gadget-adb status` reports requested `on`/`off`; `enable` clears the opt-out and actively retries setup every time, even if already enabled; `disable` persists the opt-out and removes the ADB interface while preserving any already selected storage function. Settings route through `rocknix-services set adbusb.enabled on|off`. Never test the off path through the sole active ADB transport: establish SSH first.
- Source now includes `/sbin/hotplug` (installed from `overlay/usr/sbin/hotplug` via merged-/usr). After initial boot setup, it retries a lost binding on a power-supply/UDC event only when ADB is enabled, the existing composition contains ADB, USB power is online, and safely read `usbc0/otg_role` is `usb_device`. It does not force a role or run a resident polling watcher. A host-role attach remains a vendor-kernel limitation; use enable to request setup, and if necessary boot with the data cable attached. Do not read the role-trigger siblings `usb_device`, `usb_host`, or `usb_null`.
- Hotplug/off→on behavior is covered by fake-tree tests. The scripts are now deployed, and software disable→enable was verified over backup SSH: ADB disappeared while off and reappeared as `device` after enabling and waiting for host enumeration. Real cable replug and UI switch-cycle verification remain separate pending checks. See `docs/24-rg34xx-adb-recovery.md` and the unified issue tracker `docs/25-rg34xx-debug-progress.md`.
 - Debugged SSH and ADB using the exact verified password-assisted SSH command above. Do not use bare SSH with `BatchMode=yes` or conclude SSH is unavailable without testing the documented command.
- An old host key for this IP exists in the default known_hosts. The working command isolates the current device key in `/tmp/pjos-debug-known-hosts`, preserving existing records. `accept-new` records a first-seen key; it does not independently verify its identity or accept a changed key in that file. The device ED25519 fingerprint observed during this session was `SHA256:gvXjj5OSbV/V+FjbNyWb+wGefuxeStGAvuhZA7CdysI`.
- The SD card's active System directory is `/mnt/sdcard/System`, also accessible as `/storage/System`.
- Runtime settings: `/storage/.config/pocketjs/runtime.conf`.
- Idle policy overrides: `/storage/.config/baseos/screen-idle.conf`. These override the launcher settings; check both files when debugging sleep or automatic power-off.
- During the current investigation, automatic screen blanking and power-off were temporarily disabled with `timeout = never` and `auto_stop_timeout = never` in the idle override file. Do not report this mitigation as a completed fix.
- Framebuffer: `/dev/fb0` is a 720 × 960 double-height buffer, 32 bits per pixel/BGRX; the visible panel is 720 × 480. Read `/sys/class/graphics/fb0/pan` for the active offset (observed `0,480`) and crop that 720 × 480 region after decoding. The other half can contain an old game's frame; do not mistake both buffers for a split-screen UI. With this adbd, use `adb shell 'dd if=/dev/fb0 of=/tmp/frame.raw bs=4096 count=675'` then `adb pull`; `exec-out` is unsupported. Check the raw file is 2,764,800 bytes before decoding.
- USB identity: `18d1:4e42` (serial kept out of the repo). The PVE host is reachable from the lab; the Debian VM there has `usb0: host=18d1:4e42` configured.
- Back up device files before deploying changes and verify the active files and device behavior after deployment. Do not disable Wi-Fi while it is the active debugging transport.
