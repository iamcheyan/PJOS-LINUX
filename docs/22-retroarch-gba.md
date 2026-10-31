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

The device reports one joystick, `ANBERNIC-keys`, with 15 buttons, 6 axes and 1 hat
(`/dev/input/js0`). The device run that produced the screenshots used explicit SDL2 button
bindings with `input_autodetect_enable = false`, which avoids a crash in RetroArch's joypad
initialisation on this device. Button *events* inside RetroArch are not yet verified; treat
in-game control as unproven until someone presses buttons on the panel and records the result.

The bundled `test.gba`, `test.gb` and `test.gbc` are emulator diagnostic ROMs (mGBA and
Gambatte test images). Their screens are not evidence of a running game.

## Image integration

`build-rootfs.sh` installs, when the vendor artifacts are present under
`overlay/usr/share/pocketshell/System/compat`:

| Path | What |
|---|---|
| `/usr/bin/retroarch` | frontend |
| `/usr/lib/libretro/mgba_libretro.so`, `gambatte_libretro.so` | cores |
| `/usr/lib/libSDL2-2.0.so.0`, `libsamplerate.so.0`, `libUMP.so.3.0.0` (+ `libUMP.so.3` link) | runtime libraries |
| `/usr/share/retroarch/retroarch.cfg` | device-tuned defaults |
| `/usr/bin/pocket-game-play` | ROM → core → RetroArch |
| `/usr/bin/pocket-gamehub-play`, `pocketshell-games` | compat helpers |

All of these live in the root filesystem, so **a SYSTEM image build and flash is required**
for a fresh card. This repository never flashes the device, and no flashing was performed for
this work.

`pocket-game-play <rom>` validates that the path is under a scanned games root
(`/storage/content/games`, `/storage/roms`, `/storage/games-internal/roms`,
`/storage/games-external/roms`, `/media/...`), rejects `.`/`..` components, picks mGBA for
`.gba` and Gambatte for `.gb`/`.gbc`, then execs RetroArch.

## ROM handoff to the supervisor

The launcher owns `/dev/fb0`, so an emulator cannot simply be forked alongside it. The flow:

1. A PocketJS app calls the bridge `ROM\tlaunch\t<absolute-path>`.
2. The bridge validates the path and extension, writes it to
   `/mnt/sdcard/System/pocketjs/game-active`, then kills its own runtime after 0.4 s —
   the same handoff the existing `LAUNCH\t<app>` command uses.
3. `launch_frontend.sh` is already blocked in `wait "$runtime_pid"`; once the runtime is gone
   it owns the panel, reads the marker, deletes it, and runs
   `/usr/bin/pocket-game-play <rom>` synchronously.
4. When RetroArch exits, the script clears the app marker and exits; busybox init respawns
   `frontend-session`, which restarts the boot package (the launcher).

Apotris itself is shipped in the image at
`/usr/share/pocketshell/System/pocketjs/apps/apotris.gba`. `frontend-session` installs it to
`$SD/apps/apotris.gba` on first boot, and `launch_frontend.sh` copies it into
`$SD/content/games/homebrew/apotris.gba`, which the games scanner already indexes. That makes
it selectable from the launcher's library and from GameHub.
