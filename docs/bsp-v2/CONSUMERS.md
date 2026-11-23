# PocketJS hardware consumers

PocketShell asks its host for `LEVEL`, `STATE` and `CONTROL`; the guest does not need permission to open devices. The production bridge reads `/usr/sbin/baseosctl power battery` (presence, capacity and status) and `/usr/sbin/baseosctl display get-brightness` (0–255, rounded to UI percent). A failed read produces `unknown`, not zero. `heya-control` and `rocknix-settings` translate brightness writes from percent to 0–255. Volume is already in percent. `heya-control` publishes the requested volume, persistence and wheel notification only after `audio set-volume` succeeds; without a cached request it queries `audio get-volume`. Do not substitute a mixer name when that query fails.

## Input contract

The first `--input` is the resolved `gamepad` role. On open, evdev reads `/etc/pjos/input.map` (or `input.map` in the absolute `PJOS_PROFILE_DIR`). The first line is `schema=pjos.input/1`. Remaining lines are `BUTTON key CODE [CODE ...]` or `BUTTON lt|gt AXIS THRESHOLD`. `BUTTON` is a PocketJS semantic button. Comparisons are strict and an axis must have reported a value. Rules are ORed at SYN_REPORT; hats and sticks can independently assert the same direction. Missing, empty and malformed maps prevent the device from opening; there is no fallback key table or product-name ioctl. Each existing H700 board explicitly opts into the previously shipped vendor bindings; this is compatibility data, not measurement of every handheld. TG5040 supplies different face, shoulder, trigger, stick and hat wiring in its board overlay. A different board can override `/etc/pjos/input.map` without rebuilding Rust.

## Card profile handoff (TG5040, vendor boot)

1. On the host run `python3 tools/bsp_compose.py --target tg5040 --output /tmp/pjos-tg5040-stage`. Stage `/tmp/pjos-tg5040-stage/profile.env`, the four generated JSON manifests, and `/tmp/pjos-tg5040-stage/overlay/etc/pjos/input.map` together under `/mnt/SDCARD/System/profile`. Do not copy an image target's map or replace vendor `/etc`.
2. The SD launcher must export `PJOS_PROFILE_DIR=/mnt/SDCARD/System/profile`, `PJOS_BASEOSCTL=/mnt/SDCARD/System/baseosctl`, `DAL_LIB=/mnt/SDCARD/System/dal.sh` and `DAL_DIR=/mnt/SDCARD/System/dal` **before** starting either frontend or helpers. Include the matching auxiliary CLI backend and timeout utility. Ensure card compat tools precede stock shims on PATH. Check `"$PJOS_BASEOSCTL" version` for `board=tg5040` and `soc=allwinner/a133`; do not continue on a mismatch.
3. Obtain the display with `"$PJOS_BASEOSCTL" display node` and pad with `"$PJOS_BASEOSCTL" input node gamepad`. Pass those results as individual runtime arguments; do not use the first input event or an H700 framebuffer default. Install the rebuilt runtime **and its matching package export**; run package `--check` before replacing the active pair. Retain the prior runtime, package, CLI, profile directory and launcher as one rollback set. This handoff changes no internal partition and does not demonstrate standalone firmware boot.
4. On device check confirm/back, held hat plus stick, shoulders/triggers, idle/reconnect, battery with/without charger, brightness endpoints and audible volume/zero. Check again after a ROM returns. Device acceptance is separate from patch application or package admission.

## Residual owners and removal conditions

Read-only audit of `PocketShell` (including local changes); no deploy or edit there. Source references below are absolute.

| Location | Owner / disposition |
|---|---|
| `PocketShell/app/setting-bridge.ts` | Guest protocol owner: retain semantic compatibility requests until all supported hosts implement unified `SETTING`; never replace them with sysfs reads. |
| `PocketShell/app/system-status.ts` | UI owner: remove stacked-fb geometry heuristic once all SYSTEM producers provide panel geometry rather than virtual surface size. |
| `PocketShell/app/main.tsx` | Demo terminal owner: sample disk names are fixture text, not partition discovery; replace with role labels when updating the demo. |
| `PocketShell/bridge/local-sysinfo.rs`, `PocketShell/bridge/settings.rs` | Desktop host owner: local Linux CPU, memory, DMI, thermal, display, power, network and hostname probes belong to desktop telemetry, not the handheld bridge. Replace on handheld reuse with semantic queries. |
| `PocketShell/config/profile.ts`, `PocketShell/config/profile-trimui.ts` | Package owner: target viewports are compile/admission inputs. Replace separate exports when the package toolchain can generate compatible profiles from BSP geometry. |
| `PocketShell/scripts/deploy-rg34xx.sh` | Deployment owner: process inspection and framebuffer/pan capture are target-specific diagnostics. Remove fixed framebuffer, pan and byte count when a profile-aware capture command exists; do not ship this script in startup. |
| `src/apply-pocketjs-system-info.py`, `src/apply-pocketjs-kanade.py` | SYSTEM and player bridge owners: migrate framebuffer telemetry and player panel control separately; remove probes when `display info` and blank/wake semantics are covered on both targets. |
| `overlay/usr/share/pocketshell/System/compat/bin/heya-control`, `overlay/usr/share/pocketshell/System/compat/bin/rocknix-settings` | Network adapter owner: remaining supplicant/interface and BlueZ logic reports enabled/association state, not just link state. Replace when the network CLI provides equivalent semantics. |
