#!/bin/sh
dal_input_root() { printf '%s' "${PJOS_DEV_ROOT:-}"; }
dal_sys_root() { printf '%s' "${PJOS_SYS_ROOT:-}"; }
dal_input_match_role() {
    role=$1 name=$2
    expected=$(dal_meta "input.$role.name" 2>/dev/null || :)
    prefix=$(dal_meta "input.$role.name_prefix" 2>/dev/null || :)
    suffix=$(dal_meta "input.$role.name_suffix" 2>/dev/null || :)
    [ "$expected" != unknown ] || expected=
    [ "$prefix" != unknown ] || prefix=
    [ "$suffix" != unknown ] || suffix=
    [ -n "$expected$prefix$suffix" ] || return 1
    [ -z "$expected" ] || [ "$expected" = "$name" ] || return 1
    case "$name" in "$prefix"*"$suffix") return 0;; *) return 1;; esac
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
    match=
    for node in "$devroot"/dev/input/event*; do
        [ -c "$node" ] || [ -f "$node" ] || continue
        sysnode="$(dal_sys_root)/sys/class/input/${node##*/}/device/name"
        name=$(cat "$sysnode" 2>/dev/null || :)
        [ -n "$name" ] || continue
        [ -z "$expected" ] || [ "$name" = "$expected" ] || continue
        [ -z "$prefix" ] || case "$name" in "$prefix"*) ;; *) continue;; esac
        [ -z "$suffix" ] || case "$name" in *"$suffix") ;; *) continue;; esac
        [ -z "$match" ] || return 3
        match=${node##*/}
    done
    [ -n "$match" ] || return 3
    printf '/dev/input/%s\n' "$match"
}
dal_input_list() {
    dal_init || return $?
    devroot=$(dal_input_root)
    for node in "$devroot"/dev/input/event*; do
        [ -c "$node" ] || [ -f "$node" ] || continue
        name=$(cat "$(dal_sys_root)/sys/class/input/${node##*/}/device/name" 2>/dev/null || :)
        [ -n "$name" ] || continue
        kind=unknown
        for role in keyboard power gamepad touch directions virtual_dpad; do
            dal_input_match_role "$role" "$name" || continue
            [ "$kind" = unknown ] || { kind=unknown; break; }
            kind=$role
        done
        [ "${1:-}" != --nodes ] || printf 'node=/dev/input/%s ' "${node##*/}"
        printf 'name=%s kind=%s\n' "$name" "$kind"
    done
}
dal_input_power_node() { dal_input_node power; }
dal_input_key_state() {
    [ "$#" -eq 2 ] || return 2
    role=$1 key=$2
    case "$role" in keyboard|power|gamepad|touch|directions|virtual_dpad) ;; *) return 2;; esac
    case "$key" in ''|*[!A-Za-z0-9_]*) return 2;; esac
    node=$(dal_input_node "$role") || return $?
    helper=${BASEOS_INPUT_STATE:-${BASEOS_SBIN_ROOT:-}/usr/sbin/baseos-input-state}
    [ -x "$helper" ] || helper=${BASEOS_INPUT_STATE_HELPER:-}
    [ -x "$helper" ] || helper=${DAL_DIR%/dal}/baseos-input-state
    [ -x "$helper" ] || helper=/usr/sbin/baseos-input-state
    [ -x "$helper" ] || return 3
    devroot=$(dal_input_root)
    case "$node" in /dev/*) node="$devroot$node";; esac
    "$helper" "$node" "$key"
}
dal_input_menu_held() (
    dal_init || exit $?
    source=$(dal_meta input.menu_source) || exit $?
    case "$source" in none|no) exit 4;; gpio) ;; *) exit 3;; esac
    dal_soc_hook || exit $?
    command -v soc_boot_menu_held >/dev/null || exit 3
    GPIO=${BASEOS_GPIO_DEBUG:-${PJOS_SYS_ROOT:-}/sys/kernel/debug/gpio}
    # The vendor predicate returns false both for a released key and for no
    # matching GPIO. Require a labelled input line before reporting release.
    BASEOS_GPIO_DEBUG=$GPIO
    grep -Eq '\|GPIO Key [Mm]enu[[:space:]]*\)[[:space:]]+in[[:space:]]+(hi|lo)([[:space:]]|$)' "$GPIO" 2>/dev/null || exit 3
    if soc_boot_menu_held; then printf 'held=yes\n'; else printf 'held=no\n'; fi
)
