# Sol code review: PJOS → PocketShell → Kanade

Review resumed 2026-11-13 in that order. Existing uncommitted work was retained.
This pass prioritizes process ownership, shutdown/resume, settings/network
protocols, media selection, concurrent playback, and NAS synchronization. The
ongoing 240×160 UI migration and runtime package budget changes are outside this
pass. This is source and host-test verification; no device deployment or visual
acceptance is claimed.

## PJOS

- **Framebuffer ownership during video exit:** the mpv shell wrapper used a
  signal trap that resumed PocketJS immediately after signaling its child.
  SIGTERM does not imply that mpv has stopped writing the framebuffer. The trap
  now waits for the child before its exit cleanup resumes the UI. A real-process
  fixture delays child termination and verifies that the UI remains stopped
  until output is released; a separate audio fixture checks that the UI stays
  active and the owned playback marker is removed.
- **Stale application resume:** `baseos-save-state` copied persistent
  `last-active` even when the user had returned to the launcher. It now writes
  an app resume only when the current runtime and volatile foreground identity
  exist, and clears stale resume state otherwise. Tests cover a previous app,
  the current app, a missing runtime, and an invalid identity.
- **Force-quit retargeting after a blocking helper:** the Kanade stop request can
  take three seconds, during which the original UI may exit normally. Process
  targets and start times are now captured before that call and revalidated
  before signaling. A real-process test respawns an executable with the same
  name and verifies it is not retargeted.

Validation: new wrapper and save-state tests; hotkeys `go test -race`; existing
screen-idle, force-quit/power/network bridge tests; update-package validation;
poweroff-policy and frontend-session regressions. Update-package tests initially
failed because `/usr/sbin` was absent from PATH, then passed with the existing
system tools on PATH. No packages or system configuration were changed.

## PocketShell

- **Missing Wi-Fi hotspots:** indexing by SSID in a normal JavaScript object
  hid legitimate names such as `__proto__` and `constructor`. A Map preserves
  these names. Missing signal readings no longer become a false 0 dBm, and a
  later valid BSSID replaces an earlier invalid reading. An unsupported scan is
  reported as failure rather than displayed as a hotspot.
- **False settings-write success:** the legacy transport's `Unknown launcher
  action` response was accepted, after which the old readable setting was
  returned as success. It is now rejected explicitly.

Validation: 10 Bun tests across settings, scan parsing and the existing showcase
model; existing Wi-Fi and library model verification scripts. No UI files were
modified and no app bundle was rebuilt by this review.

## Kanade

- **Concurrent framebuffer owners:** concurrent play requests could both launch
  mpv. Playback actions and shutdown are now serialized. Replacement waits for
  the original process to release its output and closes its IPC connection;
  timeout refuses a new launch. A player whose IPC startup fails is retained as
  a stopping owner, blocking retry until its process exits. The redundant second
  signal to an already-ended previous PID was removed. Real IPC child fixtures
  test concurrent replacement, slow exit, connection closure and startup retry.
- **NAS configuration races:** status reads wrote a shared live batch variable,
  and the first concurrent sync could race initialization of its state object.
  State is initialized once and every task gets its own batch snapshot. A
  concurrent configuration-read test runs under the race detector.
- **Missing music and soundtracks during sync:** same-name audio was discarded
  whenever a video existed on the share. Transfer planning now retains both
  video and music, including companion M4A audio. It still excludes covers,
  metadata and incomplete transfers from the media transfer plan.
- **ID collisions:** scanning truncated any filename containing `_p`, merging
  unrelated legitimate IDs. Only a trailing `_p` followed by digits is now
  removed, and an entire identifier is never removed. A fixture checks distinct
  IDs, playlist suffixes and an identifier consisting of `_p12`.
- **Streaming the wrong mode:** a newer audio download could win the generic
  media stream route. Default streaming now prefers video, with
  `?media_type=audio` available for explicit music selection.

Validation: Go suite, Go vet, media race tests, and a static arm64 videod build.
Existing codec policy, sidecar-repair, mode-specific playback and independent
progress tests were retained. Tests use temporary databases/media and disposable
processes; no real library, share, or device was modified.

## Remaining verification and delivery

- Device verification should exercise video replacement, audio screen-off/wake,
  music/video resume, force-quit and launcher shutdown after a normal app exit.
- Ungraceful power loss can still lose the last background progress interval
  (roughly two seconds). Database/media files were not deleted or migrated
  destructively.
- Runtime/UI build and device deployment remain with the integrating agent.
  `/tmp/kanade-videod-reviewed` and `/tmp/pjos-baseos-hotkeys-reviewed` are static
  arm64 review builds. PJOS script changes are `compat/bin/mpv` and
  `baseos-save-state` in the overlay; the integrating agent separately owns the
  launcher process-matching correction and runtime profile changes.
