#!/usr/bin/env python3
import sys
import time
import struct
import subprocess
import os

def send_key(dev_path, code, hold_sec=0.08):
    device_ip = os.environ.get("PJOS_DEVICE_IP", "")
    dev_pw = os.environ.get("PJOS_DEV_PW", "")
    
    # 64-bit linux input_event: timeval (16 bytes), type (2), code (2), value (4)
    # Event 1: EV_KEY (1), code, 1
    # Event 2: EV_SYN (0), 0, 0
    press = struct.pack('<QQHHi', 0, 0, 1, code, 1) + struct.pack('<QQHHi', 0, 0, 0, 0, 0)
    release = struct.pack('<QQHHi', 0, 0, 1, code, 0) + struct.pack('<QQHHi', 0, 0, 0, 0, 0)
    
    with open('/tmp/dev_key_press.bin', 'wb') as f:
        f.write(press)
    with open('/tmp/dev_key_release.bin', 'wb') as f:
        f.write(release)
        
    ssh_base = f"sshpass -p '{dev_pw}' ssh -o ConnectTimeout=5 -o UserKnownHostsFile=/tmp/pjos-debug-known-hosts -o StrictHostKeyChecking=accept-new root@{device_ip}"
    scp_base = f"sshpass -p '{dev_pw}' scp -o ConnectTimeout=5 -o UserKnownHostsFile=/tmp/pjos-debug-known-hosts -o StrictHostKeyChecking=accept-new"
    
    subprocess.check_call(f"{scp_base} /tmp/dev_key_press.bin /tmp/dev_key_release.bin root@{device_ip}:/tmp/", shell=True)
    subprocess.check_call(f"{ssh_base} 'dd if=/tmp/dev_key_press.bin of={dev_path} bs=48 count=1 2>/dev/null'", shell=True)
    time.sleep(hold_sec)
    subprocess.check_call(f"{ssh_base} 'dd if=/tmp/dev_key_release.bin of={dev_path} bs=48 count=1 2>/dev/null'", shell=True)
    time.sleep(0.1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: send-device-key.py <dev_path> <code> [hold_sec]")
        sys.exit(1)
    dev = sys.argv[1]
    code = int(sys.argv[2], 0)
    hold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.08
    send_key(dev, code, hold)
