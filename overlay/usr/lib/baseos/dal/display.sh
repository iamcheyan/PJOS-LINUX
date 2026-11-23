#!/bin/sh
dal_display_info() {
    dal_init || return $?
    for k in backend width height bpp rotation_ccw logical_width logical_height vsync brightness_min brightness_max brightness_control outputs; do
        v=$(dal_meta "display.$k" 2>/dev/null) || continue
        printf '%s=%s\n' "$k" "$v"
    done
    value=$(dal_display_brightness_get 2>/dev/null) || value=unknown
    printf 'brightness=%s\n' "$value"
}
dal_display_state() {
    dal_init || return $?
    statefile="${PJOS_RUN_ROOT:-}/run/baseos-display.state"
    state=$(cat "$statefile" 2>/dev/null) || state=lit
    case "$state" in blank|lit) printf '%s\n' "$state";; *) printf 'lit\n';; esac
}
dal_display_node() { dal_meta display.node; }
display_state() { dal_display_state; }
dal_display_helper() {
    for helper in "${PJOS_SYS_ROOT:-}${BASEOS_SBIN_ROOT:-}/usr/sbin/baseos-panel" "${PJOS_DEV_ROOT:-}${BASEOS_SBIN_ROOT:-}/usr/sbin/baseos-panel" /usr/sbin/baseos-panel /mnt/sdcard/System/bin/baseos-panel; do
        [ -x "$helper" ] && { printf '%s\n' "$helper"; return 0; }
    done
    return 1
}
dal_display_path() {
    case "$1" in /sys/*) printf '%s%s\n' "${PJOS_SYS_ROOT:-}" "$1";; /dev/*) printf '%s%s\n' "${PJOS_DEV_ROOT:-}" "$1";; *) printf '%s\n' "$1";; esac
}
dal_display_level_get() {
    control=$(dal_meta display.brightness_control 2>/dev/null || :)
    if [ "$control" = ioctl ]; then
        helper=$(dal_display_helper) || return 3
        level=$($helper level 2>/dev/null) || return 1
        case "$level" in ''|*[!0-9]*) return 3;; esac
        printf '%s\n' "$level"; return 0
    fi
    if [ "$control" = sysfs ]; then
        node=$(dal_meta display.brightness_node 2>/dev/null) || return 3
        node=$(dal_display_path "$node")
        [ -r "$node" ] || return 3
        IFS= read -r level <"$node" || return 1
        case "$level" in ''|*[!0-9]*) return 3;; esac
        printf '%s\n' "$level"; return 0
    fi
    return 4
}
dal_display_brightness_get() {
    dal_init || return $?
    level=$(dal_display_level_get) || return $?
    max=$(dal_meta display.brightness_max 2>/dev/null || printf 255)
    case "$max" in ''|*[!0-9]*) return 6;; esac
    [ "$max" -gt 0 ] && [ "$level" -le "$max" ] || return 6
    printf '%s\n' "$((level * 255 / max))"
}
_dal_display_write_raw() {
    value=$1 control=$2
    case "$control" in
        ioctl) helper=$(dal_display_helper) || return 3; "$helper" level "$value" >/dev/null 2>&1 || return 1;;
        sysfs) node=$(dal_meta display.brightness_node 2>/dev/null) || return 3; node=$(dal_display_path "$node"); [ -w "$node" ] || return 4; printf '%s\n' "$value" >"$node" || return 1;;
        *) return 4;;
    esac
}
_dal_display_lock() {
    lock="${PJOS_RUN_ROOT:-}/run/baseos-display.lock"
    mkdir -p "${lock%/*}" || return 1
    exec 8>"$lock" || return 1
    flock -n 8 || { echo 'display: state lock busy' >&2; return 1; }
}

dal_display_brightness_set() (
    dal_init || return $?
    case "${1:-}" in ''|*[!0-9]*) return 2;; esac
    [ "$1" -le 255 ] || return 2
    min=$(dal_meta display.brightness_min 2>/dev/null || printf 0)
    max=$(dal_meta display.brightness_max 2>/dev/null || printf 255)
    case "$min:$max" in *[!0-9:]*) return 6;; esac
    [ "$min" -le "$max" ] || return 6
    raw=$((min + ($1 * (max - min) + 127) / 255))
    control=$(dal_meta display.brightness_control 2>/dev/null || :)
    _dal_display_lock || return $?
    if [ "$(cat "${PJOS_RUN_ROOT:-}/run/baseos-display.state" 2>/dev/null)" = blank ]; then
        printf '%s\n' "$raw" >"${PJOS_RUN_ROOT:-}/run/baseos-display.raw" || return 1
        return 0
    fi
    _dal_display_write_raw "$raw" "$control"
)
dal_display_blank() (
    dal_init || return $?
    action=${1:-} origin=${2:-manual}
    case "$action" in on|off|toggle) ;; *) return 2;; esac
    case "$origin" in manual|idle) ;; *) return 2;; esac
    _dal_display_lock || return $?
    statefile="${PJOS_RUN_ROOT:-}/run/baseos-display.state"
    marker="${PJOS_RUN_ROOT:-}/run/baseos-display.manual"
    current=$(cat "$statefile" 2>/dev/null || printf lit)
    [ "$current" = blank ] || current=lit
    [ "$action" != toggle ] || { [ "$current" = blank ] && action=off || action=on; }
    control=$(dal_meta display.brightness_control 2>/dev/null || :)
    if [ "$action" = on ]; then
        if [ "$current" = lit ]; then raw=$(dal_display_level_get) || return $?; max=$(dal_meta display.brightness_max 2>/dev/null || printf 255); [ "$max" -gt 0 ] || return 6; normalized=$((raw * 255 / max)); printf '%s\n' "$raw" >"${PJOS_RUN_ROOT:-}/run/baseos-display.raw" || return 1; printf '%s\n' "$normalized" >"${PJOS_RUN_ROOT:-}/run/baseos-display.saved" || return 1; fi
        if [ "$control" = ioctl ]; then helper=$(dal_display_helper) || return 3; "$helper" off >/dev/null 2>&1 || return 1
        else _dal_display_write_raw 0 "$control" || return $?; fi
        printf 'blank\n' >"$statefile" || return 1
        [ "$origin" != manual ] || : >"$marker" || return 1
        return 0
    fi
    [ "$origin" != idle ] || [ ! -e "$marker" ] || return 0
    if [ "$current" = lit ]; then [ "$origin" != manual ] || rm -f "$marker"; return 0; fi
    raw=$(cat "${PJOS_RUN_ROOT:-}/run/baseos-display.raw" 2>/dev/null) || return 3
    case "$raw" in ''|*[!0-9]*) return 6;; esac
    if [ "$control" = ioctl ]; then helper=$(dal_display_helper) || return 3; "$helper" on >/dev/null 2>&1 || return 1; "$helper" level "$raw" >/dev/null 2>&1 || return 1
    else node=$(dal_meta display.brightness_node 2>/dev/null) || return 3; node=$(dal_display_path "$node"); [ -w "$node" ] || return 4; printf '%s\n' "$raw" >"$node" || return 1; fi
    printf 'lit\n' >"$statefile" || return 1
    [ "$origin" != manual ] || rm -f "$marker"
)
dal_display_output() { [ "$1" = list ] || return 2; outputs=$(dal_meta display.outputs 2>/dev/null) || return 3; for output in $outputs; do printf 'output=%s connected=unknown active=unknown\n' "$output"; done; }
dal_display_output_set() { return 4; }
