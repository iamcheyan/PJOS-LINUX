#!/usr/bin/env python3
"""Point the bridge's brightness read at the RG34XX vendor node.

BaseOS has no /sys/class/backlight: the H700 display driver exposes
/sys/class/disp/disp/attr/enhance_bright, whose content is two space-separated
levels on a 0..255 scale ("127 127"). The stock bridge scanned the backlight
class, found nothing on this panel and answered "unknown", so the settings row
never reflected the hardware. Return the first field as 0..100 percent.

Idempotent; safe on an already patched file.

    python3 src/apply-pocketjs-panel.py <pocketshell-launcher.rs>
"""
from pathlib import Path
import sys

SCAN = '''            if let Ok(entries) = std::fs::read_dir("/sys/class/backlight") {
                for entry in entries.flatten() {
                    let path = entry.path();
                    let read = |name| std::fs::read_to_string(path.join(name)).ok()?.trim().parse::<u32>().ok();
                    if let (Some(current), Some(max)) = (read("brightness"), read("max_brightness")) {
                        if max > 0 { return (current * 100 / max).to_string(); }
                    }
                }
            }
'''

VENDOR = """            // No /sys/class/backlight on the H700. The vendor display node
            // prints the live level as "backlight(N)" on a 0..255 scale.
            if let Ok(raw) = std::fs::read_to_string("/sys/class/disp/disp/attr/sys") {
                if let Some(pos) = raw.find("backlight(") {
                    let digits: String = raw[pos + 10..]
                        .trim_start()
                        .chars()
                        .take_while(|c| c.is_ascii_digit())
                        .collect();
                    if let Ok(level) = digits.parse::<u32>() {
                        return (level.min(255) * 100 / 255).to_string();
                    }
                }
            }
"""

def main(path: Path) -> int:
    text = path.read_text()
    if '"/sys/class/disp/disp/attr/sys"' in text:
        print("panel: vendor brightness read already present")
        return 0
    if SCAN not in text:
        print("panel: brightness arm anchor missing", file=sys.stderr)
        return 1
    count = text.count(SCAN)
    path.write_text(text.replace(SCAN, VENDOR))
    print(f"panel: vendor brightness read installed in {count} arm(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
