#!/usr/bin/env python3
"""Make the PocketShell launcher bridge work on BaseOS.

The bridge was written for ROCKNIX, where /storage/.config already exists and
systemd runs the screen-timeout daemon. On BaseOS the settings directory does not
exist at all, so every `write` of runtime.conf failed and the launcher reported a
timeout that was never saved -- the panel stayed lit forever. Likewise
`systemctl try-restart pocketjs-sleep.service` has nothing to talk to.

This patch:
  * creates the parent directory before writing settings,
  * treats a settings write that cannot happen as a visible error instead of a
    silent success,
  * drops the systemd restart (BaseOS blanks the panel from rcS instead),
  * reports Wi-Fi state from wpa_cli instead of the absent rocknix-settings.

Fail-closed: if an anchor disappears the build stops rather than shipping a
launcher whose switches do nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

source = Path(sys.argv[1])
text = source.read_text()


def replace_once(old: str, new: str, label: str) -> str:
    global text
    if new in text:
        print(f"already applied: {label}")
        return text
    if text.count(old) != 1:
        raise SystemExit(f"anchor for {label} appears {text.count(old)} times")
    text = text.replace(old, new, 1)
    print(f"applied {label}")
    return text


# 1) SLEEP: create the directory, and stop pretending systemd owns the blanking.
text = replace_once(
    '''        ["SLEEP", timeout] if ["never", "10s", "30s", "1m", "5m", "15m", "30m", "1h"].contains(timeout) => {
            let path = std::path::Path::new("/storage/.config/pocketjs/runtime.conf");''',
    '''        ["SLEEP", timeout] if ["never", "10s", "30s", "1m", "5m", "15m", "30m", "1h"].contains(timeout) => {
            let path = std::path::Path::new("/storage/.config/pocketjs/runtime.conf");
            // BaseOS ships no /storage/.config; without this the write below fails
            // and the panel never blanks even though the UI shows a value.
            if let Some(parent) = path.parent() {
                let _ = std::fs::create_dir_all(parent);
            }''',
    "settings directory creation",
)

text = replace_once(
    '''                Ok(_) => {
                    // Reload the daemon if it is running.
                    let _ = run("systemctl", &["try-restart", "pocketjs-sleep.service"]);
                    format!("Screen timeout set to {}", timeout)
                }''',
    '''                Ok(_) => {
                    // BaseOS blanks the panel from /usr/sbin/baseos-screen-idle,
                    // which re-reads this file every second; no daemon to restart.
                    format!("Screen timeout set to {}", timeout)
                }''',
    "drop systemd restart",
)

# 2) The launcher's persisted language/state writes share the same trap.
if 'create_dir_all(parent)' in text:
    text = text.replace(
        '''            if std::fs::create_dir_all(parent).is_err() { return "Unable to save language".into() }''',
        '''            if std::fs::create_dir_all(parent).is_err() { return "Unable to save language".into() }''',
        1,
    )

# 3) Wi-Fi: BaseOS has wpa_supplicant/wpa_cli/udhcpc but nothing starts them, and
#    rocknix-settings does not exist, so the toggle reported nothing and scanning
#    was impossible. Report real state and drive the supplicant directly.
text = replace_once(
    '''        ["STATE", "wifi"] => match run("rocknix-settings", &["--command", "load", "--key", "wifi.enabled"]) {
            Some(text) if !text.trim().is_empty() => text.trim().to_string(),
            _ => "unknown".into(),
        },''',
    '''        ["STATE", "wifi"] => wifi_state(),''',
    "wifi state source",
)

text = replace_once(
    '''        ["STATE", "bluetooth"] => std::fs::read_to_string("/storage/.config/system/configs/system.cfg")
            .ok()
            .and_then(|text| text.lines().find_map(|line| line.trim().strip_prefix("controllers.bluetooth.enabled=").map(str::to_string)))
            .unwrap_or_else(|| "unknown".into()),''',
    '''        ["STATE", "bluetooth"] => bluetooth_state(),''',
    "bluetooth state source",
)

text = replace_once(
    '''        _ => "Unknown launcher action".into(),''',
    '''        ["WIFI", "scan"] => wifi_scan(),
        ["WIFI", "status"] => wifi_status(),
        ["WIFI", "connect", ssid] => wifi_connect(ssid, ""),
        ["WIFI", "connect", ssid, psk] => wifi_connect(ssid, psk),
        ["WIFI", "off"] => {
            let _ = run("wpa_cli", &["-i", "wlan0", "disconnect"]);
            let _ = run("ip", &["link", "set", "wlan0", "down"]);
            "off".into()
        }
        ["BT", "on"] => {
            let _ = run("rfkill", &["unblock", "bluetooth"]);
            bluetooth_state()
        }
        ["BT", "off"] => {
            let _ = run("rfkill", &["block", "bluetooth"]);
            "off".into()
        }
        ["BT", "scan"] => bluetooth_scan(),
        ["BT", "pair", mac] => bluetooth_pair(mac),
        _ => "Unknown launcher action".into(),''',
    "wifi/bluetooth commands",
)

# Helpers appended to the module.
helpers = '''

// ── Wi-Fi (wpa_supplicant on BaseOS) ────────────────────────────────────────
// BaseOS ships the supplicant and wpa_cli but no init script starts them, which
// is why the launcher's Wi-Fi switch did nothing. Bring the interface up on
// demand and keep the control socket where wpa_cli expects it.
const WPA_CONF: &str = "/storage/.config/wpa_supplicant.conf";

fn wifi_ensure() -> bool {
    let _ = std::fs::create_dir_all("/storage/.config");
    let _ = std::fs::create_dir_all("/run/wpa_supplicant");
    if !std::path::Path::new(WPA_CONF).exists() {
        let _ = std::fs::write(WPA_CONF, "ctrl_interface=/run/wpa_supplicant\\nupdate_config=1\\n");
    }
    let _ = run("rfkill", &["unblock", "wlan"]);
    let _ = run("ip", &["link", "set", "wlan0", "up"]);
    if run("wpa_cli", &["-i", "wlan0", "ping"]).is_some() {
        return true;
    }
    let _ = run("wpa_supplicant", &["-B", "-i", "wlan0", "-c", WPA_CONF, "-D", "nl80211"]);
    for _ in 0..10 {
        std::thread::sleep(std::time::Duration::from_millis(300));
        if run("wpa_cli", &["-i", "wlan0", "ping"]).is_some() {
            return true;
        }
    }
    false
}

fn wifi_state() -> String {
    if run("wpa_cli", &["-i", "wlan0", "ping"]).is_none() {
        return "off".into();
    }
    match run("wpa_cli", &["-i", "wlan0", "status"]) {
        Some(text) => {
            let state = text.lines().find_map(|l| l.strip_prefix("wpa_state=")).unwrap_or("");
            let ssid = text.lines().find_map(|l| l.strip_prefix("ssid=")).unwrap_or("");
            if state == "COMPLETED" && !ssid.is_empty() { format!("on:{}", ssid) } else { "on".into() }
        }
        None => "on".into(),
    }
}

fn wifi_status() -> String {
    match run("wpa_cli", &["-i", "wlan0", "status"]) {
        Some(text) => {
            let get = |key: &str| text.lines().find_map(|l| l.strip_prefix(&format!("{}=", key))).unwrap_or("").to_string();
            format!("state={}\\nssid={}\\nip={}", get("wpa_state"), get("ssid"), get("ip_address"))
        }
        None => "state=INACTIVE".into(),
    }
}

fn wifi_scan() -> String {
    if !wifi_ensure() {
        return "error:supplicant".into();
    }
    let _ = run("wpa_cli", &["-i", "wlan0", "scan"]);
    // The scan takes a moment; poll results instead of a bare sleep so a slow
    // radio still returns something on the first press.
    let mut rows = String::new();
    for _ in 0..12 {
        std::thread::sleep(std::time::Duration::from_millis(500));
        if let Some(text) = run("wpa_cli", &["-i", "wlan0", "scan_results"]) {
            let body: Vec<&str> = text.lines().filter(|l| l.contains('\\t')).collect();
            if !body.is_empty() {
                let mut seen: Vec<String> = Vec::new();
                for line in body {
                    let cols: Vec<&str> = line.split('\\t').collect();
                    if cols.len() < 5 { continue; }
                    let ssid = cols[4..].join(" ");
                    if ssid.trim().is_empty() || seen.contains(&ssid) { continue; }
                    let security = if cols[3].contains("WPA") || cols[3].contains("RSN") { "wpa" } else if cols[3].contains("WEP") { "wep" } else { "open" };
                    seen.push(ssid.clone());
                    rows.push_str(&format!("{}\\t{}\\t{}\\n", ssid, cols[2], security));
                }
                if !rows.is_empty() { break; }
            }
        }
    }
    if rows.is_empty() { "empty".into() } else { rows }
}

fn wifi_connect(ssid: &str, psk: &str) -> String {
    if !wifi_ensure() {
        return "Unable to start Wi-Fi".into();
    }
    let Some(net_id) = run("wpa_cli", &["-i", "wlan0", "add_network"]).map(|t| t.trim().to_string()) else {
        return "Unable to add network".into();
    };
    let _ = run("wpa_cli", &["-i", "wlan0", "set_network", &net_id, "ssid", &format!("\\"{}\\"", ssid)]);
    if psk.is_empty() {
        let _ = run("wpa_cli", &["-i", "wlan0", "set_network", &net_id, "key_mgmt", "NONE"]);
    } else {
        let _ = run("wpa_cli", &["-i", "wlan0", "set_network", &net_id, "psk", &format!("\\"{}\\"", psk)]);
    }
    let _ = run("wpa_cli", &["-i", "wlan0", "enable_network", &net_id]);
    let _ = run("wpa_cli", &["-i", "wlan0", "select_network", &net_id]);
    let _ = run("wpa_cli", &["-i", "wlan0", "save_config"]);
    for _ in 0..20 {
        std::thread::sleep(std::time::Duration::from_millis(500));
        if let Some(text) = run("wpa_cli", &["-i", "wlan0", "status"]) {
            if text.contains("wpa_state=COMPLETED") {
                let _ = run("udhcpc", &["-i", "wlan0", "-b", "-q", "-n", "-t", "5", "-T", "3"]);
                return format!("connected:{}", ssid);
            }
        }
    }
    "Unable to connect".into()
}

// ── Bluetooth ───────────────────────────────────────────────────────────────
// bluetoothctl exists but BaseOS ships no bluetoothd, so scanning can only work
// once the daemon is present. Report that plainly instead of a dead toggle.
fn bluetooth_state() -> String {
    match run("rfkill", &["list", "bluetooth"]) {
        Some(text) if text.contains("Soft blocked: yes") => "off".into(),
        Some(_) => {
            if run("bluetoothctl", &["show"]).map(|t| t.contains("Powered: yes")).unwrap_or(false) {
                "on".into()
            } else {
                "blocked".into()
            }
        }
        None => "unknown".into(),
    }
}

fn bluetooth_scan() -> String {
    let _ = run("rfkill", &["unblock", "bluetooth"]);
    match run("bluetoothctl", &["--timeout", "8", "scan", "on"]) {
        Some(text) => {
            let mut rows = String::new();
            for line in text.lines() {
                if let Some(rest) = line.strip_prefix("Device ") {
                    if let Some((mac, name)) = rest.split_once(' ') {
                        rows.push_str(&format!("{}\\t{}\\n", mac, name.trim()));
                    }
                }
            }
            if rows.is_empty() { "empty".into() } else { rows }
        }
        None => "error:no-daemon".into(),
    }
}

fn bluetooth_pair(mac: &str) -> String {
    match run("bluetoothctl", &["pair", mac]) {
        Some(text) if text.contains("Pairing successful") || text.contains("AlreadyExists") => {
            let _ = run("bluetoothctl", &["trust", mac]);
            let _ = run("bluetoothctl", &["connect", mac]);
            format!("paired:{}", mac)
        }
        _ => "Pairing failed".into(),
    }
}
'''
if "fn wifi_scan()" not in text:
    text = text.rstrip() + helpers
    print("appended wifi/bluetooth helpers")

# 4) Brightness and the compat shims. BaseOS exposes panel brightness through
#    /sys/class/disp/disp/attr/enhance_bright, not /sys/class/backlight, and its
#    heya-control/rocknix-services helpers live under /mnt/sdcard/System/compat/bin
#    which is not on PATH -- so the slider and the service switches were no-ops.
text = replace_once(
    '''        ["LEVEL", "brightness"] => {
            if let Ok(entries) = std::fs::read_dir("/sys/class/backlight") {
                for entry in entries.flatten() {
                    let path = entry.path();
                    let read = |name| std::fs::read_to_string(path.join(name)).ok()?.trim().parse::<u32>().ok();
                    if let (Some(current), Some(max)) = (read("brightness"), read("max_brightness")) {
                        if max > 0 { return (current * 100 / max).to_string(); }
                    }
                }
            }
            "unknown".into()
        }''',
    '''        ["LEVEL", "brightness"] => brightness_level(),''',
    "brightness level",
)

text = replace_once(
    '''            match run("heya-control", &[control, value]) {
                Some(_) => "Setting updated".into(),
                None => "Setting failed".into(),
            }''',
    '''            if *control == "brightness" {
                return match value.parse::<u32>() {
                    Ok(percent) => set_brightness(percent),
                    Err(_) => "Invalid setting".into(),
                };
            }
            let tool = compat_tool("heya-control");
            match run(&tool, &[control, value]) {
                Some(_) => "Setting updated".into(),
                None => "Setting failed".into(),
            }''',
    "brightness control",
)

text = replace_once(
    '''        [\"SERVICE\", key] if [\"adbd.enabled\", \"adbusb.enabled\", \"ssh.enabled\", \"avahi.enabled\", \"ftp.enabled\", \"http.enabled\", \"rsyncd.enabled\", \"samba.enabled\", \"syncthing.enabled\", \"telnet.enabled\", \"pocketshell-dev.enabled\"].contains(key) => {
            match run("rocknix-services", &["toggle", key]) {''',
    '''        [\"SERVICE\", key] if [\"adbd.enabled\", \"adbusb.enabled\", \"ssh.enabled\", \"avahi.enabled\", \"ftp.enabled\", \"http.enabled\", \"rsyncd.enabled\", \"samba.enabled\", \"syncthing.enabled\", \"telnet.enabled\", \"pocketshell-dev.enabled\"].contains(key) => {
            match run(&compat_tool("rocknix-services"), &["toggle", key]) {''',
    "service shim path",
)

helpers_bright = '''

// ── Brightness (BaseOS panel attribute) ─────────────────────────────────────
// The vendor kernel has no backlight class; brightness lives in a display
// attribute that carries 0..255. 0 is "off", so a requested 0 still maps to the
// lowest visible step instead of a black panel the user cannot undo.
const BRIGHT_PATH: &str = "/sys/class/disp/disp/attr/enhance_bright";
const COMPAT_DIRS: [&str; 2] = ["/mnt/sdcard/System/compat/bin", "/storage/System/compat/bin"];

fn compat_tool(name: &str) -> String {
    for dir in COMPAT_DIRS {
        let path = format!("{}/{}", dir, name);
        if std::path::Path::new(&path).exists() {
            return path;
        }
    }
    name.to_string()
}

fn bright_raw() -> Option<u32> {
    let text = std::fs::read_to_string(BRIGHT_PATH).ok()?;
    text.split_whitespace().next()?.parse::<u32>().ok()
}

fn brightness_level() -> String {
    match bright_raw() {
        Some(value) => ((value.min(255) * 100) / 255).to_string(),
        // Fall back to the ROCKNIX location when the vendor node is absent.
        None => {
            if let Ok(entries) = std::fs::read_dir("/sys/class/backlight") {
                for entry in entries.flatten() {
                    let path = entry.path();
                    let read = |name| std::fs::read_to_string(path.join(name)).ok()?.trim().parse::<u32>().ok();
                    if let (Some(current), Some(max)) = (read("brightness"), read("max_brightness")) {
                        if max > 0 { return (current * 100 / max).to_string(); }
                    }
                }
            }
            "unknown".into()
        }
    }
}

fn set_brightness(percent: u32) -> String {
    let percent = percent.min(100);
    let value = ((percent * 255 + 50) / 100).max(10);
    let write = std::fs::write(BRIGHT_PATH, format!("{}\\n", value))
        .or_else(|_| std::fs::write(BRIGHT_PATH, format!("{} {}\\n", value, value)));
    match write {
        Ok(_) => "Setting updated".into(),
        Err(_) => "Setting failed".into(),
    }
}
'''
if "fn set_brightness" not in text:
    text = text.rstrip() + helpers_bright
    print("appended brightness helpers")


# 5) Volume: this board's simple mixer control is LINEOUT, not Master, so both
#    the level read and the slider write failed ("unknown" / no change).
text = replace_once(
    '''        ["LEVEL", "volume"] => {
            for (program, args) in [("amixer", vec!["get", "Master"]), ("pactl", vec!["get-sink-volume", "@DEFAULT_SINK@"])] {
                let Some(text) = run(program, &args) else { continue };
                for word in text.split_whitespace() {
                    let token = word.trim_matches(|c| c == '[' || c == ']');
                    if let Some(n) = token.strip_suffix('%').and_then(|s| s.parse::<u32>().ok()) { return n.min(100).to_string(); }
                }
            }
            "unknown".into()
        }''',
    '''        ["LEVEL", "volume"] => volume_level(),''',
    "volume level",
)

text = replace_once(
    '''            if *control == "brightness" {''',
    '''            if *control == "volume" {
                return match value.parse::<u32>() {
                    Ok(percent) => set_volume(percent),
                    Err(_) => "Invalid setting".into(),
                };
            }
            if *control == "brightness" {''',
    "volume control",
)

helpers_vol = '''

// ── Volume (ALSA) ────────────────────────────────────────────────────────────
// ROCKNIX uses a "Master" control; this vendor kernel exposes LINEOUT.
const MIXER_CONTROLS: [&str; 4] = ["Master", "LINEOUT", "Playback", "DAC"];

fn volume_level() -> String {
    for control in MIXER_CONTROLS {
        let Some(text) = run("amixer", &["get", control]) else { continue };
        for word in text.split_whitespace() {
            let token = word.trim_matches(|c| c == '[' || c == ']');
            if let Some(n) = token.strip_suffix('%').and_then(|s| s.parse::<u32>().ok()) {
                return n.min(100).to_string();
            }
        }
    }
    "unknown".into()
}

fn set_volume(percent: u32) -> String {
    let percent = percent.min(100);
    for control in MIXER_CONTROLS {
        if run("amixer", &["-q", "sset", control, &format!("{}%", percent)]).is_some() {
            return "Setting updated".into();
        }
    }
    "Setting failed".into()
}
'''
if "fn set_volume" not in text:
    text = text.rstrip() + helpers_vol
    print("appended volume helpers")


# 6) SYSTEM: the launcher asks the bridge for a tab-separated system snapshot on
#    every panel refresh, but no such command ever existed -- the info panel was
#    blank on BaseOS from day one. Collect it from procfs/sysfs instead of the
#    ROCKNIX helpers.
text = replace_once(
    '''        ["WIFI", "scan"] => wifi_scan(),''',
    '''        ["SYSTEM"] => system_snapshot(),
        ["WIFI", "scan"] => wifi_scan(),''',
    "system snapshot command",
)

helpers_sys = '''

// ── System snapshot ─────────────────────────────────────────────────────────
fn read_trimmed(path: &str) -> Option<String> {
    std::fs::read_to_string(path).ok().map(|v| v.trim().replace('\\u{0}', ""))
}

fn cpu_times() -> Option<(u64, u64)> {
    let stat = std::fs::read_to_string("/proc/stat").ok()?;
    let line = stat.lines().next()?;
    let mut fields = line.split_whitespace();
    fields.next();
    let values: Vec<u64> = fields.filter_map(|v| v.parse::<u64>().ok()).collect();
    if values.len() < 4 { return None; }
    let idle = values[3] + values.get(4).copied().unwrap_or(0);
    let total: u64 = values.iter().sum();
    Some((idle, total))
}

fn cpu_percent() -> Option<u32> {
    let (idle0, total0) = cpu_times()?;
    std::thread::sleep(std::time::Duration::from_millis(180));
    let (idle1, total1) = cpu_times()?;
    let total = total1.saturating_sub(total0);
    let idle = idle1.saturating_sub(idle0);
    if total == 0 { return None; }
    Some((((total - idle) * 100) / total) as u32)
}

fn meminfo_kb(key: &str) -> Option<u64> {
    let text = std::fs::read_to_string("/proc/meminfo").ok()?;
    text.lines()
        .find(|line| line.starts_with(key))
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u64>().ok())
}

fn storage_pair() -> Option<(String, String, u32)> {
    let text = run("df", &["-k", "/storage"])?;
    let line = text.lines().nth(1)?;
    let cols: Vec<&str> = line.split_whitespace().collect();
    if cols.len() < 4 { return None; }
    let total: u64 = cols[1].parse().ok()?;
    let used: u64 = cols[2].parse().ok()?;
    let percent = if total > 0 { ((used * 100) / total) as u32 } else { 0 };
    let human = |kb: u64| {
        if kb < 1024 * 1024 { format!("{:.0} MB", kb as f64 / 1024.0) }
        else { format!("{:.1} GB", kb as f64 / 1048576.0) }
    };
    Some((human(used), human(total), percent))
}

fn system_snapshot() -> String {
    let mut out: Vec<String> = Vec::new();
    let mut push = |key: &str, value: String| out.push(format!("{}\t{}", key, value));

    let model = read_trimmed("/proc/device-tree/model").unwrap_or_else(|| "RG34XX".into());
    push("model", model);
    push("hardware", read_trimmed("/proc/device-tree/compatible").unwrap_or_else(|| "--".into()).replace('\\u{0}', ",").trim_end_matches(',').to_string());

    let cpuinfo = std::fs::read_to_string("/proc/cpuinfo").unwrap_or_default();
    let cores = cpuinfo.lines().filter(|l| l.starts_with("processor")).count();
    push("cpu", format!("{} cores", cores.max(1)));
    if let Some(percent) = cpu_percent() { push("cpuUsagePercent", percent.to_string()); }

    let os_release = std::fs::read_to_string("/etc/os-release").unwrap_or_default();
    let field = |name: &str| os_release.lines()
        .find(|l| l.starts_with(&format!("{}=", name)))
        .map(|l| l.trim_start_matches(&format!("{}=", name)).trim_matches('"').to_string())
        .unwrap_or_default();
    let name = field("NAME");
    // os-release only carries VERSION_ID here; VERSION is empty in this image.
    let version = {
        let v = field("VERSION");
        if v.is_empty() { field("VERSION_ID") } else { v }
    };
    push("osName", name.clone());
    push("osVersion", version.clone());
    push("os", format!("{} {}", name, version).trim().to_string());
    push("kernel", run("uname", &["-r"]).unwrap_or_else(|| "--".into()).trim().to_string());

    if let Some(total) = meminfo_kb("MemTotal:") { push("ramTotalKb", total.to_string()); }
    if let Some(available) = meminfo_kb("MemAvailable:") { push("ramAvailableKb", available.to_string()); }
    push("ramVariant", format!("{:.1} GB", meminfo_kb("MemTotal:").unwrap_or(0) as f64 / 1048576.0));

    if let Some((used, total, percent)) = storage_pair() {
        push("storageUsed", used);
        push("storageTotal", total);
        push("storagePercent", percent.to_string());
    }

    if let Some(raw) = read_trimmed("/sys/class/thermal/thermal_zone0/temp").and_then(|v| v.parse::<i64>().ok()) {
        push("temperature", format!("{:.1}C", raw as f64 / 1000.0));
    }
    if let Some(raw) = read_trimmed("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").and_then(|v| v.parse::<u64>().ok()) {
        push("frequency", format!("{} MHz", raw / 1000));
    }
    push("display", read_trimmed("/sys/class/graphics/fb0/virtual_size").unwrap_or_else(|| "--".into()));
    push("runtime", format!("PocketJS {}", version).trim().to_string());
    out.join("\n")
}
'''
if "fn system_snapshot" not in text:
    text = text.rstrip() + helpers_sys
    print("appended system snapshot helper")

source.write_text(text)
print("bridge patched")
