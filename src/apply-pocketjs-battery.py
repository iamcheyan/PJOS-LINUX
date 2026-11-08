#!/usr/bin/env python3
"""Teach the PocketShell bridge about the RG34XX fuel gauge.

The stock bridge looks for battery/BAT0/BAT1/rk817-battery/cw2015-battery. This
panel reports power through ``axp2202-battery``, so the launcher's battery gauge
stayed at "--" and had no charging state to draw. Add the gauge to the level
lookup and a ``LEVEL battery-status`` arm returning charging / discharging /
full / unknown, which is what the status bar polls.

Idempotent: safe to run on an already patched file.

    python3 src/apply-pocketjs-battery.py <pocketshell-launcher.rs>
"""
from pathlib import Path
import sys

OLD_LIST = 'for name in ["battery", "BAT0", "BAT1", "rk817-battery", "cw2015-battery"] {'
NEW_LIST = 'for name in ["axp2202-battery", "battery", "BAT0", "BAT1", "rk817-battery", "cw2015-battery"] {'
ANCHOR = '        // First IPv4 address of an interface that is up and not loopback'
ARM = '''        // Charging state of the fuel gauge: "charging" | "discharging" | "full" | "unknown".
        ["LEVEL", "battery-status"] => {
            for name in ["axp2202-battery", "battery", "BAT0", "BAT1", "rk817-battery", "cw2015-battery"] {
                let base = std::path::Path::new("/sys/class/power_supply").join(name);
                if let Ok(raw) = std::fs::read_to_string(base.join("status")) {
                    return match raw.trim().to_ascii_lowercase().as_str() {
                        "charging" => "charging".into(),
                        "discharging" => "discharging".into(),
                        "full" | "not charging" => "full".into(),
                        _ => "unknown".into(),
                    };
                }
            }
            "unknown".into()
        }
'''


def main(path: Path) -> int:
    text = path.read_text()
    changed = False
    if '"axp2202-battery"' not in text:
        if OLD_LIST not in text:
            print("battery: fuel-gauge list anchor missing", file=sys.stderr)
            return 1
        text = text.replace(OLD_LIST, NEW_LIST)
        changed = True
    if '"LEVEL", "battery-status"' not in text:
        if ANCHOR not in text:
            print("battery: LEVEL anchor missing", file=sys.stderr)
            return 1
        text = text.replace(ANCHOR, ARM + ANCHOR, 1)
        changed = True
    if changed:
        path.write_text(text)
    print("battery arm present:", '"LEVEL", "battery-status"' in text)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
