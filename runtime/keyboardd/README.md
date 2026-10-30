# keyboardd — PJOS Universal Input Framework backend

`keyboardd` is the system service that owns the on-screen keyboard for all PJOS
frontends. Applications never render a keyboard themselves; they call the
**Input API** (HTTP on loopback), and `keyboardd` handles visibility, focus,
layout validation, the composed value, and provider loading/switching.

The full contract — endpoints, state, provider interface, capability model — is in
[`docs/16-keyboardd-input-framework.md`](../../docs/16-keyboardd-input-framework.md).
The provider UI lives in the separate `pjos-keyboard` repository; the coordination
and app-integration docs live in the PJOS input-framework repository.

## Run

```sh
go test ./...
go run ./cmd/keyboardd                  # in-memory, no dependencies
KEYBOARDD_ADDR=127.0.0.1:8787 go run ./cmd/keyboardd
go build -tags sqlite ./cmd/keyboardd   # optional pure-Go persistence
```

Desktop Debug Mode runs this binary alone — no full PJOS image required.

## Input API

| Method | Path                     | Purpose                 |
|--------|--------------------------|-------------------------|
| POST   | `/api/keyboard/show`     | Show with a layout      |
| POST   | `/api/keyboard/hide`     | Hide                    |
| POST   | `/api/keyboard/submit`   | Return value + hide     |
| POST   | `/api/keyboard/focus`    | Focus input → show      |
| POST   | `/api/keyboard/blur`     | Blur input → maybe hide |
| POST   | `/api/keyboard/key`      | Inject key/char         |
| GET    | `/api/keyboard/state`    | Current state           |
| GET/POST | `/api/keyboard/providers` / `/provider` | provider management |

CORS preflight is answered because the provider runs on another origin.

## Architecture

- `keyboardd.go` — `Manager`: state, Focus Manager, layout validation, Provider
  Manager, key composition. Pure standard library.
- `server.go` — HTTP Input API binding (+ CORS).
- `provider_stub.go` — default in-process provider (records hooks; full
  capability superset). Used for headless/desktop and tests.
- `store_sqlite.go` (build tag `sqlite`) — optional `modernc.org/sqlite`
  persistence. The default build is dependency-free.
- `cmd/keyboardd` — service entrypoint.

## Provider contract

```go
type KeyboardProvider interface {
    Name() string
    Capabilities() []Capability
    OnShow(req ShowRequest, st State)
    OnHide(st State)
    OnKey(key string, st State)
    OnSubmit(value string, st State)
}
```

The default provider is `stub`. The real UI provider (`PocketKeyboardProvider`)
lives in `pjos-keyboard` and consumes this API over HTTP, pushing keys back via
`POST /api/keyboard/key`. Reserved providers (`FcitxProvider`/`RimeProvider`/
`MozcProvider`/`VoiceProvider`) are future external integrations — Phase 1 does not
implement input methods.

## Capability-driven selection

Navigation mode is derived from capabilities, **never** from a device name:

- `Touch` present → Touch Mode
- else `DPad` present → DPad Mode
- `HardwareKeyboard` feeds keys through the same path

## Test

```sh
go test ./...              # unit + HTTP API + CORS
./tests/test-keyboardd.sh  # docker/alpine API smoke (mirrors other PJOS tests)
```
