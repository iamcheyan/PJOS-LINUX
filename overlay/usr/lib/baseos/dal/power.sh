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
dal_power_boot_reason() { dal_init || return $?; reason=$(dal_meta power.boot_reason 2>/dev/null || printf unknown); printf 'reason=%s\nsource=profile\n' "$reason"; }
