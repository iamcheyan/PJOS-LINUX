#!/usr/bin/env python3
"""Install profile-driven evdev bindings in the staged PocketJS checkout."""
from pathlib import Path
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f'evdev source drift: {old[:60]}')
    return text.replace(old, new, 1)


root = Path(sys.argv[1]) / 'platforms/linux/evdev/src'
lib = root / 'lib.rs'
native = root / 'native.rs'
s = lib.read_text()
n = native.read_text()
if 'fn pjos_layout(' not in s:
    # Preserve upstream USB input behavior for secondary devices. The primary
    # gamepad has an explicit map and never takes the upstream branch.
    start = s.index('        let keys = &self.published.keys;')
    end = s.index('        if self.pointer_enabled {', start)
    s = s[:start] + """        for &(code, mask) in &self.layout_keys {
            if self.published.keys[code] { frame.buttons |= mask; }
        }
        for &(code, greater, threshold, mask) in &self.layout_axes {
            if self.published.axes[code].is_some_and(|v| if greater { v > threshold } else { v < threshold }) {
                frame.buttons |= mask;
            }
        }
""" + s[end:]
    s = once(s, '    keys: [bool; 768],', '    keys: [bool; 768],\n    axes: [Option<i32>; 64],')
    s = once(s, '            keys: [false; 768],', '            keys: [false; 768],\n            axes: [None; 64],')
    s = once(s, '        self.current.keys.fill(false);', '        self.current.axes.fill(None);\n        self.current.keys.fill(false);')
    s = once(s, '        match (kind, code) {', '        if kind == 3 && (code as usize) < 64 { self.current.axes[code as usize] = Some(value); }\n        match (kind, code) {')
    s = once(s, '    pointer_enabled: bool,', '    layout_keys: Vec<(usize, u32)>,\n    layout_axes: Vec<(usize, bool, i32, u32)>,\n    pointer_enabled: bool,')
    s = once(s, '            pointer_enabled: false,', '            layout_keys: Vec::new(),\n            layout_axes: Vec::new(),\n            pointer_enabled: false,')
    names = 'UP DOWN LEFT RIGHT START SELECT CIRCLE CROSS SQUARE TRIANGLE LTRIGGER RTRIGGER ZL ZR'.split()
    s += r'''
impl Decoder {
    fn pjos_layout(&mut self, text: &str) -> io::Result<()> {
        let bad = || io::Error::new(io::ErrorKind::InvalidData, "invalid PocketJS input.map");
        let mut lines = text.lines();
        if lines.next() != Some("schema=pjos.input/1") { return Err(bad()); }
        for line in lines {
            let mut fields = line.split_whitespace();
            let mask = match fields.next() {
BUTTON_NAMES
                _ => return Err(bad()),
            };
            match fields.next() {
                Some("key") => {
                    let first = fields.next().ok_or_else(bad)?;
                    for word in std::iter::once(first).chain(fields) {
                        let code: usize = word.parse().map_err(|_| bad())?;
                        if code >= 768 { return Err(bad()); }
                        self.layout_keys.push((code, mask));
                    }
                }
                Some(op @ ("lt" | "gt")) => {
                    let code: usize = fields.next().ok_or_else(bad)?.parse().map_err(|_| bad())?;
                    let threshold = fields.next().ok_or_else(bad)?.parse().map_err(|_| bad())?;
                    if code >= 64 || fields.next().is_some() { return Err(bad()); }
                    self.layout_axes.push((code, op == "gt", threshold, mask));
                }
                _ => return Err(bad()),
            }
        }
        if self.layout_keys.is_empty() && self.layout_axes.is_empty() { return Err(bad()); }
        Ok(())
    }
}
'''.replace('BUTTON_NAMES', '\n'.join(f'                Some("{name}") => btn::{name},' for name in names))
    anchor = '        decoder.pointer_enabled = pointer;'
    n = once(n, anchor, """        let dir = std::env::var_os("PJOS_PROFILE_DIR").unwrap_or_else(|| "/etc/pjos".into());
        let map = std::fs::read_to_string(Path::new(&dir).join("input.map"))?;
        decoder.pjos_layout(&map)?;
        // Axis wiring belongs only to the first (DAL-resolved gamepad) input.
        if first_contact != 0 { decoder.layout_axes.clear(); }
""" + anchor)
    a = n.index('        let buttons = ['); b = n.index('        let mut classes', a)
    n = n[:a] + n[b:]; a=n.index('        if buttons {'); b=n.index('        let codes',a); n=n[:a]+n[b:]
    n = once(n, anchor, """        if decoder.layout_keys.iter().any(|&(c, _)| has(&keys, c)) || decoder.layout_axes.iter().any(|&(c, _, _, _)| has(&absolute, c)) {
            classes |= InputClasses::BUTTONS;
        }
""" + anchor)
    for call in ('request(0x20 + kind, bytes.len())', 'request(0x40 + code, size_of::<AbsInfo>())'):
        n = n.replace(call + ',', call + ' as _,')
    native.write_text(n)
    lib.write_text(s)
