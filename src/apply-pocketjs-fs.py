#!/usr/bin/env python3
from pathlib import Path
import sys

HELPER = r'''
// BaseOS File System read-only browser.
fn fs_list(path: &str) -> String {
    let clean = path.trim();
    let target = if clean.is_empty() { "/storage" } else { clean };
    let mut entries = Vec::new();
    if let Ok(dir) = std::fs::read_dir(target) {
        for entry in dir.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with('.') && name != ".config" {
                continue;
            }
            let is_dir = entry.file_type().map(|t| t.is_dir()).unwrap_or(false);
            let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
            entries.push((is_dir, name, size));
        }
    } else {
        return "error:cannot_read".into();
    }
    entries.sort_by(|a, b| {
        b.0.cmp(&a.0).then_with(|| a.1.to_lowercase().cmp(&b.1.to_lowercase()))
    });
    let mut lines = Vec::new();
    for (is_dir, name, size) in entries {
        lines.push(format!("{}\t{}\t{}", if is_dir { "dir" } else { "file" }, name, size));
    }
    lines.join("\n")
}

fn fs_read(path: &str) -> String {
    let clean = path.trim();
    if clean.is_empty() || !clean.starts_with('/') {
        return "error:invalid_path".into();
    }
    match std::fs::File::open(clean) {
        Ok(file) => {
            use std::io::Read;
            let mut handle = file.take(32768);
            let mut bytes = Vec::new();
            if handle.read_to_end(&mut bytes).is_err() {
                return "error:cannot_read".into();
            }
            if bytes.iter().take(512).any(|&b| b == 0) {
                return "error:binary_file".into();
            }
            match String::from_utf8(bytes) {
                Ok(s) => s,
                Err(_) => "error:binary_or_invalid_utf8".into(),
            }
        }
        Err(e) => format!("error:{}", e),
    }
}

'''

def main(path):
    source = Path(path)
    text = source.read_text()
    if '// BaseOS File System read-only browser.' in text:
        return
    anchor = '    match fields.as_slice() {\n'
    if text.count(anchor) != 1 or text.count('pub fn command(') != 1:
        raise SystemExit('fs: unsupported bridge anchors')
    arms = '        ["FS", "list", path] => fs_list(path),\n        ["FS", "read", path] => fs_read(path),\n'
    text = text.replace(anchor, anchor + arms, 1)
    source.write_text(text.replace('pub fn command(', HELPER + 'pub fn command(', 1))

if __name__ == '__main__':
    main(sys.argv[1])
