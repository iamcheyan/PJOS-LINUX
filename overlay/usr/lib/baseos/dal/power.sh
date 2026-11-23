#!/bin/sh
dal_power_supply_path() { case "$1" in /sys/*) printf '%s%s\n' "${PJOS_SYS_ROOT:-}" "$1";; *) printf '%s\n' "$1";; esac; }
dal_power_battery() {
    dal_init || return $?
    path=$(dal_meta power.battery 2>/dev/null) || return 3
    case "$path" in no) return 4;; unknown) return 3;; esac
    path=$(dal_power_supply_path "$path")
    [ -r "$path/capacity" ] || return 3
    capacity=$(cat "$path/capacity" 2>/dev/null) || return 1
    case "$capacity" in ''|*[!0-9]*) return 3;; esac
    [ "$capacity" -le 100 ] || return 6
    present=$(cat "$path/present" 2>/dev/null || printf 1)
    status=$(cat "$path/status" 2>/dev/null || printf Unknown)
    voltage=$(cat "$path/voltage_now" 2>/dev/null || printf unknown)
    health=$(cat "$path/health" 2>/dev/null || printf Unknown)
    case "$present" in 0) present=no;; *) present=yes;; esac
    case "$voltage" in ''|*[!0-9]*) voltage=unknown;; esac
    case "$status" in Charging|Discharging|Full|'Not charging'|Unknown) ;; *) status=Unknown;; esac
    case "$health" in Good|Unknown) ;; *) health=Unknown;; esac
    printf 'present=%s\ncapacity=%s\nstatus=%s\nvoltage_uv=%s\nhealth=%s\n' "$present" "$capacity" "$status" "$voltage" "$health"
}
dal_power_charger() {
    dal_init || return $?
    path=$(dal_meta power.charger 2>/dev/null) || return 3
    case "$path" in no) return 4;; unknown) return 3;; esac
    path=$(dal_power_supply_path "$path")
    [ -r "$path/online" ] || return 3
    online=$(cat "$path/online" 2>/dev/null) || return 1
    case "$online" in 0|1) ;; *) return 3;; esac
    name=${path##*/}
    printf 'online=%s\nname=%s\n' "$online" "$name"
}
dal_power_supplies() {
    dal_init || return $?
    root="${PJOS_SYS_ROOT:-}/sys/class/power_supply"
    found=0
    for supply in "$root"/*; do
        [ -d "$supply" ] || continue
        name=${supply##*/}; type=$(cat "$supply/type" 2>/dev/null || printf unknown)
        case "$name$type" in *[!A-Za-z0-9_.-]*) return 6;; esac
        printf 'supply=%s type=%s\n' "$name" "$type"; found=1
    done
    [ "$found" -eq 1 ] || return 3
}
# Only source an installed adapter, never a command or path from profile.env.
dal_soc_hook() {
    hook=${BASEOS_SOC_HOOK:-/etc/init.d/soc-hw-init}
    [ -r "$hook" ] || return 3
    SOC_ID=
    . "$hook"
    [ "$SOC_ID" = "$DAL_soc" ] || return 6
}
dal_power_boot_reason() (
    dal_init || exit $?
    dal_soc_hook || exit $?
    command -v soc_boot_reason >/dev/null || exit 3
    boot_mode=
    soc_boot_reason || exit 3
    case "$boot_mode" in 0) reason=normal;; 1) reason=charger;; *) exit 3;; esac
    printf 'reason=%s\nsource=soc-hook\n' "$reason"
)
dal_power_gate() {
    value=$(dal_meta "$1") || return $?
    case "$value" in yes) return 0;; no) return 4;; unknown) return 3;; *) return 6;; esac
}
dal_power_action() {
    dal_init || return $?
    case "$1" in suspend) dal_power_gate feature.suspend || return $?;;
        poweroff|reboot) dal_power_gate "power.$1" || return $?;; *) return 2;; esac
    [ ! -e "${PJOS_RUN_ROOT:-}/run/usb-storage-device" ] || return 5
    case "$1" in
        suspend) state=${PJOS_SYS_ROOT:-}/sys/power/state
            [ -f "$state" ] || return 3
            grep -qw mem "$state" || return 4
            printf 'mem\n' > "$state" || return 1;;
        *) helper=${BASEOS_SBINDIR:-/usr/sbin}/baseos-$1
            [ -x "$helper" ] || return 3
            "$helper" || return 1;;
    esac
}
dal_power_alarm() {
    case "$1:$#" in get:1) ;; set:2) case "$2" in ''|*[!0-9]*) return 2;; esac;; *) return 2;; esac
    dal_power_gate feature.rtc_alarm || return $?
    rtc=$(dal_meta power.rtc) || return $?
    case "$rtc" in no) return 4;; /sys/class/rtc/rtc*) ;; *) return 3;; esac
    case "${rtc#/sys/class/rtc/rtc}" in ''|*[!0-9]*) return 6;; esac
    node=${PJOS_SYS_ROOT:-}$rtc/wakealarm
    [ -f "$node" ] || return 3
    if [ "$1" = set ]; then printf '%s\n' "$2" > "$node" || return 1
    else epoch=$(cat "$node") || return 1
        case "$epoch" in *[!0-9]*) return 3;; esac
        printf 'alarm_epoch=%s\n' "${epoch:-0}"
    fi
}
