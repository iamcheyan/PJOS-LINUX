#!/usr/bin/env python3
"""Allow non-zero high bits in variable.rotate on Allwinner DISP2 framebuffers.

Allwinner's sunxi fb drivers set rotate=768 (0x300) for hardware plane flags.
Standard Linux fb.h uses bits 0..1 for rotation (FB_ROTATE_UR=0).
"""
import sys
from pathlib import Path

path = Path(sys.argv[1]) / "platforms/linux/fbdev/src/native.rs"
if not path.is_file():
    print(f"skip: {path} not found")
    sys.exit(0)

src = path.read_text()
target = "|| variable.rotate != 0"
replacement = "|| (variable.rotate & 3) != 0"

if target in src:
    src = src.replace(target, replacement)
    path.write_text(src)
    print(f"applied rotate & 3 patch to {path}")
else:
    print(f"already patched or target not found in {path}")
