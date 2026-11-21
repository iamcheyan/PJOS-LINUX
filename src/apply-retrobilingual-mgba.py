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
for adapter in (src / "adapters").glob("*.c"):
    if adapter.name == "template.c":
        continue
    shutil.copy(adapter, source / "src/platform/libretro" / adapter.name)
adapters = source / "src/platform/libretro/adapters"
adapters.mkdir(exist_ok=True)
shutil.copy(src / "adapters/adapter.h", adapters / "adapter.h")
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
    "bool retro_load_game(const struct retro_game_info* game) {",
    "bool retro_load_game(const struct retro_game_info* game) {\n\tretrobilingual_set_rom_path(game ? game->path : NULL);",
    "load game hook",
)
replace_once(
    "void retro_unload_game(void) {",
    "void retro_unload_game(void) {\n\tretrobilingual_set_rom_path(NULL);",
    "unload game hook",
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
    "\tinfo->geometry.base_width = width;\n\tinfo->geometry.base_height = height;",
    "\tinfo->geometry.base_width = 720;\n\tinfo->geometry.base_height = 480;",
    "av_info base dimensions",
)
replace_once(
    "\t{\n\t\tinfo->geometry.max_width = width;\n\t\tinfo->geometry.max_height = height;\n\t}",
    "\t{\n\t\tinfo->geometry.max_width = 720;\n\t\tinfo->geometry.max_height = 480;\n\t}",
    "av_info max dimensions",
)
replace_once(
    "\tinfo->geometry.aspect_ratio = width / (double) height;",
    "\tinfo->geometry.aspect_ratio = 720.0 / 480.0;",
    "av_info aspect ratio",
)
replace_once(
    "\tvideoCallback(outputBuffer, width, height, BYTES_PER_PIXEL * 256);",
    "\tretrobilingual_draw(core, outputBuffer, width, height, BYTES_PER_PIXEL * 256);\n"
    "\tvoid* out_buf = outputBuffer;\n"
    "\tunsigned out_w = width, out_h = height, out_pitch = BYTES_PER_PIXEL * 256;\n"
    "\tretrobilingual_present(outputBuffer, width, height, BYTES_PER_PIXEL * 256, &out_buf, &out_w, &out_h, &out_pitch);\n"
    "\tvideoCallback(out_buf, out_w, out_h, out_pitch);",
    "overlay draw hook",
)
libretro.write_text(text, encoding="utf-8")
