#!/bin/sh
# Exercise keyboardd's Input API the same way a frontend/provider would, using a
# real busybox environment. No device, privileged mount, or other repo needed.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=tools/docker-platform.sh
. "$HERE/tools/docker-platform.sh"

# Build the keyboardd binary once for the target host platform.
OUT="$HERE/work/keyboardd-test"
rm -rf "$OUT"
mkdir -p "$OUT"
( cd "$HERE/runtime/keyboardd" && GOOS="${BASEOS_DOCKER_PLATFORM_HOST##*/}" GOARCH="${BASEOS_DOCKER_PLATFORM_HOST%%/*}" \
	go build -o "$OUT/keyboardd" ./cmd/keyboardd )

docker run --rm -i --platform "$BASEOS_DOCKER_PLATFORM_HOST" \
  -v "$OUT/keyboardd":/usr/bin/keyboardd:ro \
  alpine:3.20 sh -eu <<'TEST'
apk add --no-cache curl >/dev/null 2>&1 || true
export PATH=/usr/local/bin:/usr/bin:/bin:/sbin
KEYBOARDD_ADDR=127.0.0.1:8787 /usr/bin/keyboardd &
KP=$!
sleep 0.5

base=http://127.0.0.1:8787
# health
test "$(curl -s $base/api/health | grep -o '"status":"ok"')" = '"status":"ok"'

# show text with Touch capability -> touch mode
show=$(curl -s -X POST $base/api/keyboard/show -d '{"layout":"text","capabilities":["Touch"]}')
test "$(echo "$show" | grep -o '"visible":true')" = '"visible":true'
test "$(echo "$show" | grep -o '"inputMode":"touch"')" = '"inputMode":"touch"'

# typing
curl -s -X POST $base/api/keyboard/key -d '{"key":"h"}' >/dev/null
curl -s -X POST $base/api/keyboard/key -d '{"key":"i"}' >/dev/null

# submit returns composed value and hides
sub=$(curl -s -X POST $base/api/keyboard/submit -d '{}')
test "$(echo "$sub" | grep -o '"value":"hi"')" = '"value":"hi"'
test "$(echo "$sub" | grep -o '"visible":false')" = '"visible":false'

# reserved layout rejected (501)
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST $base/api/keyboard/show -d '{"layout":"emoji"}')
test "$code" = 501

# key while hidden is 409
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST $base/api/keyboard/key -d '{"key":"a"}')
test "$code" = 409

# DPad capability -> dpad mode
show2=$(curl -s -X POST $base/api/keyboard/show -d '{"layout":"number","capabilities":["DPad","Gamepad"]}')
test "$(echo "$show2" | grep -o '"inputMode":"dpad"')" = '"inputMode":"dpad"'

# focus auto-shows, blur auto-hides (Focus Manager)
curl -s -X POST $base/api/keyboard/focus -d '{"inputId":"field1","layout":"text"}' >/dev/null
test "$(curl -s $base/api/keyboard/state | grep -o '"visible":true')" = '"visible":true'
curl -s -X POST $base/api/keyboard/blur -d '{"inputId":"field1"}' >/dev/null
test "$(curl -s $base/api/keyboard/state | grep -o '"visible":false')" = '"visible":false'

kill $KP 2>/dev/null || true
echo 'keyboardd integration tests passed'
TEST
