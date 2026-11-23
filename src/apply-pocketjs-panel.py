#!/usr/bin/env python3
"""Replace pinned dispatcher arms; refuse to build against a changed revision."""
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()
for verb in ('LEVEL', 'STATE'):
    arm = f'        ["{verb}", "brightness"] => pjos_ctl(&["display", "get-brightness"])'
    if arm in text:
        continue
    pattern = rf'^        \["{verb}", "brightness"\] => \{{\n.*?^        \}}\n'
    text, count = re.subn(pattern, arm + '\n' + '            .and_then(|s| s.trim().parse::<u8>().ok())\n            .map(|n| ((u32::from(n) * 100 + 127) / 255).to_string())\n            .unwrap_or_else(|| "unknown".into()),\n', text, flags=re.M | re.S)
    if count != 1:
        sys.exit(f'panel: expected one {verb} brightness arm, found {count}')
path.write_text(text)
