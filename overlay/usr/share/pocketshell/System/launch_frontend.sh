#!/bin/sh
# BaseOS generic frontend entry. frontend-session invokes this through /bin/sh
# from the SD root and respawns it after return.
set -u

SD=/mnt/sdcard
RUNTIME="$SD/System/pocketjs/bin/pocket-linux-kms"
PACKAGE="$SD/System/pocketjs/apps/boot.pocket"
APPROVED="$SD/System/pocketjs/apps/boot.approved.pocket"
LOG=/tmp/pocketjs-frontend.log
FAILURES=/tmp/pocketjs-frontend-failures
COMPAT="$SD/System/compat"
PATH="$COMPAT/bin:$COMPAT/usr/bin:$PATH"
export PATH

log() {
    timestamp=$(date '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || printf unknown-time)
    printf '%s %s\n' "$timestamp" "$*" >> "$LOG" 2>/dev/null || :
}

read_failures() {
    failures=0
    if [ -r "$FAILURES" ]; then
        read -r failures < "$FAILURES" || failures=0
    fi
    case "$failures" in ''|*[!0-9]*) failures=0 ;; esac
}

backoff() {
    read_failures
    failures=$((failures + 1))
    printf '%s\n' "$failures" > "$FAILURES" 2>/dev/null || :
    if [ "$failures" -ge 3 ]; then
        log "failure streak=$failures; sleeping 30 seconds before respawn"
        sleep 30
    else
        sleep 3
    fi
}

check_package() {
    admission_output=$("$RUNTIME" --package "$1" --check 2>&1)
    admission_status=$?
    log "admission package=$1 exit=$admission_status output=$admission_output"
    return "$admission_status"
}

log "starting; package=$PACKAGE"
if [ -r "$SD/baseos.conf" ]; then
    log "baseos.conf readable; SSH/ADB are enabled by BaseOS defaults"
else
    log "baseos.conf unavailable; SSH/ADB are enabled by BaseOS defaults"
fi

if [ ! -x "$RUNTIME" ]; then
    log "runtime missing or not executable: $RUNTIME"
    backoff
    exit 1
fi
if [ ! -f "$PACKAGE" ]; then
    if [ -f "$APPROVED" ]; then
        log "primary package missing; using approved fallback"
        PACKAGE=$APPROVED
    else
        log "package missing: $PACKAGE"
        backoff
        exit 1
    fi
fi

# Installed-app switching: the launcher bridge asks for another package by
# writing System/pocketjs/active and letting this script restart. Running the
# child here keeps one owner of the panel — no second runtime racing the launcher.
ACTIVE="$SD/System/pocketjs/active"
CLEAR_ACTIVE=0
if [ -r "$ACTIVE" ]; then
    wanted=$(tr -cd 'a-zA-Z0-9._-' < "$ACTIVE" 2>/dev/null | cut -c1-64)
    if [ -n "$wanted" ] && [ -f "$SD/apps/$wanted.pocket" ]; then
        log "installed app requested: $wanted"
        PACKAGE="$SD/apps/$wanted.pocket"
        CLEAR_ACTIVE=1
    else
        log "active marker ignored: app=$wanted not installed"
        rm -f "$ACTIVE" 2>/dev/null || :
    fi
fi

card=
for candidate in /dev/dri/card0 /dev/dri/card1; do
    if [ -e "$candidate" ]; then
        card=$candidate
        break
    fi
done
if [ -n "$card" ]; then
    log "display: DRM card=$card"
    display_args="--card $card"
else
    log "display: fbdev /dev/fb0"
    display_args="--fb /dev/fb0"
fi

inputs=
add_input() {
    candidate=$1
    case " $inputs " in
        *" $candidate "*) return 0 ;;
    esac
    inputs="$inputs $candidate"
}
# Prefer ANBERNIC-keys, then add the remaining event nodes (the D-pad is a
# separate gpio-keys device on event2).
for candidate in /dev/input/event*; do
    [ -e "$candidate" ] || continue
    name=$(cat "/sys/class/input/${candidate##*/}/device/name" 2>/dev/null || :)
    [ "$name" = "ANBERNIC-keys" ] && add_input "$candidate"
done
for candidate in /dev/input/event*; do
    [ -e "$candidate" ] || continue
    add_input "$candidate"
done
if [ -n "$inputs" ]; then
    input_args=
    for candidate in $inputs; do
        input_args="$input_args --input $candidate"
    done
    log "inputs:$inputs"
else
    log "input: no evdev device found; runtime will probe /dev/input"
    input_args=
fi

if [ ! -d /storage ]; then
    if mkdir -p /storage 2>/dev/null; then
        log "created /storage mount point"
    else
        log "WARNING: could not create /storage mount point"
    fi
fi

if [ -d /storage ] && command -v mountpoint >/dev/null 2>&1 \
    && ! mountpoint -q /storage 2>/dev/null; then
    if mount --bind "$SD" /storage >> "$LOG" 2>&1; then
        log "bound $SD to /storage for the compiled PocketShell bridge"
    else
        log "WARNING: could not bind SD at /storage; launcher state and bridge paths may be unavailable"
    fi
else
    log "/storage bind skipped (mount point missing or already mounted)"
fi

if ! check_package "$PACKAGE"; then
    if [ "$PACKAGE" != "$APPROVED" ] && [ -f "$APPROVED" ] && check_package "$APPROVED"; then
        log "primary package rejected; using approved fallback $APPROVED"
        PACKAGE=$APPROVED
    else
        log "package admission failed; runtime will not be started"
        backoff
        exit 1
    fi
fi

# Sleep and hotkey helpers are kept on the card so they can be fixed without
# rebuilding the (read-only) OS image. rcS starts the image copies; kill every
# instance of them here — image and card, by cmdline — and start exactly one card
# copy each. Two idle daemons fight over the panel and the screen never sleeps.
kill_matching() {
    helper_pattern=$1
    for helper_dir in /proc/[0-9]*; do
        helper_pid=${helper_dir##*/}
        [ "$helper_pid" = "$$" ] && continue
        helper_cmd=$(tr '\0' ' ' < "$helper_dir/cmdline" 2>/dev/null) || continue
        case "$helper_cmd" in
        *"$helper_pattern"*) kill -9 "$helper_pid" 2>/dev/null || : ;;
        esac
    done
}

if [ -x "$SD/System/baseos-screen-idle" ]; then
    kill_matching baseos-screen-idle
    rm -f /run/baseos-screen-idle.pid
    /bin/sh "$SD/System/baseos-screen-idle" </dev/null >/dev/null 2>&1 &
    log "helpers: card screen-idle started"
fi
if [ -x "$SD/System/bin/baseos-hotkeys" ]; then
    kill_matching baseos-hotkeys
    rm -f /run/baseos-hotkeys.pid
    "$SD/System/bin/baseos-hotkeys" --power-dev /dev/input/event0 --pad-dev /dev/input/event1 \
        </dev/null >/dev/null 2>&1 &
    log "helpers: hotkeys started"
fi

started=$(date +%s 2>/dev/null || printf '0')
log "launching runtime; package=$PACKAGE args=$display_args $input_args"
(
    exec "$RUNTIME" --package "$PACKAGE" $display_args $input_args
) >> "$LOG" 2>&1 &
runtime_pid=$!
wait "$runtime_pid"
runtime_status=$?
finished=$(date +%s 2>/dev/null || printf '0')
log "PocketJS exit code=$runtime_status"
if [ "$CLEAR_ACTIVE" = 1 ]; then
    rm -f "$ACTIVE" 2>/dev/null || :
    log "app $PACKAGE exited; returning to the launcher"
fi
if [ "$started" -gt 0 ] && [ "$finished" -ge $((started + 10)) ]; then
    printf '0\n' > "$FAILURES" 2>/dev/null || :
    log "runtime ran for $((finished - started))s; clearing failure streak"
    sleep 3
else
    backoff
fi
exit "$runtime_status"
