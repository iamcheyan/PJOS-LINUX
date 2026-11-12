#!/bin/sh
# PJOS Linux replacement for the stock /mnt/vendor/ctrl/setBluetooth.sh (same
# path so NextUI's bt_init.sh works unmodified; p6 is never mounted over it).
# POSIX sh version of the vendor logic: attach the RTL8821CS BT UART.

LOCKFILE=${BASEOS_BT_LOCK:-/tmp/.init_bt}
HCI=${BASEOS_BT_HCI:-/sys/class/bluetooth/hci0}
ATTACH_LOG=${BASEOS_BT_ATTACH_LOG:-/run/rtk-hciattach.log}

attach() {
	# A failed attach must not leave a lock that suppresses every later attempt.
	rfkill unblock bluetooth || return 1
	[ ! -d "$HCI" ] || return 0
	attach_pid=$(pidof rtk_hciattach 2>/dev/null || :)
	if [ -z "$attach_pid" ]; then
		rm -f "$LOCKFILE"
		touch "$LOCKFILE" || return 1
		insmod /lib/modules/rtl_btlpm.ko 2>/dev/null || :
		nohup rtk_hciattach -n -s 115200 ttyS1 rtk_h5 </dev/null >"$ATTACH_LOG" 2>&1 &
		attach_pid=$!
	fi
	attempt=0
	while [ "$attempt" -lt 50 ]; do
		[ -d "$HCI" ] && return 0
		kill -0 $attach_pid 2>/dev/null || { rm -f "$LOCKFILE"; return 1; }
		sleep 0.2
		attempt=$((attempt + 1))
	done
	return 1
}

enable_hci() {
	if [ -f "$LOCKFILE" ]; then
		if ! hciconfig | grep -q hci0; then
			sleep 3
		fi
		hciconfig hci0 up
		hciconfig -a hci0 lm master 2>/dev/null
		hciconfig hci0 auth 2>/dev/null
	fi
}

case "$1" in
	init)
		attach
		;;
	enable)
		enable_hci
		;;
	all)
		attach && enable_hci
		;;
	restart)
		systemctl stop bluetooth
		systemctl start bluetooth
		;;
esac
