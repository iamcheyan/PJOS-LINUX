#!/bin/bash
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
STAGED_DIR="$HERE/work/staged-series"
DEVICE_TARGET="/storage/content/games/series"

echo "=== Fire Emblem Series Deployment Script ==="

# Check ADB
if adb get-state >/dev/null 2>&1; then
    echo "[+] Found ADB device:"
    adb devices -l
    echo "[+] Uploading series to $DEVICE_TARGET..."
    for series in fe-binding-blade fe-blazing-blade fe-sacred-stones; do
        echo " -> Deploying $series..."
        adb shell "mkdir -p $DEVICE_TARGET/$series/gba"
        adb push "$STAGED_DIR/$series/series.json" "$DEVICE_TARGET/$series/series.json"
        adb push "$STAGED_DIR/$series/cover.png" "$DEVICE_TARGET/$series/cover.png"
        adb push "$STAGED_DIR/$series/gba/"* "$DEVICE_TARGET/$series/gba/"
    done
    echo "[+] Updating PocketShell package and scanner via ADB..."
    adb push "$HERE/../pocketshell/dist/pocketshell.pocket" "/storage/System/pocketjs/apps/boot.pocket"
    adb push "$HERE/overlay/usr/share/pocketshell/System/compat/bin/pocketshell-games" "/storage/System/compat/bin/pocketshell-games"
    adb shell "chmod +x /storage/System/compat/bin/pocketshell-games"
    echo "[+] Updating game library..."
    adb shell "/storage/System/compat/bin/pocketshell-games"
    echo "[+] Reloading PocketShell..."
    adb shell "killall -TERM pocket-linux-kms 2>/dev/null || true"
    echo "[✓] Deployment complete via ADB!"
    exit 0
fi

# Check SSH
DEVICE_IP="${PJOS_DEVICE_IP:-${1:-}}"
PW="${PJOS_DEV_PW:-}"
if [ -z "$DEVICE_IP" ]; then
    echo "Usage: $0 [device-ip]" >&2
    exit 1
fi

echo "[*] ADB not detected, trying SSH to $DEVICE_IP..."
if sshpass -p "$PW" ssh -o ConnectTimeout=3 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "root@$DEVICE_IP" "hostname" >/dev/null 2>&1; then
    echo "[+] SSH connection successful!"
    for series in fe-binding-blade fe-blazing-blade fe-sacred-stones; do
        echo " -> Deploying $series..."
        sshpass -p "$PW" ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "root@$DEVICE_IP" "mkdir -p $DEVICE_TARGET/$series/gba"
        sshpass -p "$PW" scp -r -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "$STAGED_DIR/$series/"* "root@$DEVICE_IP:$DEVICE_TARGET/$series/"
    done
    echo "[+] Updating PocketShell package and scanner via SSH..."
    sshpass -p "$PW" scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "$HERE/../pocketshell/dist/pocketshell.pocket" "root@$DEVICE_IP:/storage/System/pocketjs/apps/boot.pocket"
    sshpass -p "$PW" scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "$HERE/overlay/usr/share/pocketshell/System/compat/bin/pocketshell-games" "root@$DEVICE_IP:/storage/System/compat/bin/pocketshell-games"
    sshpass -p "$PW" ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "root@$DEVICE_IP" "chmod +x /storage/System/compat/bin/pocketshell-games"
    echo "[+] Updating game library..."
    sshpass -p "$PW" ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "root@$DEVICE_IP" "/storage/System/compat/bin/pocketshell-games"
    echo "[+] Reloading PocketShell..."
    sshpass -p "$PW" ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "root@$DEVICE_IP" "killall -TERM pocket-linux-kms 2>/dev/null || true"
    echo "[✓] Deployment complete via SSH!"
    exit 0
fi
    echo "[✓] Deployment complete via SSH!"
    exit 0
fi

echo "[!] Error: Neither ADB device nor SSH at $DEVICE_IP is reachable."
echo "    Please wake up hx90 or check device power/network connection, then re-run this script."
exit 1
