#!/usr/bin/env python3
"""Apply the RG34XX (vendor H700 DTB) evdev mapping to a PocketJS source tree.

Why this exists: PocketJS's Linux evdev decoder was written against ROCKNIX's
mainline H700 device tree, where the face buttons, shoulders, Start/Select and
Menu carry different linux,input codes than the vendor 4.9 device tree that
BaseOS actually boots. On the vendor table Start/Select emit BTN_TL/BTN_TR,
which PocketJS reads as the L/R triggers, and Menu/L2/R2 emit codes it ignores
entirely - so A/B come out swapped and several buttons do nothing.

The tables below come from this device's own device tree
(/sys/firmware/devicetree/base/soc@03000000/gpio_keys/*/linux,code), not from a
guess:

    keyA      BTN_SOUTH  304     keyL1    BTN_WEST   308
    keyB      BTN_EAST   305     keyR1    BTN_Z      309
    keyX      BTN_C      306     keySEl   BTN_TL     310
    keyY      BTN_NORTH  307     keyStart BTN_TR     311
                                 keyMenu  BTN_TL2    312
                                 keyL2    BTN_SELECT 314
                                 keyR2    BTN_START  315

The D-pad and volume keys already reach the runtime correctly and are left
alone. Keyboard aliases (arrows, Enter/Space/Z/X) keep their previous masks so
desktop and SSH use of the runtime is unchanged.
"""
from pathlib import Path
import sys

source = Path(sys.argv[1]) / "platforms/linux/evdev/src/lib.rs"
text = source.read_text()

old = """            (&[28, 315], btn::START),
            (&[57, 44, 304], btn::CROSS),
            (&[45, 305], btn::CIRCLE),
            (&[42, 307], btn::SQUARE),
            (&[46, 308], btn::TRIANGLE),
            (&[310], btn::LTRIGGER),
            (&[311], btn::RTRIGGER),
"""

new = """            (&[28], btn::START),
            // RG34XX vendor H700 DTB: the physical face buttons are named by
            // their printed labels, and BTN_SOUTH/BTN_EAST are the reverse of
            // ROCKNIX's mainline table. A must confirm and B must cancel.
            (&[304, 45], btn::CIRCLE),
            (&[305, 57, 44], btn::CROSS),
            (&[306, 42], btn::SQUARE),
            (&[307, 46], btn::TRIANGLE),
            (&[308], btn::LTRIGGER),
            (&[309], btn::RTRIGGER),
            (&[310], btn::SELECT),
            (&[311, 312], btn::START),
            (&[314], btn::ZL),
            (&[315], btn::ZR),
"""

if new in text:
    print("RG34XX mapping already present")
elif old in text:
    source.write_text(text.replace(old, new, 1))
    print("applied RG34XX mapping")
else:
    raise SystemExit("pinned PocketJS evdev mapping anchor changed")

# musl's libc declares ioctl(2) with a c_int request; glibc uses c_ulong. Cast
# at the call sites so one patch serves both ABIs (BaseOS runs the musl build).
native = Path(sys.argv[1]) / "platforms/linux/evdev/src/native.rs"
ntext = native.read_text()
if ntext.count("request(0x20 + kind, bytes.len())") == 1 or \
        ntext.count("request(0x40 + code, size_of::<AbsInfo>())") == 1:
    ntext = ntext.replace("request(0x20 + kind, bytes.len()),",
                          "request(0x20 + kind, bytes.len()) as _,", 1)
    ntext = ntext.replace("request(0x40 + code, size_of::<AbsInfo>()),",
                          "request(0x40 + code, size_of::<AbsInfo>()) as _,", 1)
    native.write_text(ntext)
    print("applied musl ioctl request cast")
