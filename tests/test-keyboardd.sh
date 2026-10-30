#!/bin/sh
# Exercise keyboardd's Input API the same way a frontend/provider would, using a
# real BusyBox-ish userspace. No device, privileged mount, or other repo needed.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=tools/docker-platform.sh
. "$HERE/tools/docker-platform.sh"

# BASEOS_DOCKER_PLATFORM_HOST is docker's os/arch order, e.g. linux/amd64.
OUT="$HERE/work/keyboardd-test"
rm -rf "$OUT"
mkdir -p "$OUT"
( cd "$HERE/runtime/keyboardd" && \
  GOOS="${BASEOS_DOCKER_PLATFORM_HOST%%/*}" GOARCH="${BASEOS_DOCKER_PLATFORM_HOST#*/}" \
  CGO_ENABLED=0 go build -o "$OUT/keyboardd" ./cmd/keyboardd )

docker run --rm -i --platform "$BASEOS_DOCKER_PLATFORM_HOST" \
  -v "$OUT/keyboardd":/usr/bin/keyboardd:ro \
  alpine:3.20 sh -eu <<'TEST'
apk add --no-cache curl >/dev/null
export PATH=/usr/local/bin:/usr/bin:/bin:/sbin
KEYBOARDD_ADDR=127.0.0.1:8787 /usr/bin/keyboardd &
KP=$!
sleep 0.5

base=http://127.0.0.1:8787
post() { curl -s -X POST "$base$1" -H 'Content-Type: application/json' -d "$2"; }
get()  { curl -s "$base$1"; }
code() { curl -s -o /dev/null -w '%{http_code}' -X POST "$base$1" -H 'Content-Type: application/json' -d "$2"; }

test "$(get /api/health | grep -o '"status":"ok"')" = '"status":"ok"'

# show text with Touch capability -> touch mode
show=$(post /api/keyboard/show '{"layout":"text","capabilities":["Touch"]}')
test "$(echo "$show" | grep -o '"visible":true')" = '"visible":true'
test "$(echo "$show" | grep -o '"inputMode":"touch"')" = '"inputMode":"touch"'

# typing
post /api/keyboard/key '{"key":"h"}' >/dev/null
post /api/keyboard/key '{"key":"i"}' >/dev/null

# submit returns the composed value and hides
sub=$(post /api/keyboard/submit '{}')
test "$(echo "$sub" | grep -o '"value":"hi"')" = '"value":"hi"'
test "$(echo "$sub" | grep -o '"visible":false')" = '"visible":false'

# reserved layout rejected (501)
test "$(code /api/keyboard/show '{"layout":"emoji"}')" = 501

# key while hidden is 409
test "$(code /api/keyboard/key '{"key":"a"}')" = 409

# DPad capability -> dpad mode
show2=$(post /api/keyboard/show '{"layout":"number","capabilities":["DPad","Gamepad"]}')
test "$(echo "$show2" | grep -o '"inputMode":"dpad"')" = '"inputMode":"dpad"'

# Focus Manager: focus auto-shows, blur auto-hides
post /api/keyboard/focus '{"inputId":"field1","layout":"text"}' >/dev/null
test "$(get /api/keyboard/state | grep -o '"visible":true')" = '"visible":true'
post /api/keyboard/blur '{"inputId":"field1"}' >/dev/null
test "$(get /api/keyboard/state | grep -o '"visible":false')" = '"visible":false'

# CORS preflight is what a provider on another origin needs
test "$(curl -s -o /dev/null -w '%{http_code}' -X OPTIONS "$base/api/keyboard/key" \
	-H 'Origin: http://127.0.0.1:5199' -H 'Access-Control-Request-Method: POST')" = 204

kill $KP 2>/dev/null || true
echo 'keyboardd integration tests passed'
TEST
