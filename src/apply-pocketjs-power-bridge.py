#!/usr/bin/env python3
"""Add the effective screen/automatic-power policy to the device dispatcher.

Support both SETTING timeout/autoPoweroff and legacy STATE/SLEEP/POWER forms.
Read the same overrides as the idle daemon and update them when the user changes
its preference, so a leftover card-side override cannot defeat the settings UI.
"""
from pathlib import Path
import sys

HELPERS = r'''
// BaseOS effective idle policy (v2): UI and daemon must share one preference.
fn idle_policy_read(path: &str, section: Option<&str>, keys: &[&str]) -> Option<String> {
    let content = std::fs::read_to_string(path).ok()?;
    let mut selected = section.is_none();
    for line in content.lines() {
        let line = line.trim();
        if line.starts_with('[') && line.ends_with(']') {
            selected = section.map_or(true, |name| line == format!("[{name}]"));
            continue;
        }
        if !selected || line.starts_with('#') || line.starts_with(';') { continue; }
        if let Some((key, value)) = line.split_once('=') {
            if keys.contains(&key.trim()) && !value.trim().is_empty() {
                return Some(value.trim().to_owned());
            }
        }
    }
    None
}

fn idle_policy_valid(power: bool, value: &str) -> bool {
    if power {
        ["never", "1m", "5m", "10m", "15m", "30m", "1h", "2h"].contains(&value)
    } else {
        ["never", "10s", "30s", "1m", "5m", "15m", "30m", "1h"].contains(&value)
    }
}

fn idle_policy_value(power: bool) -> String {
    let keys: &[&str] = if power { &["auto_stop_timeout", "auto_off_timeout", "poweroff_timeout"] } else { &["timeout"] };
    let configured = idle_policy_read("/storage/.config/baseos/screen-idle.conf", None, keys)
        .or_else(|| idle_policy_read("/storage/.config/pocketjs/runtime.conf", Some(if power { "power" } else { "sleep" }), &["timeout"]));
    let fallback = if power { "never" } else { "30s" };
    match configured.as_deref() {
        Some("off" | "none" | "0") => "never".into(),
        Some(value) if idle_policy_valid(power, value) => value.into(),
        _ => fallback.into(),
    }
}

// Replace a key within its own section, even if that section is not last and
// does not yet contain the key. Write through a sibling file before renaming.
fn idle_policy_write(path: &str, section: Option<&str>, keys: &[&str], value: &str) -> std::io::Result<()> {
    let content = std::fs::read_to_string(path).unwrap_or_default();
    let mut output: Vec<String> = Vec::new();
    let mut selected = section.is_none();
    let mut seen = section.is_none();
    let mut written = false;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            if selected && !written {
                output.push(format!("{} = {}", keys[0], value));
                written = true;
            }
            selected = section.map_or(true, |name| trimmed == format!("[{name}]"));
            seen |= selected;
            output.push(line.into());
            continue;
        }
        if selected && trimmed.split_once('=').is_some_and(|(key, _)| keys.contains(&key.trim())) {
            if !written { output.push(format!("{} = {}", keys[0], value)); written = true; }
        } else {
            output.push(line.into());
        }
    }
    if !written {
        if !seen { if let Some(section) = section { output.push(format!("[{section}]")); } }
        output.push(format!("{} = {}", keys[0], value));
    }
    let path = std::path::Path::new(path);
    if let Some(parent) = path.parent() { std::fs::create_dir_all(parent)?; }
    let temporary = path.with_extension("conf.new");
    std::fs::write(&temporary, output.join("\n") + "\n")?;
    std::fs::rename(temporary, path)
}

fn idle_policy_set(power: bool, value: &str) -> String {
    if !idle_policy_valid(power, value) { return "error:invalid-timeout".into(); }
    let section = if power { "power" } else { "sleep" };
    if idle_policy_write("/storage/.config/pocketjs/runtime.conf", Some(section), &["timeout"], value).is_err() {
        return "error:save-timeout".into();
    }
    let override_path = "/storage/.config/baseos/screen-idle.conf";
    if std::path::Path::new(override_path).exists() {
        let keys: &[&str] = if power { &["auto_stop_timeout", "auto_off_timeout", "poweroff_timeout"] } else { &["timeout"] };
        if idle_policy_write(override_path, None, keys, value).is_err() {
            return "error:save-idle-override".into();
        }
    }
    // Starting a new policy is a new idle interval, not an immediate shutdown
    // based on inactivity that preceded the user's settings change.
    let _ = std::fs::write("/run/screen-idle.stamp", "");
    "ok".into()
}

'''

ARMS = '''        // BaseOS effective idle policy aliases (v2).
        ["SETTING", key] if ["timeout", "autoPoweroff"].contains(key) => idle_policy_value(*key == "autoPoweroff"),
        ["SETTING", key, value] if ["timeout", "autoPoweroff"].contains(key) => idle_policy_set(*key == "autoPoweroff", value),
        ["STATE", key] if ["timeout", "power_timeout"].contains(key) => idle_policy_value(*key == "power_timeout"),
        ["POWER", value] if idle_policy_valid(true, value) => idle_policy_set(true, value),
        ["SLEEP", value] if idle_policy_valid(false, value) => idle_policy_set(false, value),
'''


def main(source_path: str) -> int:
    source = Path(source_path)
    text = source.read_text()
    if '// BaseOS effective idle policy aliases (v2).' in text:
        print('power: effective policy already installed')
        return 0
    anchor = '    match fields.as_slice() {\n'
    if text.count(anchor) != 1:
        raise SystemExit(f'power dispatcher anchor appears {text.count(anchor)} times')
    text = text.replace(anchor, anchor + ARMS, 1)
    function = 'pub fn command('
    if function not in text:
        raise SystemExit('power dispatcher function missing')
    text = text.replace(function, HELPERS + function, 1)
    source.write_text(text)
    print('power: installed effective idle policy and unified/legacy commands')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
