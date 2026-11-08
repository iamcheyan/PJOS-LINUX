from pathlib import Path
p = Path('overlay/usr/sbin/baseos-screen-idle')
t = p.read_text()

# 1. Add config reading
old = '''configured_timeout() {
    value=
    if [ -r /storage/.config/baseos/screen-idle.conf ]; then
        value=$(sed -n 's/^[[:space:]]*timeout[[:space:]]*=[[:space:]]*//p' \\
            /storage/.config/baseos/screen-idle.conf | head -1)
    fi
    if [ -z "$value" ] && [ -r /storage/.config/pocketjs/runtime.conf ]; then
        value=$(awk '
            /^\\[/ { section = $0 }
            section == "[sleep]" && /timeout[[:space:]]*=/ {
                sub(/^[^=]*=[[:space:]]*/, ""); print; exit
            }' /storage/.config/pocketjs/runtime.conf)
    fi
    [ -n "$value" ] || value=$DEFAULT_TIMEOUT
    seconds "$value"
}'''
new = '''configured_timeout() {
    value=
    if [ -r /storage/.config/baseos/screen-idle.conf ]; then
        value=$(sed -n 's/^[[:space:]]*timeout[[:space:]]*=[[:space:]]*//p' \\
            /storage/.config/baseos/screen-idle.conf | head -1)
    fi
    if [ -z "$value" ] && [ -r /storage/.config/pocketjs/runtime.conf ]; then
        value=$(awk '
            /^\\[/ { section = $0 }
            section == "[sleep]" && /^[[:space:]]*timeout[[:space:]]*=/ {
                sub(/^[^=]*=[[:space:]]*/, ""); print; exit
            }' /storage/.config/pocketjs/runtime.conf)
    fi
    [ -n "$value" ] || value=$DEFAULT_TIMEOUT
    seconds "$value"
}

# Auto stop after sustained input inactivity. "never"/0 disables it.
# Reads auto_stop_timeout from screen-idle.conf, or [power] timeout from the
# launcher's runtime.conf (same precedence pattern as screen timeout).
configured_auto_stop_timeout() {
    value=
    if [ -r /storage/.config/baseos/screen-idle.conf ]; then
        value=$(sed -n 's/^[[:space:]]*\\(auto_stop_timeout\\|auto_off_timeout\\)[[:space:]]*=[[:space:]]*//p' \\
            /storage/.config/baseos/screen-idle.conf | head -1)
    fi
    if [ -z "$value" ] && [ -r /storage/.config/pocketjs/runtime.conf ]; then
        value=$(awk '
            /^\\[/ { section = $0 }
            section == "[power]" && /^[[:space:]]*timeout[[:space:]]*=/ {
                sub(/^[^=]*=[[:space:]]*/, ""); print; exit
            }' /storage/.config/pocketjs/runtime.conf)
    fi
    [ -n "$value" ] || value=never
    seconds "$value"
}'''
if old not in t:
    print('anchor1 missing')
    raise SystemExit(1)
t = t.replace(old, new)
print('ok1')

# 2. Add check in main loop
old2 = '''    last=$(stat -c %Y "$STAMP" 2>/dev/null || echo 0)
    now=$(date +%s)
    idle=$(( now - last ))

    if [ "$blanked" = 0 ] && [ "$idle" -ge "$timeout" ]; then'''
new2 = '''    last=$(stat -c %Y "$STAMP" 2>/dev/null || echo 0)
    now=$(date +%s)
    idle=$(( now - last ))

    auto_stop_timeout=$(configured_auto_stop_timeout)
    if [ "$auto_stop_timeout" -gt 0 ] && [ "$idle" -ge "$auto_stop_timeout" ]; then
        log "auto-stop after ${idle}s idle (timeout ${auto_stop_timeout}s)"
        sync
        if [ -x /usr/sbin/baseos-poweroff ]; then
            /usr/sbin/baseos-poweroff 2>/dev/null || /sbin/poweroff 2>/dev/null || :
        else
            /sbin/poweroff 2>/dev/null || :
        fi
        sleep 60
        continue
    fi

    if [ "$blanked" = 0 ] && [ "$idle" -ge "$timeout" ]; then'''
if old2 not in t:
    print('anchor2 missing')
    raise SystemExit(1)
t = t.replace(old2, new2)
print('ok2')

# 3. Update header comment
old3 = '''# Turn the panel backlight off after a period without input, and restore it on
# the next keypress. Only the backlight is touched: nothing is suspended,
# unmounted, throttled or stopped, so playback, downloads and the frontend keep
# running while the screen is dark.
#
# Configuration, in this order of precedence:
#   /storage/.config/baseos/screen-idle.conf   timeout = 30s      (BaseOS)
#   /storage/.config/pocketjs/runtime.conf     [sleep] timeout=30s (launcher UI)
# Accepted values are the launcher's own vocabulary: never, 10s, 30s, 1m, 5m,
# 15m, 30m, 1h. With no configuration at all the default is 30 seconds, so a
# fresh card behaves like a phone instead of staying lit forever.'''
new3 = '''# Turn the panel backlight off after a period without input, and restore it on
# the next keypress. The backlight is the only thing touched for screen blanking:
# nothing is suspended, unmounted, throttled or stopped, so playback, downloads
# and the frontend keep running while the screen is dark.
#
# Screen timeout, in this order of precedence:
#   /storage/.config/baseos/screen-idle.conf   timeout = 30s      (BaseOS)
#   /storage/.config/pocketjs/runtime.conf     [sleep] timeout=30s (launcher UI)
# Accepted values: never, 10s, 30s, 1m, 5m, 15m, 30m, 1h. Default: 30 seconds.
#
# Auto stop (idle device stop), in this order of precedence:
#   /storage/.config/baseos/screen-idle.conf   auto_stop_timeout = never
#   /storage/.config/pocketjs/runtime.conf     [power] timeout=never
# Accepted values: never/off/none/0, 1m, 5m, 10m, 15m, 30m, 1h, 2h. Default: never.
# Uses the same input-idle stamp as screen blanking; any keypress resets it.'''
if old3 not in t:
    print('anchor3 missing')
    raise SystemExit(1)
t = t.replace(old3, new3)
print('ok3')

p.write_text(t)
print('wrote')
