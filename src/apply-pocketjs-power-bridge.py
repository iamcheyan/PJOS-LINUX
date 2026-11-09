#!/usr/bin/env python3
"""Add auto power-off idle settings to the PocketShell launcher bridge.

Commands (tab-separated, via host.__launcher):
  STATE<TAB>power_timeout        -> "never" | "1m" | ...
  POWER<TAB><timeout>            -> persists [power] timeout=... in runtime.conf
                                    and returns "Auto power-off: <label>"

The timeout is enforced by baseos-screen-idle on the device; the bridge only
stores the preference so the launcher UI can read/change it.
"""
from pathlib import Path
import sys

ANCHOR = '        [\"SLEEP\", timeout] if [\"never\", \"10s\", \"30s\", \"1m\", \"5m\", \"15m\", \"30m\", \"1h\"].contains(timeout) => {'

STATE_ANCHOR = '        [\"STATE\", \"timeout\"] => {'

STATE_ARM = '''        [\"STATE\", \"power_timeout\"] => {
            let content = std::fs::read_to_string("/storage/.config/pocketjs/runtime.conf").unwrap_or_default();
            let mut in_section = false;
            let configured = content.lines().find_map(|line| {
                let trimmed = line.trim();
                if trimmed.starts_with('[') && trimmed.ends_with(']') { in_section = trimmed == "[power]"; return None; }
                if in_section { return trimmed.split_once('=').filter(|(name, _)| name.trim() == "timeout").map(|(_, value)| value.trim().to_string()); }
                None
            });
            configured.unwrap_or_else(|| "never".into())
        }
'''

POWER_ARM = '''        [\"POWER\", timeout] if [\"never\", \"1m\", \"5m\", \"10m\", \"15m\", \"30m\", \"1h\", \"2h\"].contains(timeout) => {
            let path = std::path::Path::new("/storage/.config/pocketjs/runtime.conf");
            let _ = std::fs::create_dir_all("/storage/.config/pocketjs");
            let mut content = std::fs::read_to_string(path).unwrap_or_default();
            let mut in_section = false;
            let mut replaced = false;
            let mut seen_power = false;
            let mut new_lines: Vec<String> = Vec::new();
            for line in content.lines() {
                let trimmed = line.trim();
                if trimmed.starts_with('[') && trimmed.ends_with(']') {
                    in_section = trimmed == "[power]";
                    if in_section { seen_power = true; }
                    new_lines.push(line.to_string());
                    continue;
                }
                if in_section && trimmed.starts_with("timeout") {
                    new_lines.push(format!("timeout = {}", timeout));
                    replaced = true;
                } else {
                    new_lines.push(line.to_string());
                }
            }
            if !replaced {
                if !content.is_empty() && !content.ends_with('\\n') { new_lines.push(String::new()); }
                if !seen_power { new_lines.push("[power]".to_string()); }
                new_lines.push(format!("timeout = {}", timeout));
            }
            match std::fs::write(path, new_lines.join("\\n") + "\\n") {
                Ok(_) => {
                    let label = if *timeout == "never" { "Never".to_string() } else { timeout.to_string() };
                    format!("Auto power-off: {}", label)
                }
                Err(_) => "Failed to save auto power-off".into(),
            }
        }
'''


def main(source_path: str) -> int:
    source = Path(source_path)
    text = source.read_text()
    changed = False
    if '"STATE", "power_timeout"' not in text:
        if text.count(STATE_ANCHOR) != 1:
            raise SystemExit(f"STATE anchor appears {text.count(STATE_ANCHOR)} times")
        text = text.replace(STATE_ANCHOR, STATE_ARM + STATE_ANCHOR, 1)
        changed = True
        print("applied STATE power_timeout")
    else:
        print("already applied: STATE power_timeout")
    if '["POWER", timeout]' not in text:
        if text.count(ANCHOR) != 1:
            raise SystemExit(f"SLEEP anchor appears {text.count(ANCHOR)} times")
        text = text.replace(ANCHOR, POWER_ARM + ANCHOR, 1)
        changed = True
        print("applied POWER command")
    else:
        print("already applied: POWER command")
    if changed:
        source.write_text(text)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
