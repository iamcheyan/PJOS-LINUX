#!/usr/bin/env python3
"""Apply hardware evdev mapping to PocketJS source tree for RG34XX and TrimUI Smart Pro.

- RG34XX (vendor H700 DTB): Anbernic hardware mappings (304=A, 305=B, 306=X, 307=Y, etc.)
- TrimUI Smart Pro (A133): TRIMUI Player1 virtual Xbox controller (305=A, 304=B, 308=X, 307=Y,
  310=L1, 311=R1, 314=Select, 315=Start, 316=Menu, ABS_HAT0X/Y=Dpad, ABS_X/Y=LeftStick,
  ABS_Z/RZ=L2/R2, ABS_RX=RightStick).

Auto-detected at runtime via EVIOCGNAME ("TRIMUI"). 100% zero regression for RG34XX.
"""
from pathlib import Path
import sys

tree = Path(sys.argv[1])
source = tree / "platforms/linux/evdev/src/lib.rs"
text = source.read_text()

# 1. Add is_trimui field to Decoder struct if not present
if "pub is_trimui: bool," not in text:
    old_struct = """    pointer_enabled: bool,
}"""
    new_struct = """    pointer_enabled: bool,
    pub is_trimui: bool,
}"""
    text = text.replace(old_struct, new_struct, 1)

# 2. Add is_trimui: false to Decoder::new
if "is_trimui: false," not in text:
    old_new = """            pointer_enabled: false,
        })"""
    new_new = """            pointer_enabled: false,
            is_trimui: false,
        })"""
    text = text.replace(old_new, new_new, 1)

# 3. Add ABS handling in Decoder::event
old_abs = """            (3, 0 | 1) if !self.multitouch => {
                if code == 0 {
                    self.current.touches[0].x = value;
                } else {
                    self.current.touches[0].y = value;
                }
            }"""

new_abs = """            (3, 16) if self.is_trimui => {
                self.current.keys[105] = value < 0;
                self.current.keys[106] = value > 0;
            }
            (3, 17) if self.is_trimui => {
                self.current.keys[103] = value < 0;
                self.current.keys[108] = value > 0;
            }
            (3, 0) if self.is_trimui => {
                self.current.keys[105] = value < -12000;
                self.current.keys[106] = value > 12000;
            }
            (3, 1) if self.is_trimui => {
                self.current.keys[103] = value < -12000;
                self.current.keys[108] = value > 12000;
            }
            (3, 2) if self.is_trimui => {
                self.current.keys[312] = value > 128;
            }
            (3, 5) if self.is_trimui => {
                self.current.keys[313] = value > 128;
            }
            (3, 3) if self.is_trimui => {
                self.current.keys[602] = value < -16000;
                self.current.keys[603] = value > 16000;
            }
            (3, 0 | 1) if !self.multitouch && !self.is_trimui => {
                if code == 0 {
                    self.current.touches[0].x = value;
                } else {
                    self.current.touches[0].y = value;
                }
            }"""

if old_abs in text:
    text = text.replace(old_abs, new_abs, 1)

# 4. Patch Decoder::append with dual mapping (TrimUI vs RG34XX)
target_anchor = "let keys = &self.published.keys;"
if "if self.is_trimui {" not in text:
    old_mapping = """        let keys = &self.published.keys;
        for (codes, mask) in [
            (&[103u16, 544][..], btn::UP),
            (&[108, 545], btn::DOWN),
            (&[105, 546], btn::LEFT),
            (&[106, 547], btn::RIGHT),
            (&[28], btn::START),
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
        ] {
            if codes.iter().any(|c| keys[*c as usize]) {
                frame.buttons |= mask;
            }
        }"""

    # If the original unmodified upstream mapping is present:
    upstream_mapping = """        let keys = &self.published.keys;
        for (codes, mask) in [
            (&[103u16, 544][..], btn::UP),
            (&[108, 545], btn::DOWN),
            (&[105, 546], btn::LEFT),
            (&[106, 547], btn::RIGHT),
            (&[28, 315], btn::START),
            (&[57, 44, 304], btn::CROSS),
            (&[45, 305], btn::CIRCLE),
            (&[42, 307], btn::SQUARE),
            (&[46, 308], btn::TRIANGLE),
            (&[310], btn::LTRIGGER),
            (&[311], btn::RTRIGGER),
        ] {
            if codes.iter().any(|c| keys[*c as usize]) {
                frame.buttons |= mask;
            }
        }"""

    new_dual_mapping = """        let keys = &self.published.keys;
        if self.is_trimui {
            for (codes, mask) in [
                (&[103u16, 544][..], btn::UP),
                (&[108, 545], btn::DOWN),
                (&[105, 546], btn::LEFT),
                (&[106, 547], btn::RIGHT),
                (&[28], btn::START),
                // TrimUI Smart Pro layout (TRIMUI Player1 virtual Xbox pad):
                // Physical 'A' (Right) emits BTN_B (305) -> Confirm (CIRCLE)
                (&[305, 45], btn::CIRCLE),
                // Physical 'B' (Bottom) emits BTN_A (304) -> Cancel (CROSS)
                (&[304, 57, 44], btn::CROSS),
                // Physical 'X' (Top) emits BTN_Y (308) -> Triangle
                (&[308, 46], btn::TRIANGLE),
                // Physical 'Y' (Left) emits BTN_X (307) -> Square
                (&[307, 42], btn::SQUARE),
                // Shoulders: L1 (310), Right stick left (602)
                (&[310, 602], btn::LTRIGGER),
                // Shoulders: R1 (311), Right stick right (603)
                (&[311, 603], btn::RTRIGGER),
                // Select (314)
                (&[314], btn::SELECT),
                // Start (315) or Menu/FN (316)
                (&[315, 316], btn::START),
                // Triggers L2 (312), R2 (313)
                (&[312], btn::ZL),
                (&[313], btn::ZR),
            ] {
                if codes.iter().any(|c| keys[*c as usize]) {
                    frame.buttons |= mask;
                }
            }
        } else {
            // RG34XX vendor H700 DTB (100% UNCHANGED!)
            for (codes, mask) in [
                (&[103u16, 544][..], btn::UP),
                (&[108, 545], btn::DOWN),
                (&[105, 546], btn::LEFT),
                (&[106, 547], btn::RIGHT),
                (&[28], btn::START),
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
            ] {
                if codes.iter().any(|c| keys[*c as usize]) {
                    frame.buttons |= mask;
                }
            }
        }"""

    if old_mapping in text:
        text = text.replace(old_mapping, new_dual_mapping, 1)
        print("Updated existing RG34XX mapping to dual TrimUI/RG34XX mapping")
    elif upstream_mapping in text:
        text = text.replace(upstream_mapping, new_dual_mapping, 1)
        print("Replaced upstream mapping with dual TrimUI/RG34XX mapping")
    else:
        raise SystemExit("pinned PocketJS evdev mapping anchor changed")

source.write_text(text)

# 5. Patch native.rs with musl ioctl cast and EVIOCGNAME device detection
native = tree / "platforms/linux/evdev/src/native.rs"
ntext = native.read_text()
if ntext.count("request(0x20 + kind, bytes.len())") == 1 or \
        ntext.count("request(0x40 + code, size_of::<AbsInfo>())") == 1:
    ntext = ntext.replace("request(0x20 + kind, bytes.len()),",
                          "request(0x20 + kind, bytes.len()) as _,", 1)
    ntext = ntext.replace("request(0x40 + code, size_of::<AbsInfo>()),",
                          "request(0x40 + code, size_of::<AbsInfo>()) as _,", 1)
    print("applied musl ioctl request cast")

old_native_decoder = """        let mut decoder = Decoder::new(extent, ranges, first_contact, count)?;
        decoder.pointer_enabled = pointer;
        decoder.accept_multitouch = type_b;"""

new_native_decoder = """        let mut decoder = Decoder::new(extent, ranges, first_contact, count)?;
        decoder.pointer_enabled = pointer;
        decoder.accept_multitouch = type_b;
        let mut name_buf = [0u8; 128];
        unsafe {
            let res = libc::ioctl(file.as_raw_fd(), 0x80804506, name_buf.as_mut_ptr());
            if res > 0 {
                let s = std::str::from_utf8_unchecked(&name_buf[..res as usize]);
                if s.contains("TRIMUI") {
                    decoder.is_trimui = true;
                }
            }
        }"""

if old_native_decoder in ntext:
    ntext = ntext.replace(old_native_decoder, new_native_decoder, 1)
    print("applied TrimUI EVIOCGNAME auto-detection to native.rs")

native.write_text(ntext)
