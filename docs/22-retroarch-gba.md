# RG34XX RetroArch + GBA homebrew

## Device proof

RG34XX (PJOS BaseOS 1.5.3, H700, Linux 4.9.170, glibc 2.35) runs Apotris — a GPL-3.0 GBA
homebrew — under a device-compatible RetroArch build. Two framebuffer captures prove it:
the in-game board with `GO`, and the `APOTRIS` / `Press Any Button` title screen. See
[`docs/evidence/2026-11-01-retroarch-gba/`](evidence/2026-11-01-retroarch-gba/).

What does **not** work: RetroArch's `sunxi` video driver. `/dev/disp` opens, but
`DISP_CMD_VERSION` and `DISP_CMD_LAYER_REQUEST` return `EPERM` on this vendor kernel, and
`/dev/dri` does not exist. What does work: the `mali-fbdev` SDL2 from
`ghcr.io/loveretro/h700-toolchain`, whose accelerated `opengles2` renderer presents to
`/dev/fb0` (720×480, 32bpp).

## Building RetroArch

`tools/build-retroarch-h700.sh` clones libretro/RetroArch v1.21.0, configures and builds it
inside the H700 toolchain image, and installs the binary plus the shared libraries it needs
into `overlay/usr/share/pocketshell/System/compat/lib/` (gitignored build output). The result
needs at most `GLIBC_2.28`, so it loads on the device's glibc 2.35.

Two toolchain details the script handles:

- `PKG_CONFIG_PATH` is unset so `PKG_CONFIG_LIBDIR` resolves SDL2 inside the cross sysroot
  instead of `/opt/nextui`; the generated `sdl2.pc` gets a plain `Libs:` line.
- The sysroot has `libSDL2-2.0.so.0` but no `libSDL2.so` linker symlink, so one is created.

Required shared libraries, all from the same toolchain sysroot:
`libSDL2-2.0.so.0`, `libsamplerate.so.0`, `libUMP.so.3.0.0`. The ROCKNIX RetroArch binary
that previously sat in the overlay needs `GLIBC_2.43`, `libass.so.9`, FFmpeg and PulseAudio,
none of which the image ships — it cannot run here.

mGBA (`.gba`) and Gambatte (`.gb`/`.gbc`) are the bundled cores; both stay at or below
`GLIBC_2.33`.

## Input

Measured on the connected RG34XX (PJOS Linux 1.5.3, 2026-11-08) with `EVIOCGABS` and
`JSIOCGAXMAP` / `JSIOCGBTNMAP` on the live nodes. RetroArch's input driver is `sdl2` (keyboard
and the mali-fbdev window). Its joypad driver is `linuxraw`, which reads `/dev/input/js*` and
does not understand hat names such as `h0up`.

### What the kernel actually exposes

`ANBERNIC-keys` is `/dev/input/event1` and `/dev/input/js0`. Face, shoulder, menu, Select and
Start are keys. The D-pad is **not** a key and **not** on `dierct-keys-polled` (`event2`).
The vendor device tree under `soc@03000000/gpio_keys` sets `linux,input-type` to `EV_ABS`:

| Physical | evdev | js0 | RetroArch |
|---|---|---|---|
| A | key 304 | button 0 | b |
| B | key 305 | button 1 | a |
| X | key 306 | button 2 | x, and quick save |
| Y | key 307 | button 3 | y, and quick load |
| L1 | key 308 | button 4 | l |
| R1 | key 309 | button 5 | r |
| Select | key 310 | button 6 | select |
| Start | key 311 | button 7 | start |
| Menu | key 312 | button 8 | menu_toggle |
| L2 | key 314 | button 9 | backlight down, one step per tap |
| R2 | key 315 | button 10 | backlight up, one step per tap |
| Left / Right | `ABS_HAT0X` (0x10), value −1 / +1 | axis 3 | `left_axis = "-3"`, `right_axis = "+3"` |
| Up / Down | `ABS_HAT0Y` (0x11), value −1 / +1 | axis 4 | `up_axis = "-4"`, `down_axis = "+4"` |

`js0` also advertises axes 0–2 (`ABS_RX`, `ABS_RY`, `ABS_RZ`). They sit at 0. Binding the
D-pad to axis 0 or 1 makes every direction look dead. `linuxraw` scales a hat value of ±1
through joydev's correction (min −1, max +1) to about ±32767, which passes the default 0.5
axis threshold.

`dierct-keys-polled` (`event2`) is a second keyboard-like node. The launcher still opens it.
It is not the node RetroArch's joypad driver has to read for the D-pad.

### Why directions died inside a game

`launch_frontend.sh` used to start `pjos-padmerge`, which built a virtual `PJOS Pad` and
rewrote `input_player1_joypad_index` to that js node. The merger copied face buttons and
listened for `KEY_UP` / `DOWN` / `LEFT` / `RIGHT` on `event2`. The physical D-pad never sends
those keys; it sends the hat axes on `event1`, which the merger ignored. `driver.cfg` then
bound directions to axes 0 and 1 of the virtual pad. Face buttons still worked, because those
keys were forwarded. Directions did not.

The game path no longer starts the merger and no longer rewrites the joypad index. Player 1
stays on `js0`. The binds live in
`overlay/usr/share/pocketshell/System/compat/share/retroarch/driver.cfg`
(`input_autodetect_enable = false`, so a profile that still says `h0up` cannot override them).

### Select, Start, and leaving the game

Select and Start are ordinary buttons 6 and 7. `baseos-hotkeys` (card copy,
`System/bin/baseos-hotkeys`) also watches `event1`, but it does not grab the device, so a
normal press still reaches RetroArch.

Holding **Select and Start together for 1.5 s** is the quit combo (`comboHold` in
`src/baseos-hotkeys/main.go`). The helper sends `SIGTERM` to `retroarch` or
`pocket-linux-kms`, then `SIGKILL` if that process is still there 1.5 s later.
`launch_frontend.sh` is waiting on the player; when it exits, init respawns
`frontend-session` and the launcher comes back. A shorter press does nothing. RetroArch's own
instant Select+Start exit is not bound.

On this device, 2026-11-08 11:19:43 and 11:22:12, `/tmp/baseos-hotkeys.log` recorded
`SELECT+START held 1.5s` and `SIGTERM retroarch`. The frontend log then says
`ROM session ended; returning to the launcher`, and `pocket-linux-kms` was running again.

### GBA quick save and quick load

`driver.cfg` turns the hotkey modifier off (`input_enable_hotkey_btn = "nul"`) and binds:

| Physical | js button | RetroArch |
|---|---|---|
| X | 2 | `input_save_state_btn` |
| Y | 3 | `input_load_state_btn` |

States go to `/storage/pocketshell/states/mGBA/<rom>.state`. During the Zelda session the
frontend log recorded both `Saving state` and `Loading state` for
`zelda-minish-cap-zh1.state` (405592 bytes). The file on the card was updated at 11:21, while
that game was in the foreground.

### L2 / R2 brightness

L2 and R2 are not GBA buttons. While RetroArch's command line contains the `.gba`
ROM, `baseos-hotkeys` steps the panel backlight: L2 calls `baseos-panel down`, R2
calls `baseos-panel up`. A tap is one step. Holding the key waits 380 ms, then
repeats every 150 ms. The launcher does not use these keys for brightness, and a
press that only wakes a blanked panel does not also change the level.

The backlight is the display driver's PWM, not `/sys/class/disp/disp/attr/enhance_bright`
and not the `/dev/disp` brightness ioctls (those return `EPERM`). `baseos-panel`
writes `setbl` for `lcd0` through `/sys/kernel/debug/dispdbg`, then checks
`backlight(N)` in `/sys/class/disp/disp/attr/sys`. Levels are 0..255. `down` / `up`
move by 15 and do not go below 10, so L2 cannot turn the panel off. Blanking stays
with `off` / `on` (power key and `baseos-screen-idle`).

A successful `level N`, `up`, or `down` with a level above 0 stores that number in
`/run/panel.level`. `off` records the live read-back, writes `setbl 0`, and creates
`/run/panel.off`. `on` restores the stored level and refreshes `/run/screen-idle.stamp`.
Screen idle reads the same helper, so a level chosen in a GBA game is the level
idle blanking restores.

`driver.cfg` binds L2 and R2 to `nul`. The core does not see them. Keys 314 and 315
are the shoulders on this board (Linux calls those codes `BTN_SELECT` / `BTN_START`).
Select and Start remain 310 and 311, and the quit combo listens only to that pair.
Holding L2 and R2 does not leave the game.

## Audio

The bundled frontend reports a garbage ALSA period/buffer (`Buffer size: …548005464848
frames`) and its synchronous audio thread then blocks the whole frame loop: RetroArch sits
at 0 % CPU with a frozen picture. `driver.cfg` therefore sets `audio_driver = "null"` until a
working sink ships. Games run and render without sound; removing that line re-introduces the
stall.

## ROM handoff to the supervisor

The launcher owns `/dev/fb0`, so an emulator cannot simply be forked alongside it.

1. A card with `romPath` calls the bridge `ROMLAUNCH\t<absolute-path>`
   (`ROM\tlaunch\t<path>` is tried as a fallback for older bridges).
2. The bridge checks the file, then starts `pocketshell-play <path>` detached through
   `systemd-run` (`--unit/--collect/--no-block` are dropped by the BaseOS shim, which
   `setsid`s the command instead).
3. `pocketshell-play` writes the ROM's absolute path into
   `/mnt/sdcard/System/pocketjs/active` and SIGKILLs the launcher runtime. It draws nothing.
4. `launch_frontend.sh` is blocked in `wait "$runtime_pid"`; it respawns, reads the marker
   (an absolute path is played as-is; a bare id still resolves to `$SD/apps/<id>.gba`), and
   runs `pocket-game-play <rom>` synchronously.
5. When RetroArch exits the marker is cleared and the script exits; init respawns
   `frontend-session`, which brings the launcher back.

Apotris ships in the image at
`/usr/share/pocketshell/System/pocketjs/apps/apotris.gba`. `frontend-session` seeds it to
`$SD/apps/apotris.gba` on first boot and `launch_frontend.sh` copies it into
`$SD/content/games/homebrew/apotris.gba`, where the scanner indexes it.
