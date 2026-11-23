#!/bin/sh
DAL_DIR=${DAL_DIR:-/usr/lib/baseos/dal}
: "${PJOS_PROFILE_DIR:=/etc/pjos}"
DAL_SYS_ROOT=${PJOS_SYS_ROOT:-/sys}
DAL_PROC_ROOT=${PJOS_PROC_ROOT:-${PJOS_SYS_ROOT:+$PJOS_SYS_ROOT/proc}}
DAL_PROC_ROOT=${DAL_PROC_ROOT:-/proc}
DAL_profile=${DAL_ENV:-${PJOS_PROFILE_FILE:-$PJOS_PROFILE_DIR/profile.env}}
DAL_board= DAL_soc= DAL_version= DAL_schema= DAL_feature_bitmask=
_dal_loaded=0 _dal_fail=0

_dal_value() {
    [ -r "$DAL_profile" ] || return 3
    awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; found=1; exit } END { if (!found) exit 3 }' "$DAL_profile"
}
_dal_load_file() {
    [ -r "$DAL_profile" ] || return 1
    awk -F= '
        NF < 2 || $1 !~ /^[A-Za-z0-9_.-]+$/ { exit 1 }
        $1 == "schema" { schema=$2 }
        $1 == "board" { board=$2 }
        $1 == "soc" { soc=$2 }
        END { if (schema != "pjos.dal/1" || board !~ /^[a-z0-9][a-z0-9_-]*$/ || soc !~ /^[a-z0-9_-]+\/[a-z0-9_-]+$/) exit 1 }
    ' "$DAL_profile" || return 1
    DAL_schema=$(_dal_value schema) || return 1
    DAL_board=$(_dal_value board) || return 1
    DAL_soc=$(_dal_value soc) || return 1
    DAL_version=$(_dal_value version 2>/dev/null || printf unknown)
    DAL_feature_bitmask=$(_dal_value feature.bitmask 2>/dev/null || :)
}
_dal_json_scalar() {
    awk -v key="$2" 'index($0, "\"" key "\"") { line=$0; sub("^.*\"" key "\"[[:space:]]*:[[:space:]]*\"", "", line); sub("\".*$", "", line); print line; found=1; exit } END { if (!found) exit 1 }' "$1"
}
_dal_validate_composition() {
    boardfile=${PJOS_BOARD_FILE:-$PJOS_PROFILE_DIR/board.json}
    socfile=${PJOS_SOC_FILE:-$PJOS_PROFILE_DIR/soc.json}
    capsfile=${PJOS_CAPS_FILE:-$PJOS_PROFILE_DIR/caps.json}
    featuresfile=${PJOS_FEATURES_FILE:-$PJOS_PROFILE_DIR/features.json}
    [ -r "$boardfile" ] && [ -r "$socfile" ] && [ -r "$capsfile" ] && [ -r "$featuresfile" ] || return 6
    [ "$(_dal_json_scalar "$boardfile" schema)" = pjos.board/1 ] || return 6
    [ "$(_dal_json_scalar "$boardfile" id)" = "$DAL_board" ] || return 6
    [ "$(_dal_json_scalar "$boardfile" soc)" = "$DAL_soc" ] || return 6
    [ "$(_dal_json_scalar "$socfile" schema)" = pjos.soc/1 ] || return 6
    [ "$(_dal_json_scalar "$socfile" soc)" = "$DAL_soc" ] || return 6
    [ "$(_dal_json_scalar "$capsfile" schema)" = pjos.caps/1 ] || return 6
    [ "$(_dal_json_scalar "$capsfile" board)" = "$DAL_board" ] || return 6
    [ "$(_dal_json_scalar "$capsfile" soc)" = "$DAL_soc" ] || return 6
    [ "$(_dal_json_scalar "$featuresfile" schema)" = pjos.features/1 ] || return 6
    [ "$(_dal_json_scalar "$featuresfile" board)" = "$DAL_board" ] || return 6
    [ "$(_dal_json_scalar "$featuresfile" soc)" = "$DAL_soc" ] || return 6
}
dal_init() {
    [ "$_dal_loaded" -eq 1 ] && return "$_dal_fail"
    _dal_loaded=1
    _dal_load_file || { echo 'dal: missing or invalid profile metadata' >&2; _dal_fail=6; return 6; }
    _dal_validate_composition || { echo 'dal: composed profile mismatch' >&2; _dal_fail=6; return 6; }
    return 0
}
dal_meta() {
    dal_init || return $?
    case "$1" in *[!A-Za-z0-9_.-]*|'') return 2;; esac
    _dal_value "$1"
}
_dal_known() {
    case "$1" in wifi|bluetooth|touch|vibration|hdmi|gpu|rtc|usb_gadget|usb_host|brightness|audio|bt_sink|bt_source|audio_hw_volume|audio_hw_mute|display_rotation|display_output_switch|suspend|rtc_alarm|usb_storage_export|usb_adb|usb_host_input|wifi_ap) return 0;; *) return 1;; esac
}
dal_cap_get() { _dal_known "$1" || return 2; dal_meta "cap.$1"; }
dal_feature_get() { _dal_known "$1" || return 2; dal_meta "feature.$1"; }
dal_cap_list() { _dal_meta_list cap pjos.caps/1; }
dal_feature_list() { _dal_meta_list feature pjos.features/1; }
_dal_meta_list() {
    dal_init || return $?
    prefix=$1 schema=$2
    printf 'schema=%s\nboard=%s\nsoc=%s\n' "$schema" "$DAL_board" "$DAL_soc"
    case "$prefix" in cap) names='wifi bluetooth touch vibration hdmi gpu rtc usb_gadget usb_host brightness audio';; *) names='bt_sink bt_source audio_hw_volume audio_hw_mute display_rotation display_output_switch suspend rtc_alarm usb_storage_export usb_adb usb_host_input wifi_ap';; esac
    for name in $names; do value=$(dal_meta "$prefix.$name" 2>/dev/null) || value=unknown; case "$value" in yes|no|unknown) ;; *) return 6;; esac; printf '%s=%s\n' "$name" "$value"; done
}
dal_cap_has() { _dal_has cap "$1"; }
dal_feature_has() { _dal_has feature "$1"; }
_dal_has() { _dal_known "$2" || return 2; value=$(dal_meta "$1.$2") || return 2; case "$value" in yes)return 0;; no)return 1;; unknown)return 2;; *)return 6;; esac; }
dal_feature_bitmask() {
    dal_init || return $?
    order='bt_sink bt_source audio_hw_volume audio_hw_mute display_rotation display_output_switch suspend rtc_alarm usb_storage_export usb_adb usb_host_input wifi_ap'
    mask=0 bit=0 unknown=0
    mask=$((mask | 2147483648))
    for name in $order; do
        value=$(dal_meta "feature.$name" 2>/dev/null) || value=unknown
        case "$value" in yes) mask=$((mask | (1 << bit)));; no) ;; unknown) unknown=1;; *) return 6;; esac
        bit=$((bit + 1))
    done
    [ "$unknown" -eq 0 ] || mask=$((mask | 1073741824))
    printf '%s\n' "$mask"
}
. "$DAL_DIR/display.sh" || return 1
. "$DAL_DIR/input.sh" || return 1
. "$DAL_DIR/power.sh" || return 1
