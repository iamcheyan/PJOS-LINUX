#!/usr/bin/env python3
"""Pass the linuxraw pad name to autoconf.

linuxraw calls `input_autoconfigure_connect` with a NULL device name, so
autoconf can only match by VID/PID. On the RG34XX the built-in pad reports
generic 0001:0001 IDs, which makes every profile miss and leaves the pad
"(0/0) not configured". The pad's name ("ANBERNIC-keys") is already known.

    python3 src/apply-retroarch-linuxraw-autoconf.py <retroarch source tree>
"""
from pathlib import Path
import sys

OLD = '      input_autoconfigure_connect(pad->ident, NULL, "linuxraw",'
NEW = '      input_autoconfigure_connect(pad->ident, pad->ident, "linuxraw",'

p = Path(sys.argv[1]) / "input/drivers_joypad/linuxraw_joypad.c"
t = p.read_text()
if 'pad->ident, pad->ident, "linuxraw"' in t:
    print("already applied: linuxraw autoconf name"); raise SystemExit
if t.count(OLD) != 1:
    raise SystemExit(f"anchor appears {t.count(OLD)} times")
p.write_text(t.replace(OLD, NEW, 1))
print("applied linuxraw autoconf name")
