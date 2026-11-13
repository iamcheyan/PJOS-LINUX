# Launcher force-quit review (2026-11-13)

START+SELECT now reports a one-shot notice after returning to PocketShell:
`已强制关闭「应用名」` in Chinese, with English/Japanese equivalents.
The existing brief toast animates in a global bottom overlay and fades after
about 1.3 seconds. It remains available on settings and system pages.

## Event ownership

- `launch_frontend.sh` clears `/run/baseos-foreground-app` on entry, publishes
  the installed app ID immediately before launching that package, and removes
  it after the child exits. ROM sessions publish the safe generic ID `game`.
  A fallback boot package never inherits an installed app's identity.
- `baseos-hotkeys` snapshots that identity before sending SIGTERM. It writes
  `/run/baseos-force-quit` through a sibling temporary file only after signaling
  a PocketJS runtime or RetroArch successfully. Normal exits and quitting the
  launcher itself do not create notices. The delayed SIGKILL checks only the
  original PIDs and their `/proc` start times, never a newly respawned launcher.
  Dry-run now avoids sending either signal.
- The additive runtime patch exposes `FORCEQUIT`; atomic rename claims a marker,
  validates the ID and removes the claimed file. The UI claims once on mount,
  then displays after its global toast node is ready. Unknown IDs display a
  generic localized app name, never marker contents or ROM paths.

## Verification

`go test ./...` in `src/baseos-hotkeys`, an arm64 static Go build, shell syntax
checks for the launcher and builders, and `python3 tests/test-forcequit-bridge.py`
pass. The latter compiles the real Rust helper and checks consume-once behavior,
invalid-ID disposal and patch idempotence while preserving an existing network
arm. The parent integration task owns the final runtime and PocketShell builds,
deployment and physical START+SELECT verification. No device deployment was
performed as part of this review; a completed device fix must not be inferred.

## Redundancy candidates retained

The catalog's ROMS/GAMESCAN/ROMSCAN fallbacks, launcher short-ID ROM migration,
legacy power/settings command aliases, and the historical full bridge rewrite
appear to overlap newer routes. Their consumers and old SD-card compatibility
have not been fully established, so this review does not remove them. Runtime
builders intentionally use the current baseline plus additive bridge patches;
reapplying the historical whole-bridge rewrite would discard newer behavior.

## Parent integration result

The reviewed hotkeys binary, script, additive runtime bridge and PocketShell
package were deployed together. A genuine SELECT+START hold from Kanade returned
to the launcher and displayed a localized notice; the one-shot marker was gone.
The global notice uses the shared purple/gold square-corner styling and a fixed
320px width. Sol review was explicitly paused by the user and was not resumed.

Kanade shutdown additionally asks the local player service to stop (3s maximum)
before terminating the UI, allowing music progress to be saved and audio stopped.
A missing/idle player never prevents the force-quit operation.
