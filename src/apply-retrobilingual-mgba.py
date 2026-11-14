#!/usr/bin/env python3
"""Apply the RetroBilingual integration to a temporary mGBA checkout."""
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: apply-retrobilingual-mgba.py <mgba-source> <src-dir>")

source = Path(sys.argv[1])
src = Path(sys.argv[2])
libretro = source / "src/platform/libretro/libretro.c"
text = libretro.read_text(encoding="utf-8")

shutil.copy(src / "retrobilingual.c", source / "src/platform/libretro/retrobilingual.c")
shutil.copy(src / "retrobilingual.h", source / "src/platform/libretro/retrobilingual.h")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one {label} anchor in libretro.c, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    '#include "libretro_core_options.h"',
    '#include "libretro_core_options.h"\n#include "retrobilingual.h"',
    "libretro helper include",
)
replace_once(
    "\tcore->setKeys(core, keys);",
    "\tretrobilingual_process_input(core, &keys, inputCallback);\n\tcore->setKeys(core, keys);",
    "input filter hook",
)
replace_once(
    "\tcore->runFrame(core);\n\tunsigned width, height;",
    "\tif (retrobilingual_should_run_frame(core)) {\n\t\tcore->runFrame(core);\n\t}\n\tunsigned width, height;",
    "frame gate hook",
)
replace_once(
    "\tvideoCallback(outputBuffer, width, height, BYTES_PER_PIXEL * 256);",
    "\tretrobilingual_draw(core, outputBuffer, width, height, BYTES_PER_PIXEL * 256);\n\tvideoCallback(outputBuffer, width, height, BYTES_PER_PIXEL * 256);",
    "overlay draw hook",
)
libretro.write_text(text, encoding="utf-8")
