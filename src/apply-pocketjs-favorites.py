#!/usr/bin/env python3
from pathlib import Path
import sys

HELPER = r'''
// BaseOS launcher favorites (v1).
fn launcher_favorites(action: &str, path: &str) -> String {
    let file = std::path::Path::new("/storage/.config/pocketjs/favorites.txt");
    let saved = std::fs::read_to_string(file).unwrap_or_default();
    if action == "list" { return saved; }
    if action != "toggle" || !path.starts_with('/') || path.contains('\n') || path.contains('\r') || path.len() > 4096 {
        return "error: invalid favorite".into();
    }
    let mut entries: Vec<&str> = saved.lines().filter(|line| !line.is_empty() && *line != path).collect();
    let added = !saved.lines().any(|line| line == path);
    if added { entries.push(path); }
    let Some(parent) = file.parent() else { return "error: invalid location".into(); };
    if std::fs::create_dir_all(parent).is_err() { return "error: cannot create directory".into(); }
    let temporary = file.with_extension(format!("tmp.{}", std::process::id()));
    let mut content = entries.join("\n");
    if !content.is_empty() { content.push('\n'); }
    if std::fs::write(&temporary, content).is_err() || std::fs::rename(&temporary, file).is_err() {
        let _ = std::fs::remove_file(temporary);
        return "error: cannot save favorites".into();
    }
    if added { "added".into() } else { "removed".into() }
}

'''

def main(path):
    source = Path(path)
    text = source.read_text()
    if '// BaseOS launcher favorites (v1).' in text:
        return
    anchor = '    match fields.as_slice() {\n'
    if text.count(anchor) != 1 or text.count('pub fn command(') != 1:
        raise SystemExit('favorites: unsupported bridge anchors')
    text = text.replace(anchor, anchor + '        ["FAVORITES", "list"] => launcher_favorites("list", ""),\n        ["FAVORITES", "toggle", path] => launcher_favorites("toggle", path),\n', 1)
    source.write_text(text.replace('pub fn command(', HELPER + 'pub fn command(', 1))

if __name__ == '__main__':
    main(sys.argv[1])
