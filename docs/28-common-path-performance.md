# Common-path performance pass (2026-11-13)

Scope: PJOS frontend handoff, PocketShell settings/status polling, and Kanade
list loading and AV1 filtering. The device was left disconnected as requested;
these are source-level reductions and host checks, not measured handheld FPS or
startup-time claims.

| Path | Before | Now |
| --- | --- | --- |
| Frontend helper cleanup | `kill_matching` started `tr` and `sed` twice for each `/proc` entry on every helper scan. | A shell builtin reads `comm`; only shell-script processes need one cmdline decode. The executable/script-only match still protects unrelated SSH/debug shells. |
| Settings screen | Every 400 ms read all 16 setting keys, including keys backed by external commands. A full pass also ran every 5 s. | The 400 ms pass reads only brightness and volume. The full pass runs on entering settings, after non-level changes, and every 5 s while settings is visible. Level changes read back only those two keys. |
| Other launcher screens | The 5 s pass reread all settings and the complete SYSTEM snapshot even when neither page was visible. | It reads only brightness/volume for hardware control changes. SYSTEM is read when entering its page and refreshed there every 5 s. |
| Kanade list | Each load/tab switch made separate health and library bridge calls, each spawning a helper and making HTTP round trips. | The library response supplies both rows and reachability in one call. |
| MP4 codec filter | A cold MP4 inspection read the first MiB and usually the last MiB before it scanned `moov`. | Valid box tables jump over `mdat` and read `moov` directly. The bounded first/last-window fallback remains for damaged tables; the large-moov tail check remains. Cache invalidation still uses path, size and mtime. |

Validation: frontend helper-match regression and `sh -n`; PocketShell's 10 Bun
tests and SDK check/compile; Kanade's Go suite, `go vet`, arm64 videod build,
and SDK check/compile. The codec test includes both AV1 and H.264 fast-start
MP4s; existing trailing-moov and cache-invalidation tests pass. All three
repositories pass `git diff --check`.

Current local artifacts:

- PocketShell package: `c1c2d5620c0415ec13282feb5046a5646907bdcc16528e64fa04022186d5b845`
- Kanade package: `28cf7ab03519b1accbc0ecd1b4d321789028bbf9cbb5b7ba6f09aebbee32a1a8`
- arm64 videod: `/tmp/kanade-videod-perf`, `cacebcc0aca3016a231277427cc8a7c3ee468bc8572f6ffc49116f0ee9e68b68`

All packages use profile
`sha256:b4eff018558f29f58bf10d76a81e1cbb1a5e7dfb965b59a020562ac797a24241`.
No device deployment or emulator run was done in this pass. On reconnection,
back up active files, deploy the matched runtime/packages/service, and time
startup, settings scrolling and first Kanade list load on the RG34XX.
The UI packages were rebuilt again after adopting the shared PJOS keyboard
theme; see [29-shared-pocketjs-keyboard.md](29-shared-pocketjs-keyboard.md).
