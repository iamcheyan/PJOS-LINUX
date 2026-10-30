# keyboardd — PJOS Universal Input Framework backend

`keyboardd` is the system service that owns the on-screen keyboard for all PJOS
frontends. Applications never render a keyboard themselves; they call the
**Input API** (HTTP on loopback), and `keyboardd` handles visibility, focus,
layout validation, the composed value, and provider loading/switching.

## Run

```sh
go run ./cmd/keyboardd                 # in-memory (default, no deps)
KEYBOARDD_ADDR=127.0.0.1:8787 go run ./cmd/keyboardd
go build -tags sqlite ./cmd/keyboardd  # optional pure-Go persistence
```

Desktop Debug Mode runs this binary alone — no full PJOS required.

## Input API

See `../../docs/INPUT-API.md` for the full contract. Quick reference:

| Method | Path                     | Purpose              |
|--------|--------------------------|----------------------|
| POST   | `/api/keyboard/show`     | Show with a layout   |
| POST   | `/api/keyboard/hide`     | Hide                 |
| POST   | `/api/keyboard/submit`   | Return value + hide  |
| POST   | `/api/keyboard/focus`    | Focus input → show   |
| POST   | `/api/keyboard/blur`     | Blur input → maybe hide |
| POST   | `/api/keyboard/key`      | Inject key/char      |
| GET    | `/api/keyboard/state`    | Current state        |
| GET/POST | `/api/keyboard/providers`/`/provider` | provider mgmt |

## Architecture

- `keyboardd.go` — `Manager`: state, Focus Manager, layout validation, Provider
  Manager, key composition. Pure standard library.
- `server.go` — HTTP Input API binding.
- `provider_stub.go` — default in-process provider (records hooks; full
  capability superset). Used for headless/desktop and tests.
- `store_sqlite.go` (build tag `sqlite`) — optional `modernc.org/sqlite`
  persistence. Default build is dependency-free.
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
lives in the separate `pjos-keyboard` repository and consumes the Input API over
HTTP, pushing key events back via `POST /api/keyboard/key`. Reserved providers
(`FcitxProvider`/`RimeProvider`/`MozcProvider`/`VoiceProvider`) are future
external integrations — Phase 1 does not implement input methods.

## Capability-driven selection

Navigation mode is derived from capabilities, **never** from a device name:

- `Touch` present → Touch Mode
- else `DPad` present → DPad Mode
- `HardwareKeyboard` feeds keys through the same path

See `../../docs/ARCHITECTURE.md`.

## Test

```sh
go test ./...
./tests/test-keyboardd.sh   # docker/alpine API smoke (mirrors other PJOS tests)
```
