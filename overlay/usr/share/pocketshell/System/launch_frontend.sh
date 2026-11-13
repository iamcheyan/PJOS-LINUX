#!/bin/sh
# BaseOS generic frontend entry. frontend-session invokes this through /bin/sh
# from the SD root and respawns it after return.
set -u

FOREGROUND=/run/baseos-foreground-app
FOREGROUND_APP=
rm -f "$FOREGROUND"
SD=/mnt/sdcard
RUNTIME="$SD/System/pocketjs/bin/pocket-linux-kms"
LAUNCHER_RUNTIME="$SD/System/pocketjs/bin/launcher/pocket-linux-kms"
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

select_runtime() {
    for candidate_runtime in "$LAUNCHER_RUNTIME" "$SD/System/pocketjs/bin/pocket-linux-kms"; do
        [ -x "$candidate_runtime" ] || continue
        RUNTIME=$candidate_runtime
        if check_package "$1"; then
            return 0
        fi
    done
    return 1
}

log "starting; package=$PACKAGE"
if [ -r "$SD/baseos.conf" ]; then
    log "baseos.conf readable; SSH/ADB are enabled by BaseOS defaults"
else
    log "baseos.conf unavailable; SSH/ADB are enabled by BaseOS defaults"
fi

if [ ! -x "$RUNTIME" ] && [ ! -x "$LAUNCHER_RUNTIME" ]; then
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

# App and ROM switching: the launcher bridge asks for another target by writing
# System/pocketjs/active and letting this script restart. Running the child here
# keeps one owner of the panel — no second process racing the launcher.
# A target is either an installed package id (apps/<id>.pocket) or a ROM name
# shipped on the card (apps/<name>.gba|gb|gbc), so the same bridge arm serves
# both without a second command.
kill_matching() {
    helper_pattern=$1
    for helper_dir in /proc/[0-9]*; do
        helper_pid=${helper_dir##*/}
        [ "$helper_pid" = "$$" ] && continue
        # comm is readable by the shell itself. Only shell-script processes
        # need cmdline decoding; launching tr/sed twice for every /proc entry
        # made each frontend handoff needlessly slow.
        IFS= read -r helper_name < "$helper_dir/comm" 2>/dev/null || continue
        case "$helper_name" in
            sh|ash|dash|bash)
                helper_arg1=$(tr '\0' '\n' < "$helper_dir/cmdline" 2>/dev/null | sed -n '2p')
                helper_name=${helper_arg1##*/} ;;
        esac
        case "$helper_pattern" in
            .screen-idle-) case "$helper_name" in .screen-idle-*) kill -9 "$helper_pid" 2>/dev/null || : ;; esac ;;
            *) [ "$helper_name" = "$helper_pattern" ] && kill -9 "$helper_pid" 2>/dev/null || : ;;
        esac
    done
}

ACTIVE="$SD/System/pocketjs/active"
RESUME="$SD/System/pocketjs/../.config/pocketjs/resume.state"
RESUME="/storage/.config/pocketjs/resume.state"
CLEAR_ACTIVE=0
ROM_PLAY=
# One-shot resume after intentional auto power-off/save-state.
if [ ! -r "$ACTIVE" ] && [ -r "$RESUME" ]; then
    rkind=$(sed -n 's/^kind=//p' "$RESUME" | head -1)
    rtarget=$(sed -n 's/^target=//p' "$RESUME" | head -1)
    if [ "$rkind" = "rom" ] && [ -n "$rtarget" ] && [ -f "$rtarget" ]; then
        printf '%s
' "$rtarget" > "$ACTIVE" 2>/dev/null && log "resume: ROM $rtarget"
        rm -f "$RESUME" 2>/dev/null || :
    elif [ "$rkind" = "app" ] && [ -n "$rtarget" ]; then
        printf '%s
' "$rtarget" > "$ACTIVE" 2>/dev/null && log "resume: app $rtarget"
        rm -f "$RESUME" 2>/dev/null || :
    else
        rm -f "$RESUME" 2>/dev/null || :
    fi
fi
if [ -r "$ACTIVE" ]; then
    wanted=$(head -n 1 "$ACTIVE" 2>/dev/null | tr -d '\r')
    # A ROM is named by absolute path when the bridge knows the file (any
    # title, any language); the legacy short-name form copied under apps/ is
    # still honoured when the marker holds a bare id.
    case "$wanted" in
        /*)
            case "$wanted" in
                *"/../"*|*/..|*"/./"*|*/.) log "active marker rejected: $wanted" ;;
                *.[gG][bB][aA]|*.[gG][bB]|*.[gG][bB][cC])
                    if [ -f "$wanted" ]; then
                        ROM_PLAY=$wanted
                        log "ROM requested: $ROM_PLAY"
                        CLEAR_ACTIVE=1
                    fi ;;
            esac ;;
    esac
    wanted=$(printf '%s' "$wanted" | tr -cd 'a-zA-Z0-9._-' | cut -c1-64)
    bare=${wanted%.*}
    if [ -z "$ROM_PLAY" ] && [ -n "$wanted" ] && { [ -f "$SD/apps/$wanted.pocket" ] || [ -f "$SD/apps/$bare.pocket" ]; }; then
        [ -f "$SD/apps/$wanted.pocket" ] || wanted=$bare
        log "installed app requested: $wanted"
        PACKAGE="$SD/apps/$wanted.pocket"
        FOREGROUND_APP=$wanted
        CLEAR_ACTIVE=1
        mkdir -p /storage/.config/pocketjs 2>/dev/null || :
        printf 'kind=app
target=%s
' "$wanted" > /storage/.config/pocketjs/last-active 2>/dev/null || :
    elif [ -z "$ROM_PLAY" ]; then
        for ext in gba gb gbc; do
            source_rom="$SD/apps/$wanted.$ext"
            [ -f "$source_rom" ] || continue
            target_dir="$SD/content/games/homebrew"
            target_rom="$target_dir/$wanted.$ext"
            mkdir -p "$target_dir" 2>/dev/null || :
            if [ -f "$target_rom" ] || cp "$source_rom" "$target_rom" 2>/dev/null; then
                ROM_PLAY=$target_rom
            else
                ROM_PLAY=$source_rom
            fi
            break
        done
        if [ -n "$ROM_PLAY" ]; then
            log "ROM requested: $ROM_PLAY"
            CLEAR_ACTIVE=1
        else
            log "active marker ignored: target=$wanted not installed"
            rm -f "$ACTIVE" 2>/dev/null || :
        fi
    fi
fi

# A ROM is a session, not a package: there is no PocketJS runtime to start.
# Play it here, then return so init respawns this script for the launcher.
if [ -n "$ROM_PLAY" ]; then
    log "launching ROM: $ROM_PLAY"
    # The D-pad is already on ANBERNIC-keys (js0) as ABS_HAT0X/Y, which
    # driver.cfg binds as axes 3 and 4. Do not start pjos-padmerge and do
    # not retarget player 1: that virtual pad never saw these hat events,
    # so every direction in a game was dead.
    if [ -x "$SD/System/bin/pjos-padmerge" ]; then
        kill_matching pjos-padmerge
        killall -9 pjos-padmerge 2>/dev/null || :
    fi
    if [ -x "$SD/System/bin/baseos-hotkeys" ]; then
        kill_matching baseos-hotkeys
        killall -9 baseos-hotkeys 2>/dev/null || :
        rm -f /run/baseos-hotkeys.pid
        "$SD/System/bin/baseos-hotkeys" --power-dev /dev/input/event0 --pad-dev /dev/input/event1 \
            --runtime "pocket-linux-kms,retroarch" </dev/null >/dev/null 2>&1 &
        log "helpers: hotkeys started for ROM session"
    fi
    play=/storage/System/compat/bin/pocket-game-play
    [ -x "$play" ] || play=/usr/bin/pocket-game-play
    printf 'game\n' > "$FOREGROUND.tmp" && mv "$FOREGROUND.tmp" "$FOREGROUND"
    "$play" "$ROM_PLAY" >> "$LOG" 2>&1 || log "ROM player exit=$?"
    rm -f "$FOREGROUND"
    kill_matching pjos-padmerge
    killall -9 pjos-padmerge 2>/dev/null || :
    log "ROM session ended; returning to the launcher"
    rm -f "$ACTIVE" 2>/dev/null || :
    sleep 3
    exit 0
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

# One D-pad source for the runtime: the vendor DTB reports directions as hat
# axes on ANBERNIC-keys and (depending on the driver path) as arrow key codes
# on dierct-keys-polled. pjos-dpad mirrors both into one uinput keyboard device,
# so the runtime only needs to understand arrow keys.
if [ -x "$SD/System/bin/pjos-dpad" ]; then
    dpad=$SD/System/bin/pjos-dpad
elif [ -x /usr/bin/pjos-dpad ]; then
    dpad=/usr/bin/pjos-dpad
else
    dpad=
fi
if [ -n "$dpad" ]; then
    kill_matching pjos-dpad
    # Let the previous daemon's uinput node leave /dev/input first, otherwise the
    # runtime receives two "PJOS D-pad" nodes and every press steps twice.
    tries=0
    while [ "$tries" -lt 15 ]; do
        stale=
        for candidate in /dev/input/event*; do
            [ -e "$candidate" ] || continue
            [ "$(cat "/sys/class/input/${candidate##*/}/device/name" 2>/dev/null)" = "PJOS D-pad" ] && stale=1
        done
        [ -z "$stale" ] && break
        tries=$((tries + 1))
        sleep 0.1
    done
    "$dpad" </dev/null >>"$LOG" 2>&1 &
    tries=0
    while [ "$tries" -lt 15 ]; do
        for candidate in /dev/input/event*; do
            [ -e "$candidate" ] || continue
            [ "$(cat "/sys/class/input/${candidate##*/}/device/name" 2>/dev/null)" = "PJOS D-pad" ] && break 2
        done
        tries=$((tries + 1))
        sleep 0.1
    done
    log "helpers: pad arrows started"
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
    name=$(cat "/sys/class/input/${candidate##*/}/device/name" 2>/dev/null || :)
    # pjos-dpad already publishes these directions as arrow keys.
    [ "$name" = "dierct-keys-polled" ] && continue
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

if ! select_runtime "$PACKAGE"; then
    if [ "$PACKAGE" != "$APPROVED" ] && [ -f "$APPROVED" ] && select_runtime "$APPROVED"; then
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
if [ -x "$SD/System/baseos-screen-idle" ]; then
    kill_matching baseos-screen-idle
    kill_matching .screen-idle-
    rm -f /run/baseos-screen-idle.pid /tmp/.screen-idle-*
    /bin/sh "$SD/System/baseos-screen-idle" </dev/null >/dev/null 2>&1 &
    log "helpers: card screen-idle started"
fi
if [ -x "$SD/System/bin/baseos-hotkeys" ]; then
    kill_matching baseos-hotkeys
    rm -f /run/baseos-hotkeys.pid
    "$SD/System/bin/baseos-hotkeys" --power-dev /dev/input/event0 --pad-dev /dev/input/event1 \
        --runtime "pocket-linux-kms,retroarch" \
        </dev/null >/dev/null 2>&1 &
    log "helpers: hotkeys started"
fi
if [ -x "$SD/System/bin/videod" ] && ! pidof videod >/dev/null 2>&1; then
    mkdir -p /storage/.config/kanade /tmp/kanade-ipc
    export KANADE_MPV=/storage/System/compat/bin/mpv
    export KANADE_IPC=/tmp/kanade-ipc
    setsid "$SD/System/bin/videod" -addr 127.0.0.1:8732 -data /storage/.config/kanade >/tmp/videod.log 2>&1 </dev/null &
    log "helpers: videod started"
fi

# Publish only the installed app that this invocation actually launches.
if [ -n "$FOREGROUND_APP" ] && [ "$PACKAGE" = "$SD/apps/$FOREGROUND_APP.pocket" ]; then
    printf '%s\n' "$FOREGROUND_APP" > "$FOREGROUND.tmp" && mv "$FOREGROUND.tmp" "$FOREGROUND"
fi
started=$(date +%s 2>/dev/null || printf '0')
log "launching runtime; package=$PACKAGE args=$display_args $input_args"
(
    exec "$RUNTIME" --package "$PACKAGE" $display_args $input_args
) >> "$LOG" 2>&1 &
runtime_pid=$!
wait "$runtime_pid"
runtime_status=$?
rm -f "$FOREGROUND"
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
