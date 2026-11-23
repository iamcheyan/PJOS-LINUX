# Sourced by baseos-hw. 2=usage, 3=unknown/unavailable, 4=unsupported.
aux_yes() {
    case $(dal_meta "$1") in yes) return 0;; no) return 4;; *) return 3;; esac
}

aux_audio() {
    case "$1:$#" in info:1|get-volume:1|cards:1) ;;
        set-volume:2) case $2 in [0-9]|[1-9][0-9]|100) ;; *) return 2;; esac;;
        mute:2) case $2 in on|off) ;; *) return 2;; esac;; *) return 2;; esac
    aux_yes cap.audio || return $?
    if [ "$1" = cards ]; then cat "${DAL_PROC_ROOT:-/proc}/asound/cards"; return; fi
    exact=$(dal_meta audio.card_name) || exact=
    prefix=$(dal_meta audio.card_prefix) || prefix=
    [ -n "$exact$prefix" ] || return 3
    card=''
    for id in "${DAL_SYS_ROOT:-/sys}"/class/sound/card[0-9]*/id; do
        [ -r "$id" ] || continue
        IFS= read -r card_name < "$id" || continue
        if [ -n "$exact" ]; then
            [ "$card_name" = "$exact" ] || continue
        else
            case $card_name in "$prefix"*) ;; *) continue;; esac
        fi
        [ -z "$card" ] || return 3
        card=${id%/id}; card=${card##*/card}
        matched_name=$card_name
    done
    [ -n "$card" ] || return 3
    ctl=$(dal_meta audio.volume_control) && [ -n "$ctl" ] || return 3
    case $1 in
        set-volume)
            lineout=$(dal_meta audio.lineout_control) || lineout=
            speaker=$(dal_meta audio.speaker_control) || speaker=
            [ -z "$lineout" ] || amixer -q -c "$card" sset "$lineout" "$2%" || return 1
            amixer -q -c "$card" sset "$ctl" "$2%" || return 1
            # A softvol control only exists once the configured PCM has opened.
            soft=$(dal_meta audio.soft_volume_control) || soft=
            if [ -n "$soft" ] && amixer -c "$card" sget "$soft" >/dev/null 2>&1; then
                amixer -q -c "$card" sset "$soft" "$2%" || return 1
            fi
            gain=$(dal_meta audio.pcm_gain_control) || gain=
            if [ -n "$gain" ]; then
                raw=$(dal_meta audio.pcm_gain_raw) || return 6
                amixer -q -c "$card" cset "name=$gain" "$raw" || return 1
            fi
            if [ -n "$speaker" ]; then
                if [ "$2" -eq 0 ]; then switch=off; else switch=on; fi
                amixer -q -c "$card" sset "$speaker" "$switch" || return 1
            fi;;
        mute) aux_yes feature.audio_hw_mute || return $?
            ctl=$(dal_meta audio.mute_control) && [ -n "$ctl" ] || return 3
            if [ "$2" = on ]; then switch=mute; else switch=unmute; fi
            amixer -q -c "$card" sset "$ctl" "$switch";;
        *) state=$(amixer -c "$card" sget "$ctl") || return 1
            pct=$(printf '%s\n' "$state" | sed -n 's/.*\[\([0-9][0-9]*\)%\].*/\1/p' | head -1)
            [ -n "$pct" ] || return 1
            if [ "$1" = info ]; then
                printf 'card=%s\ncard_name=%s\nvolume_control=%s\nvolume=%s\n' "$card" "$matched_name" "$ctl" "$pct"
            else printf '%s\n' "$pct"; fi;;
    esac
}

aux_iface() {
    iface=$(dal_meta network.wifi_iface) || return 3
    case $iface in ''|-*|*[!a-zA-Z0-9_-]*) return 3;; esac
    netdir=${DAL_SYS_ROOT:-/sys}/class/net/$iface
}

aux_network() {
    case "$1:$#" in info:1)
        wifi=$(dal_meta cap.wifi) || wifi=unknown
        bt=$(dal_meta cap.bluetooth) || bt=unknown
        printf 'wifi_present=%s\nbt_present=%s\n' "$wifi" "$bt"
        if [ "$wifi" = yes ] && aux_iface; then
            state=$(cat "$netdir/operstate" 2>/dev/null) || state=unknown
            printf 'wifi_iface=%s\nwifi_state=%s\n' "$iface" "$state"
        fi
        if [ "$bt" = yes ]; then
            if [ -d "${DAL_SYS_ROOT:-/sys}/class/bluetooth/hci0" ]; then printf 'bt_hci=hci0\n'; else printf 'bt_hci=unavailable\n'; fi
        fi;;
    wifi-up:1|wifi-down:1|wifi-scan:1|mdns:2)
        [ "$1" != mdns ] || [ "$2" = refresh ] || return 2
        aux_yes cap.wifi && aux_iface || return $?
        [ -d "$netdir" ] || return 3
        case $1 in wifi-up) ip link set dev "$iface" up;; wifi-down) ip link set dev "$iface" down;;
            wifi-scan) iw dev "$iface" scan;; mdns) [ "$iface" = wlan0 ] || return 4
                /usr/sbin/baseos-mdns refresh "$iface";; esac;;
    bt-up:1|bt-down:1)
        aux_yes cap.bluetooth || return $?
        [ "$(dal_meta network.bt_backend)" = rtl8821cs-h5 ] && [ "$(dal_meta network.bt_uart)" = ttyS1 ] || return 3
        if [ "$1" = bt-up ]; then
            /mnt/vendor/ctrl/setBluetooth.sh init && hciconfig hci0 up && /usr/sbin/systemctl start bluetooth
        else /usr/sbin/systemctl stop bluetooth && hciconfig hci0 down; fi;;
    *) return 2;; esac
}

aux_role() {
    case $1 in boot|rootfs|primary|data|tf2) dal_meta "storage.role.$1";; *) return 2;; esac
}

aux_storage() {
    case "$1:$#" in
        role:2) aux_role "$2";;
        roles:1|info:1)
            layout=$(dal_meta storage.layout) || return 3
            if [ "$1" = info ]; then
                disk=$(dal_meta storage.boot_disk) || return 3
                printf 'boot_disk=%s\nlayout=%s\n' "$disk" "$layout"
            fi
            for role in boot rootfs data primary tf2; do
                path=$(aux_role "$role") || continue
                printf '%s=%s\n' "$role" "$path"
            done;;
        usb-mode:2) case $2 in
            status) if [ -s /run/usb-storage-device ]; then cat /run/usb-storage-device; else printf 'off\n'; fi;;
            prepare) aux_yes feature.usb_storage_export || return $?
                # The existing adapter is specific to this disk and partition. Entry 5
                # follows the active slot; the inactive slot is NOT another partition.
                [ "$(dal_meta storage.layout)" = baseos-ab-v1 ] &&
                    [ "$(dal_meta storage.boot_disk)" = /dev/mmcblk0 ] &&
                    [ "$(aux_role primary)" = /dev/mmcblk0p7 ] || return 3
                /usr/sbin/usb-storage-mode prepare;;
            *) return 2;; esac;;
        # expand-storage can mkfs an occupied filesystem; only first boot owns it.
        expand:1) return 4;;
        *) return 2;; esac
}

aux_led() {
    case "$1:$#" in list:1|info:1) ;;
        set:3) [ "$2" = work ] || return 4
            case $3 in on) level=1;; off) level=0;; auto) return 4;; *) return 2;; esac;;
        *) return 2;; esac
    path=$(dal_meta led.work_node) || return 3
    supply=${path#/sys/class/power_supply/}; supply=${supply%/work_led}
    case $supply in ''|.|..|*[!a-zA-Z0-9_-]*) return 3;; esac
    [ "$path" = "/sys/class/power_supply/$supply/work_led" ] || return 3
    node=${DAL_SYS_ROOT:-/sys}/class/power_supply/$supply/work_led
    [ -f "$node" ] || return 3
    if [ "$1" = set ]; then printf '%s\n' "$level" > "$node"
    else value=$(cat "$node") || return 1; printf 'work=%s\n' "$value"; fi
}

dal_aux() {
    [ $# -ge 2 ] || return 2
    group=$1; shift
    case $group in audio) aux_audio "$@";; network) aux_network "$@";; storage) aux_storage "$@";; led) aux_led "$@";; *) return 2;; esac
}
