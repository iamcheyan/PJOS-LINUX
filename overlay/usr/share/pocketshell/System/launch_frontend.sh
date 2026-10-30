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
if [ "$started" -gt 0 ] && [ "$finished" -ge $((started + 10)) ]; then
    printf '0\n' > "$FAILURES" 2>/dev/null || :
    log "runtime ran for $((finished - started))s; clearing failure streak"
    sleep 3
else
    backoff
fi
exit "$runtime_status"
