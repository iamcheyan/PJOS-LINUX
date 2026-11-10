#!/usr/bin/env python3
"""Teach the PocketShell bridge about the RG34XX fuel gauge.

The stock bridge looks for battery/BAT0/BAT1/rk817-battery/cw2015-battery. This
panel reports power through ``axp2202-battery``, so the launcher's battery gauge
stayed at "--" and had no charging state to draw. Add the gauge to the level
lookup and a ``LEVEL battery-status`` arm returning charging / discharging /
full / unknown, which is what the status bar polls.

Tolerant on purpose: the pinned bridge revision is not always the one this
patch was written against (the vendored script and the ROCKNIX checkout drift),
and a cosmetic battery gauge must not break the whole runtime build. The exact
anchor is tried first, then a regex over the LEVEL battery arm, then a warning.

Idempotent: safe to run on an already patched file.

    python3 src/apply-pocketjs-battery.py <pocketshell-launcher.rs>
"""
from pathlib import Path
import re
import sys

OLD_LIST = 'for name in ["battery", "BAT0", "BAT1", "rk817-battery", "cw2015-battery"] {'
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

# Any `for name in [ ... ]` list naming BAT0/BAT1 — the fuel-gauge lookup, in
# whatever revision the build is using.
LIST_RE = re.compile(r'for name in \[([^\]]*"BAT0"[^\]]*)\]\s*\{')


def add_gauge(text: str) -> tuple[str, str]:
    """Return (text, status) with axp2202-battery first in the gauge list."""
    if '"axp2202-battery"' in text:
        return text, "already present"
    if OLD_LIST in text:
        return text.replace(OLD_LIST, OLD_LIST.replace('["battery"', '["axp2202-battery", "battery"')), "exact list"

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        if '"axp2202-battery"' in inner:
            return m.group(0)
        return 'for name in ["axp2202-battery", ' + inner.strip() + '] {'

    new_text, count = LIST_RE.subn(repl, text, count=1)
    if count:
        return new_text, "regex list"
    return text, "not found"


def main(path: Path) -> int:
    text = path.read_text()
    changed = False

    text, status = add_gauge(text)
    if status == "not found":
        print("battery: no fuel-gauge lookup found; gauge stays '--' (not fatal)", file=sys.stderr)
    else:
        changed = changed or status != "already present"
        print(f"battery: gauge list {status}")

    if '"LEVEL", "battery-status"' not in text:
        if ANCHOR in text:
            text = text.replace(ANCHOR, ARM + ANCHOR, 1)
            changed = True
            print("battery: charging-state arm added")
        else:
            # Fall back to inserting before the LEVEL battery arm.
            arm_re = re.compile(r'(\n\s*\["LEVEL", "battery"\] =>)')
            new_text, count = arm_re.subn(lambda m: "\n" + ARM.rstrip("\n") + m.group(1), text, count=1)
            if count:
                text = new_text
                changed = True
                print("battery: charging-state arm added (regex anchor)")
            else:
                print("battery: no anchor for the charging-state arm (not fatal)", file=sys.stderr)
    else:
        print("battery: arm already present")

    if changed:
        path.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
