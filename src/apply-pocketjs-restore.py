#!/usr/bin/env python3
"""Add RESUME bridge commands for restoring last session after boot.

Commands:
  RESUME<TAB>get                       -> "none" | "app<TAB><id>" | "rom<TAB><path>"
  RESUME<TAB>set<TAB><kind><TAB><tgt>  -> saves marker
  RESUME<TAB>clear                     -> clears marker
"""
from pathlib import Path
import sys

HELPER = r'''

fn resume_path() -> &'static str { "/storage/.config/pocketjs/resume.state" }

fn resume_get() -> String {
    let Ok(text) = std::fs::read_to_string(resume_path()) else { return "none".into(); };
    let mut kind = String::new();
    let mut target = String::new();
    for line in text.lines() {
        if let Some(v) = line.strip_prefix("kind=") { kind = v.trim().to_string(); }
        else if let Some(v) = line.strip_prefix("target=") { target = v.trim().to_string(); }
    }
    if kind.is_empty() || target.is_empty() { "none".into() } else { format!("{}\t{}", kind, target) }
}

fn resume_set(kind: &str, target: &str) -> String {
    if !["app","rom"].contains(&kind) || target.is_empty() || target.len() > 4096 { return "error:invalid".into(); }
    if target.contains('\n') || target.contains('\r') || target.contains('\0') || target.contains('\t') { return "error:invalid".into(); }
    if kind == "app" && !target.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.') { return "error:invalid".into(); }
    if kind == "rom" && (!target.starts_with("/storage/") || target.split('/').any(|p| p == "." || p == "..")) { return "error:invalid".into(); }
    let _ = std::fs::create_dir_all("/storage/.config/pocketjs");
    match std::fs::write(resume_path(), format!("kind={}\ntarget={}\n", kind, target)) { Ok(_) => "ok".into(), Err(_) => "error:write".into() }
}

fn resume_clear() -> String { let _ = std::fs::remove_file(resume_path()); "ok".into() }
'''

ARM = ('        ["RESUME", "get"] => resume_get(),\n'
       '        ["RESUME", "set", kind, target] => resume_set(kind, target),\n'
       '        ["RESUME", "clear"] => resume_clear(),\n')

ANCHORS = [
    '        ["APPS", "list"] => apps_list(),',
    '        ["ROMS", "list"] => roms_list(),',
    '        ["ROMS"] => games_library(),',
    '        ["ROMSCAN"] => games_scan(),',
    '        ["LANGUAGE"] | ["LANGUAGE", _] => language_command(&fields),',
]


def main(path: str) -> int:
    source = Path(path)
    text = source.read_text()
    if 'fn resume_get' in text:
        print('already applied')
        return 0
    for anchor in ANCHORS:
        if anchor in text:
            source.write_text(text.replace(anchor, ARM + anchor, 1).rstrip() + '\n' + HELPER)
            print('applied via', anchor.strip()[:40])
            return 0
    print('no anchor found', file=sys.stderr)
    return 1


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
