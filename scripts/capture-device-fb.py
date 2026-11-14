#!/usr/bin/env python3
import sys
import os
import subprocess
from PIL import Image

def capture_fb(out_png_path, adb_serial=None):
    if not adb_serial:
        adb_serial = os.environ.get("PJOS_ADB_SERIAL", "5c0010894414c802512")
    cmd = f"adb -s {adb_serial} shell 'cat /sys/class/graphics/fb0/pan'"
    pan = subprocess.check_output(cmd, shell=True, text=True).strip()
    try:
        px, py = [int(v) for v in pan.split(",")]
    except Exception:
        px, py = 0, 0
    print(f"Device fb0 pan: {px},{py}")

    raw_dev = "/tmp/devfb.raw"
    subprocess.check_call(f"adb -s {adb_serial} shell 'rm -f {raw_dev} && dd if=/dev/fb0 of={raw_dev} bs=4096 count=675 2>/dev/null && sync'", shell=True)
    raw_local = "/tmp/devfb_local.raw"
    if os.path.exists(raw_local):
        os.remove(raw_local)
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
