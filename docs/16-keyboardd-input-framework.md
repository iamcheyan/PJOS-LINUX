# 13 — keyboardd and the Universal Input Framework

`runtime/keyboardd` is a small system service that owns the on-screen keyboard for
every frontend. Applications never render a keyboard themselves: they call the
Input API over loopback HTTP, and `keyboardd` owns visibility, focus, the composed
value, layout validation, and provider selection. The default UI provider lives in
a separate repository (`pjos-keyboard`).

This document is the contract as implemented in this repository. The cross-repo
coordination docs (architecture, integration contract with the Pocket apps) live in
the PJOS input-framework coordination repository.

## Layers

```
app / frontend ── pjos.keyboard.show|hide|submit ──► keyboardd (Input API)
                                                       │
                                    Show/Hide/Render/Submit + keys
                                                       ▼
                                              KeyboardProvider
                            (stub in-tree; pjos-keyboard in production)
```

## Input API

Loopback HTTP, JSON. Default address `127.0.0.1:8787` (`KEYBOARDD_ADDR`).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | liveness (`{"status":"ok"}`) |
| POST | `/api/keyboard/show` | show with a layout |
| POST | `/api/keyboard/hide` | hide |
| POST | `/api/keyboard/submit` | return composed value, hide, clear focus |
| POST | `/api/keyboard/focus` | focus an input → auto-show |
| POST | `/api/keyboard/blur` | blur an input → auto-hide when none focused |
| POST | `/api/keyboard/key` | inject a key/char |
| GET | `/api/keyboard/state` | full state |
| GET | `/api/keyboard/render` | active provider's drawing spec |
| GET | `/api/keyboard/providers` | registered providers |
| POST | `/api/keyboard/provider` | switch active provider |

CORS is answered (`OPTIONS` → 204, `Access-Control-Allow-Origin: *`) because the
provider normally runs on a different origin from the service.

### Show

```json
{
  "layout": "text",
  "value": "",
  "placeholder": "Search",
  "secure": false,
  "capabilities": ["Touch"],
  "theme": "dark"
}
```

Layouts implemented in Phase 1: `text`, `number`, `url`. `number` is the layout for
passwords/PINs/ports/codes; use `secure: true` to mask. Reserved names (`search`,
`password`, `emoji`, `voice`, `ai`) answer **501**; unknown names answer **400**.

### Key tokens

Printable characters compose literally (case preserved). Control tokens
(case-insensitive): `backspace`, `space`, `enter`, `clear`, `layout:switch`, `hide`.
A key while the keyboard is hidden answers **409**.

## State

```json
{
  "visible": true,
  "layout": "text",
  "value": "",
  "placeholder": "Search",
  "secure": false,
  "capabilities": ["Touch"],
  "inputMode": "touch",
  "focusedInput": "",
  "provider": "stub",
  "theme": "dark"
}
```

`inputMode` is derived from capabilities only — never from a device name:

- `Touch` → `touch`
- else `DPad` → `dpad`
- otherwise `touch`

## Providers

```go
type KeyboardProvider interface {
    Name() string
    Capabilities() []Capability

    Show(req ShowRequest, st State) RenderSpec
    Hide(st State)
    Render(st State) RenderSpec
    Submit(value string, st State)

    // state-change notifications emitted around the calls above
    OnShow(req ShowRequest, st State)
    OnHide(st State)
    OnKey(key string, st State)
    OnSubmit(value string, st State)
}
```

`Render` is side-effect free: it returns a `RenderSpec` (layout, input mode, value,
placeholder, secure flag, capabilities, theme, visibility, focus) instead of
driving a display, so a headless provider can answer it without a surface.
`GET /api/keyboard/render` exposes the same spec.

`stub` is the in-tree provider: it records hooks, returns a `RenderSpec`, draws
nothing, and declares the full capability set. It is what headless/desktop hosts and the tests use, and it is the fallback if
a real provider fails to load. `FcitxProvider`/`RimeProvider`/`MozcProvider`/
`VoiceProvider` are future external integrations; Phase 1 implements no input
methods (no pinyin/wubi/Japanese/voice/AI/prediction/emoji/swipe).

## Persistence

In-memory by default, so the zero-dependency build is pure standard library.
`-tags sqlite` adds `modernc.org/sqlite` (pure Go, no cgo) and `KEYBOARDD_DB` then
persists state. Phase 1 needs no persistence; the hook exists for per-device
profiles later.

## Boot wiring

`overlay/usr/sbin/frontend-session` runs `/usr/sbin/keyboardd-launch.sh` once a
frontend is found, immediately before handing the display to it. USB-storage mode
returns earlier, so the service never starts while the card is exported to a host.

The glue is deliberately non-blocking:

- a missing `/usr/bin/keyboardd` logs and exits 0 — the boot continues and the
  frontend keeps whatever input it had;
- the service is detached (`setsid`, stdin from `/dev/null`) because the session
  `exec`s the frontend, which would otherwise take the shell's children down;
- a second call detects the running process and does nothing.

`build-rootfs.sh` chmods and guard-checks the glue alongside the other boot
scripts, so a non-executable copy fails the rootfs build instead of silently
skipping.

## Running it standalone (Desktop Debug)

```sh
cd runtime/keyboardd
go test ./...
go run ./cmd/keyboardd                 # 127.0.0.1:8787
```

No device and no full PJOS image are needed to develop against it.
`overlay/usr/sbin/keyboardd-launch.sh` is the init-time glue; it starts the service
if the binary exists and never touches other services or the display stack.

## Tests

- `go test ./...` — manager, layout validation, focus, provider switching, hooks,
  capability→mode, key composition, HTTP API, CORS.
- `tests/test-keyboardd.sh` — builds the binary and drives the API from an
  `alpine:3.20` container with curl (same pattern as the other runtime tests),
  then exercises the boot glue: missing binary, first start, and idempotency.

## Not in scope here

Real touchscreen/e-ink/DPad hardware, input-method engines, and installing anything
into a running system image. See `pjos-keyboard` for the provider UI and
`pjos-input-framework` for the coordination and integration contract.
