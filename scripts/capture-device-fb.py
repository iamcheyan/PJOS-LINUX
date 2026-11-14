#!/usr/bin/env python3
import sys
import os
import subprocess
from PIL import Image

def capture_fb(out_png_path, adb_serial=None):
    device_ip = os.environ.get("PJOS_DEVICE_IP", "")
    dev_pw = os.environ.get("PJOS_DEV_PW", "")
    
    # Try ADB first if adb device present, else fallback to SSH
    use_ssh = False
    if not adb_serial:
        adb_serial = os.environ.get("PJOS_ADB_SERIAL", "5c0010894414c802512")
    
    try:
        adb_check = subprocess.run(f"adb -s {adb_serial} get-state", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
        if adb_check.returncode != 0:
            use_ssh = True
    except Exception:
        use_ssh = True

    if use_ssh:
        ssh_cmd_base = f"sshpass -p '{dev_pw}' ssh -o ConnectTimeout=5 -o UserKnownHostsFile=/tmp/pjos-debug-known-hosts -o StrictHostKeyChecking=accept-new root@{device_ip}"
        pan = subprocess.check_output(f"{ssh_cmd_base} 'cat /sys/class/graphics/fb0/pan'", shell=True, text=True).strip()
    else:
        cmd = f"adb -s {adb_serial} shell 'cat /sys/class/graphics/fb0/pan'"
        pan = subprocess.check_output(cmd, shell=True, text=True).strip()

    try:
        px, py = [int(v) for v in pan.split(",")]
    except Exception:
        px, py = 0, 0
    print(f"Device fb0 pan: {px},{py}")

    raw_dev = "/tmp/devfb.raw"
    raw_local = "/tmp/devfb_local.raw"
    if os.path.exists(raw_local):
        os.remove(raw_local)

    if use_ssh:
        subprocess.check_call(f"{ssh_cmd_base} 'rm -f {raw_dev} && dd if=/dev/fb0 of={raw_dev} bs=4096 count=675 2>/dev/null && sync'", shell=True)
        subprocess.check_call(f"sshpass -p '{dev_pw}' scp -o ConnectTimeout=5 -o UserKnownHostsFile=/tmp/pjos-debug-known-hosts -o StrictHostKeyChecking=accept-new root@{device_ip}:{raw_dev} {raw_local}", shell=True)
    else:
        subprocess.check_call(f"adb -s {adb_serial} shell 'rm -f {raw_dev} && dd if=/dev/fb0 of={raw_dev} bs=4096 count=675 2>/dev/null && sync'", shell=True)
        subprocess.check_call(f"adb -s {adb_serial} pull {raw_dev} {raw_local}", shell=True)

    with open(raw_local, "rb") as f:
        data = f.read()

    if len(data) != 720 * 960 * 4:
        print(f"Warning: raw data length is {len(data)}, expected {720*960*4}")

    img = Image.frombytes("RGBA", (720, 960), data, "raw", "BGRA")
    crop_box = (px, py, px + 720, py + 480)
    cropped = img.crop(crop_box)
    cropped.save(out_png_path)
    print(f"Saved {out_png_path} ({cropped.size[0]}x{cropped.size[1]})")

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/device-test.png"
    capture_fb(out)
