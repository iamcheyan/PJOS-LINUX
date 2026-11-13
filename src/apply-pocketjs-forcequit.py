#!/usr/bin/env python3
"""Add the one-shot force-quit event without replacing the runtime bridge."""
from pathlib import Path
import sys

HELPER = r'''
// BaseOS force-quit notification (v1): rename claims a single event atomically.
fn consume_force_quit() -> String {
    let marker = "/run/baseos-force-quit";
    let claimed = format!("{marker}.consume.{}", std::process::id());
    if std::fs::rename(marker, &claimed).is_err() { return String::new(); }
    let content = std::fs::read_to_string(&claimed).unwrap_or_default();
    let _ = std::fs::remove_file(&claimed);
    let app = content.trim();
    if app.is_empty() || app.len() > 64 || !app.bytes().all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c)) {
        return String::new();
    }
    app.to_owned()
}

'''

def main(path):
    source = Path(path)
    text = source.read_text()
    if '// BaseOS force-quit notification (v1)' in text:
        return
    anchor = '    match fields.as_slice() {\n'
    if text.count(anchor) != 1 or text.count('pub fn command(') != 1:
        raise SystemExit('forcequit: unsupported bridge anchors')
    text = text.replace(anchor, anchor + '        ["FORCEQUIT"] => consume_force_quit(),\n', 1)
    source.write_text(text.replace('pub fn command(', HELPER + 'pub fn command(', 1))

if __name__ == '__main__':
    main(sys.argv[1])
