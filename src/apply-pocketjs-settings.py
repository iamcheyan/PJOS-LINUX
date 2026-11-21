#!/usr/bin/env python3
"""Add BaseOS's SETTING adapter without intercepting other domains."""
import re
from pathlib import Path
import sys

HELPER = r'''
fn baseos_setting(key: &str, value: Option<&str>) -> String {
    let helper = ["/storage/System/compat/bin/baseos-settings", "/usr/share/pocketshell/System/compat/bin/baseos-settings"]
        .into_iter().find(|path| std::path::Path::new(path).is_file());
    let Some(helper) = helper else { return "error:unsupported".into() };
    let mut cmd = Command::new("/usr/bin/timeout");
    cmd.args(["2", helper, key]);
    if let Some(value) = value { cmd.arg(value); }
    match cmd.stdin(Stdio::null()).stderr(Stdio::null()).output() {
        Ok(out) => {
            let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if text.is_empty() { "error:unavailable".into() } else { text }
        }
        Err(_) => "error:unavailable".into(),
    }
}

fn baseos_volume_state() -> String {
    for helper in ["/storage/System/compat/bin/heya-control", "/usr/share/pocketshell/System/compat/bin/heya-control"] {
        if let Some(value) = run(helper, &["volume-state"]) {
            if let Ok(level) = value.trim().parse::<u32>() {
                if level <= 100 { return level.to_string(); }
            }
        }
    }
    "unknown".into()
}
'''

KEYS = '["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb", "ssh", "mdns", "showClock", "animations", "fontSize", "themeColor", "bootResume", "pixelateCovers"]'
LAST_PLAYED = '        ["SETTING", "games.lastPlayed"] => baseos_setting("games.lastPlayed", None),\n        ["SETTING", "games.lastPlayed", value] => baseos_setting("games.lastPlayed", Some(value)),\n'
GENERIC = r'''        ["SETTING", "games.lastPlayed"] => baseos_setting("games.lastPlayed", None),
        ["SETTING", "games.lastPlayed", value] => baseos_setting("games.lastPlayed", Some(value)),
        ["SETTING", key] if key.starts_with("series.") && key.ends_with(".lastVariant") => baseos_setting(key, None),
        ["SETTING", key, value] if key.starts_with("series.") && key.ends_with(".lastVariant") => baseos_setting(key, Some(value)),
        ["STATE", "bootResume"] => baseos_setting("bootResume", None),
        ["STATE", key] if key.starts_with("series.") && key.ends_with(".lastVariant") => baseos_setting(key, None),
'''
ARMS = (
    f'        ["SETTING", key] if {KEYS}.contains(key) => baseos_setting(key, None),\n'
    f'        ["SETTING", key, value] if {KEYS}.contains(key) => baseos_setting(key, Some(value)),\n'
    + GENERIC +
    '        ["SETTING", "volume"] | ["STATE", "volume"] | ["LEVEL", "volume"] => baseos_volume_state(),\n'
)

LEGACY_KEYS = [
    '["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb"]',
    '["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb", "ssh", "mdns", "showClock", "animations", "fontSize", "themeColor"]',
    '["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb", "ssh", "mdns", "showClock", "animations", "fontSize", "themeColor", "zeldaLastRom"]',
]


SETTING_READ = re.compile(r'        \["SETTING", key\] if \[[^\]]*\]\.contains\(key\) => baseos_setting\(key, None\),')
SETTING_WRITE = re.compile(r'        \["SETTING", key, value\] if \[[^\]]*\]\.contains\(key\) => baseos_setting\(key, Some\(value\)\),')


def main(path):
    text = path.read_text()
    if 'fn baseos_setting(' in text:
        # Replace whatever whitelist an earlier revision shipped with. Exact
        # string replacement missed revisions whose list had a different shape,
        # which left fontSize/themeColor rejected at runtime.
        text, reads = SETTING_READ.subn(
            f'        ["SETTING", key] if {KEYS}.contains(key) => baseos_setting(key, None),',
            text,
        )
        text, writes = SETTING_WRITE.subn(
            f'        ["SETTING", key, value] if {KEYS}.contains(key) => baseos_setting(key, Some(value)),',
            text,
        )
        if reads < 1 or writes < 1 or text.count('"fontSize"') < 2:
            raise SystemExit('settings: existing dispatcher arms missing or changed')
        volume_arm = '        ["SETTING", "volume"] | ["STATE", "volume"] | ["LEVEL", "volume"] => baseos_volume_state(),\n'
        if '"SETTING", "games.lastPlayed"' not in text and volume_arm in text:
            text = text.replace(volume_arm, LAST_PLAYED + volume_arm, 1)
        path.write_text(text)
        print('settings: already applied')
        return
    anchor = '    match fields.as_slice() {\n'
    if text.count(anchor) != 1:
        raise SystemExit('settings: dispatcher anchor missing or ambiguous')
    text = text.replace(anchor, anchor + ARMS, 1)
    path.write_text(HELPER + '\n' + text)
    print('settings: BaseOS SETTING adapter installed')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
