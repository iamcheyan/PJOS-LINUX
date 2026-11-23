#!/usr/bin/env python3
"""Replace pinned dispatcher arms; refuse to build against a changed revision."""
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()
arm = '''        ["LEVEL", field @ ("battery" | "battery-status")] => {
            let Some(data) = pjos_ctl(&["power", "battery"]) else { return "unknown".into() };
            let get = |prefix: &str| data.lines().find_map(|line| line.strip_prefix(prefix));
            if get("present=") != Some("yes") { return "unknown".into(); }
            if *field == "battery" {
                get("capacity=").and_then(|n| n.parse::<u8>().ok()).filter(|n| *n <= 100)
                    .map(|n| n.to_string()).unwrap_or_else(|| "unknown".into())
            } else {
                match get("status=") {
                    Some("Charging") => "charging", Some("Discharging") => "discharging",
                    Some("Full") => "full", _ => "unknown",
                }.into()
            }
        }
'''
if arm not in text:
    pattern = r'^        \["LEVEL", "battery"\] => \{\n.*?^        \}\n'
    text, count = re.subn(pattern, arm, text, flags=re.M | re.S)
    if count != 1:
        sys.exit(f'battery: expected one LEVEL battery arm, found {count}')
    path.write_text(text)
