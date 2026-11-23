#!/usr/bin/env python3
"""Replace pinned dispatcher arms; refuse to build against a changed revision."""
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()
if 'fn pjos_ctl(' not in text:
    for verb in ('STATE', 'LEVEL'):
        pattern = rf'^        \["{verb}", "volume"\] => \{{\n.*?^        \}}\n'
        text, count = re.subn(pattern, '', text, flags=re.M | re.S)
        if count != 1:
            sys.exit(f'bridge: expected one {verb} volume arm, found {count}')
    path.write_text(text + '''
fn pjos_ctl(args: &[&str]) -> Option<String> {
    let ctl = std::env::var("PJOS_BASEOSCTL").unwrap_or_else(|_| "/usr/sbin/baseosctl".into());
    if !std::path::Path::new(&ctl).is_absolute() { return None; }
    run(&ctl, args)
}
''')
