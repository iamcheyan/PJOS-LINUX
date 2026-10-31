#!/bin/sh
# PJOS Linux replacement for the stock /mnt/vendor/ctrl/setBluetooth.sh (same
# path so NextUI's bt_init.sh works unmodified; p6 is never mounted over it).
# POSIX sh version of the vendor logic: attach the RTL8821CS BT UART.

LOCKFILE=/tmp/.init_bt

attach() {
	if [ ! -f "$LOCKFILE" ]; then
		touch "$LOCKFILE"
		insmod /lib/modules/rtl_btlpm.ko 2>/dev/null
		# The vendor attach process owns the UART after this script exits.
		# Keep it out of the PocketJS bridge's two-second command lifetime.
		nohup rtk_hciattach -n -s 115200 ttyS1 rtk_h5 </dev/null >/run/rtk-hciattach.log 2>&1 &
		attach_pid=$!
		for _ in 1 2 3 4 5 6 7 8 9 10; do
			[ -d /sys/class/bluetooth/hci0 ] && return 0
			kill -0 "$attach_pid" 2>/dev/null || { rm -f "$LOCKFILE"; return 1; }
			sleep 0.2
		done
		rm -f "$LOCKFILE"
		return 1
	fi
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
		attach
		enable_hci
		;;
	restart)
		systemctl stop bluetooth
		systemctl start bluetooth
		;;
esac
