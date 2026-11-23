#!/bin/sh
dal_input_root() { printf '%s' "${PJOS_DEV_ROOT:-}"; }
dal_sys_root() { printf '%s' "${PJOS_SYS_ROOT:-}"; }
dal_input_match_role() {
    role=$1 name=$2
    expected=$(dal_meta "input.$role.name" 2>/dev/null || :)
    prefix=$(dal_meta "input.$role.name_prefix" 2>/dev/null || :)
    suffix=$(dal_meta "input.$role.name_suffix" 2>/dev/null || :)
    [ -n "$expected" ] && [ "$expected" != unknown ] && [ "$name" = "$expected" ] && return 0
    [ -n "$prefix" ] && case "$name" in "$prefix"*) ;; *) return 1;; esac
    [ -n "$suffix" ] && case "$name" in *"$suffix") ;; *) return 1;; esac
    [ -n "$prefix" ] || [ -n "$suffix" ]
}
dal_input_node() {
    dal_init || return $?
    role=${1:-}; [ -n "$role" ] || return 2
    case "$role" in keyboard|power|gamepad|touch|directions|virtual_dpad) ;; *) return 2;; esac
    expected=$(dal_meta "input.$role.name" 2>/dev/null || :)
    prefix=$(dal_meta "input.$role.name_prefix" 2>/dev/null || :)
    suffix=$(dal_meta "input.$role.name_suffix" 2>/dev/null || :)
    [ "$expected" != unknown ] || expected=; [ "$prefix" != unknown ] || prefix=; [ "$suffix" != unknown ] || suffix=
    [ -n "$expected$prefix$suffix" ] || return 3
    devroot=$(dal_input_root)
    for node in "$devroot"/dev/input/event*; do
        [ -c "$node" ] || [ -f "$node" ] || continue
        sysnode="$(dal_sys_root)/sys/class/input/${node##*/}/device/name"
        name=$(cat "$sysnode" 2>/dev/null || :)
        [ -n "$name" ] || continue
        [ -z "$expected" ] || [ "$name" = "$expected" ] || continue
        [ -z "$prefix" ] || case "$name" in "$prefix"*) ;; *) continue;; esac
        [ -z "$suffix" ] || case "$name" in *"$suffix") ;; *) continue;; esac
        printf '/dev/input/%s\n' "${node##*/}"; return 0
    done
    return 3
}
dal_input_list() {
    dal_init || return $?
    devroot=$(dal_input_root)
    for node in "$devroot"/dev/input/event*; do
        [ -c "$node" ] || [ -f "$node" ] || continue
        name=$(cat "$(dal_sys_root)/sys/class/input/${node##*/}/device/name" 2>/dev/null || :)
        [ -n "$name" ] || continue
        kind=unknown
        for role in keyboard power gamepad touch; do if dal_input_match_role "$role" "$name"; then kind=$role; break; fi; done
        printf 'node=/dev/input/%s name=%s kind=%s\n' "${node##*/}" "$name" "$kind"
    done
}
dal_input_power_node() { dal_input_node power; }
dal_input_key_state() { return 3; }
dal_input_menu_held() { source=$(dal_meta input.menu_source 2>/dev/null) || return 3; [ "$source" = no ] && return 4; [ "$source" = unknown ] && return 3; return 3; }
