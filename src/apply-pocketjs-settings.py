#!/usr/bin/env python3
"""Add BaseOS's SETTING adapter without intercepting other domains."""
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
ARMS = r'''        ["SETTING", key] if ["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb", "ssh", "mdns", "showClock", "animations", "fontSize", "themeColor", "zeldaLastRom"].contains(key) => baseos_setting(key, None),
        ["SETTING", key, value] if ["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb", "ssh", "mdns", "showClock", "animations", "fontSize", "themeColor", "zeldaLastRom"].contains(key) => baseos_setting(key, Some(value)),
        ["SETTING", "volume"] | ["STATE", "volume"] | ["LEVEL", "volume"] => baseos_volume_state(),
'''

def main(path):
    text = path.read_text()
    if 'fn baseos_setting(' in text:
        old_keys = '["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb"]'
        new_keys = '["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb", "ssh", "mdns", "showClock", "animations", "fontSize", "themeColor"]'
        text = text.replace(old_keys + '.contains(key) => baseos_setting', new_keys + '.contains(key) => baseos_setting')
        path.write_text(text)
        print('settings: already applied')
        return
    anchor = '    match fields.as_slice() {\n'
    if text.count(anchor) != 1:
        raise SystemExit('settings: dispatcher anchor missing or ambiguous')
    text = text.replace(anchor, anchor + ARMS, 1)
    path.write_text(HELPER + '\n' + text)
    print('settings: BaseOS SETTING adapter installed')

if __name__ == '__main__': main(Path(sys.argv[1]))
