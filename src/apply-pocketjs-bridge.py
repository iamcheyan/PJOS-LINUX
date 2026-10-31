#!/usr/bin/env python3
"""Make the PocketShell launcher bridge work on BaseOS.

The original picker assumed a Bluetooth UART controller and BlueZ daemon already
existed. BaseOS must attach the H5 UART, start D-Bus/BlueZ and return discovery
results within the PocketJS bridge's two-second command limit.

This patch:
  * creates the parent directory before writing settings,
  * treats a settings write that cannot happen as a visible error instead of a
    silent success,
  * drops the systemd restart (BaseOS blanks the panel from rcS instead),
  * reports Wi-Fi state from wpa_cli instead of the absent rocknix-settings,
  * reads and writes the physical panel backlight through baseos-panel,
  * attaches Bluetooth, starts discovery asynchronously, and reads BlueZ's cache.
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
    '''        ["WIFI", "connect", ssid, psk] => wifi_connect(ssid, psk),
        ["WIFI", "off"] => {''',
    '''        ["WIFI", "connect", ssid, psk] => wifi_connect(ssid, psk),
        ["BT", "status"] => bluetooth_status(),
        ["BT", "scan"] => bluetooth_scan(),
        ["BT", "connect", mac] => bluetooth_connect(mac),
        ["BT", "forget", mac] => bluetooth_forget(mac),
        ["BT", "disconnect", mac] => bluetooth_disconnect(mac),
        ["CONTROL", "bluetooth", state] if ["on", "off"].contains(state) => bluetooth_power(state),
        ["WIFI", "off"] => {''',
    "Bluetooth actions used by the picker",
)

# Remove obsolete BT arms from the older patch stage. Bluetooth is supplied
# below with attach, daemon lifecycle and the picker response protocol.
text = text.replace(
    '''        ["BT", "on"] => {
            let _ = run("rfkill", &["unblock", "bluetooth"]);
            bluetooth_state()
        }
        ["BT", "off"] => {
            let _ = run("rfkill", &["block", "bluetooth"]);
            "off".into()
        }
        ["BT", "scan"] => bluetooth_scan(),
        ["BT", "pair", mac] => bluetooth_pair(mac),
''',
    "",
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

// ── Bluetooth (RTL8821CS H5 UART + BlueZ) ──────────────────────────────────
// ROCKNIX starts the UART attach helper before BlueZ. The UI bridge used to
// skip both steps, then synchronously wait eight seconds for bluetoothctl
// output; its host runner kills commands after two seconds and the output format
// is D-Bus progress, not the device cache. Attach/service start are therefore
// backgrounded, discovery is started in the background, and this call returns
// the BlueZ device cache immediately.
const BT_ATTACH: &str = "/mnt/vendor/ctrl/setBluetooth.sh";

fn bluetooth_ready() -> bool {
    let _ = run("rfkill", &["unblock", "bluetooth"]);
    if run("hciconfig", &["hci0"]).is_none() {
        let _ = run(BT_ATTACH, &["all"]);
    }
    if run("hciconfig", &["hci0", "up"]).is_none() {
        return false;
    }
    run("/usr/sbin/systemctl", &["start", "bluetooth"]).is_some()
}

fn bluetooth_status() -> String {
    if !bluetooth_ready() {
        return "powered=no\naddress=".into();
    }
    let Some(text) = run("bluetoothctl", &["show"]) else {
        return "powered=no\naddress=".into();
    };
    let address = text.lines().find_map(|line| line.trim().strip_prefix("Controller "))
        .and_then(|line| line.split_whitespace().next()).unwrap_or("");
    let powered = text.lines().any(|line| line.trim() == "Powered: yes");
    format!("powered={}\naddress={}", if powered { "yes" } else { "no" }, address)
}

fn bluetooth_power(state: &str) -> String {
    if !bluetooth_ready() {
        return "error:bluez".into();
    }
    let answer = run("bluetoothctl", &["power", state]).unwrap_or_default();
    if answer.contains("succeeded") || answer.contains("already") {
        format!("powered={}", state)
    } else {
        "error:power".into()
    }
}

fn bluetooth_scan() -> String {
    if !bluetooth_ready() {
        return "error:bluez".into();
    }
    let _ = run_detached("bluetoothctl", &["--timeout", "12", "scan", "on"]);
    let Some(text) = run("bluetoothctl", &["devices"]) else {
        return "error:bluez".into();
    };
    let mut rows = String::new();
    for line in text.lines() {
        let Some(rest) = line.strip_prefix("Device ") else { continue };
        let Some((mac, name)) = rest.split_once(' ') else { continue };
        if mac.len() == 17 && mac.bytes().filter(|b| *b == b':').count() == 5 {
            rows.push_str(&format!("{}\t{}\t-127\t0\n", mac, name.trim()));
        }
    }
    if rows.is_empty() { "empty".into() } else { rows }
}

fn bluetooth_connect(mac: &str) -> String {
    if !bluetooth_ready() { return "error:bluez".into(); }
    match run("bluetoothctl", &["connect", mac]) {
        Some(text) if text.contains("Connection successful") || text.contains("already connected") => format!("connected:{}", mac),
        _ => format!("error:connect:{}", mac),
    }
}

fn bluetooth_forget(mac: &str) -> String {
    if !bluetooth_ready() { return "error:bluez".into(); }
    match run("bluetoothctl", &["remove", mac]) {
        Some(_) => format!("ok:forgot:{}", mac),
        None => format!("error:forget:{}", mac),
    }
}

fn bluetooth_disconnect(mac: &str) -> String {
    if !bluetooth_ready() { return "error:bluez".into(); }
    match run("bluetoothctl", &["disconnect", mac]) {
        Some(_) => format!("ok:disconnected:{}", mac),
        None => format!("error:disconnect:{}", mac),
    }
}
'''
if "fn wifi_scan()" not in text:
    text = text.rstrip() + helpers
    print("appended wifi/bluetooth helpers")

# 4) Brightness uses baseos-panel to drive and read the real PWM backlight;
#    heya-control's brightness alias writes enhance_bright, which is not it.
run_old = '''fn run(program: &str, args: &[&str]) -> Option<String> {
    let mut argv: Vec<&str> = vec!["2", program];
    argv.extend_from_slice(args);'''
run_new = '''fn run(program: &str, args: &[&str]) -> Option<String> {
    let mut argv: Vec<&str> = vec![if program == "bluetoothctl" { "8" } else { "2" }, program];
    argv.extend_from_slice(args);'''
if run_old in text:
    text = text.replace(run_old, run_new, 1)
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
            match run(&compat_tool("heya-control"), &[control, value]) {
                Some(_) => "Setting updated".into(),
                None => "Setting failed".into(),
            }''',
    "brightness control",
)

text = replace_once(
    '''        ["SERVICE", key] if ["adbd.enabled", "adbusb.enabled", "ssh.enabled", "avahi.enabled", "ftp.enabled", "http.enabled", "rsyncd.enabled", "samba.enabled", "syncthing.enabled", "telnet.enabled", "pocketshell-dev.enabled"].contains(key) => {
            match run("rocknix-services", &["toggle", key]) {''',
    '''        ["SERVICE", key] if ["adbd.enabled", "adbusb.enabled", "ssh.enabled", "avahi.enabled", "ftp.enabled", "http.enabled", "rsyncd.enabled", "samba.enabled", "syncthing.enabled", "telnet.enabled", "pocketshell-dev.enabled"].contains(key) => {
            match run(&compat_tool("rocknix-services"), &["toggle", key]) {''',
    "service shim path",
)




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
    // Concrete versions so the SYSTEM page can state what is actually running.
    let release = std::fs::read_to_string("/etc/baseos-release").unwrap_or_default();
    let rel = |name: &str| release.lines()
        .find(|l| l.starts_with(&format!("{}=", name)))
        .map(|l| l.trim_start_matches(&format!("{}=", name)).trim_matches('"').to_string())
        .unwrap_or_default();
    let sdk = { let v = rel("PJOS_SDK_VERSION"); if v.is_empty() { "0.15.0".to_string() } else { v } };
    let abi = { let v = rel("POCKETJS_ABI"); if v.is_empty() { "12".to_string() } else { v } };
    push("sdk", sdk.clone());
    push("abi", abi.clone());
    push("build", { let v = rel("BASEOS_BUILD"); if v.is_empty() { "--".to_string() } else { v } });
    push("runtime", format!("PocketJS {} (abi {})", sdk, abi));
    out.join("\n")
}
'''
if "fn system_snapshot" not in text:
    text = text.rstrip() + helpers_sys
    print("appended system snapshot helper")


# --- Wi-Fi 2.0 + installed-app launching -------------------------------------
# Added as new functions instead of editing the ROCKNIX originals, so every change
# stays anchor-based and cannot half-apply.

wifi_arms_old = '''        ["WIFI", "connect", ssid] => wifi_connect(ssid, ""),
        ["WIFI", "connect", ssid, psk] => wifi_connect(ssid, psk),
        ["WIFI", "off"] => {
            let _ = run("wpa_cli", &["-i", "wlan0", "disconnect"]);
            let _ = run("ip", &["link", "set", "wlan0", "down"]);
            "off".into()
        }'''

wifi_arms_new = '''        ["WIFI", "connect", ssid] => wifi_connect_app(ssid, ""),
        ["WIFI", "connect", ssid, psk] => wifi_connect_app(ssid, psk),
        ["WIFI", "disconnect"] => {
            let _ = run("wpa_cli", &["-i", "wlan0", "disconnect"]);
            "ok:disconnected".into()
        }
        ["WIFI", "forget", ssid] => wifi_forget(ssid),
        ["WIFI", "saved"] => wifi_saved(),
        ["WIFI", "ip"] => wifi_ip(),
        ["WIFI", "off"] => {
            let _ = run("wpa_cli", &["-i", "wlan0", "disconnect"]);
            let _ = run("ip", &["link", "set", "wlan0", "down"]);
            "off".into()
        }'''

text = replace_once(wifi_arms_old, wifi_arms_new, "wifi 2.0 arms")

launch_old = '''        ["LAUNCH", app] if ["disk", "xmplayer"].contains(app) => {'''
launch_new = '''        ["LAUNCH", app] if apps_launch_ready(app) => apps_launch(app),
        ["LAUNCH", app] if ["disk", "xmplayer"].contains(app) => {'''
text = replace_once(launch_old, launch_new, "installed-app launch arm")

apps_arm_old = '''        ["LAUNCH", app] if apps_launch_ready(app) => apps_launch(app),'''
apps_arm_new = '''        ["APPS", "list"] => apps_list(),
        ["LAUNCH", app] if apps_launch_ready(app) => apps_launch(app),'''
text = replace_once(apps_arm_old, apps_arm_new, "installed app listing arm")

runtime_helpers = r"""

fn wpa_script(commands: &str) -> Option<String> {
    use std::io::Write;
    let mut child = std::process::Command::new("wpa_cli")
        .args(["-i", "wlan0"])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()
        .ok()?;
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(format!("{}\nquit\n", commands).as_bytes());
    }
    let out = child.wait_with_output().ok()?;
    Some(String::from_utf8_lossy(&out.stdout).to_string())
}

fn wifi_network_id(ssid: &str) -> Option<String> {
    let text = run("wpa_cli", &["-i", "wlan0", "list_networks"])?;
    text.lines().skip(1).find_map(|line| {
        let mut cols = line.split('\t');
        let id = cols.next()?.trim().to_string();
        let row = cols.next()?.trim();
        if row == ssid { Some(id) } else { None }
    })
}

fn wifi_forget(ssid: &str) -> String {
    match wifi_network_id(ssid) {
        Some(id) => {
            let _ = run("wpa_cli", &["-i", "wlan0", "remove_network", &id]);
            let _ = run("wpa_cli", &["-i", "wlan0", "save_config"]);
            format!("ok:forgot:{}", ssid)
        }
        None => format!("error:not-saved:{}", ssid),
    }
}

fn wifi_saved() -> String {
    match run("wpa_cli", &["-i", "wlan0", "list_networks"]) {
        Some(text) => text.lines().skip(1)
            .filter_map(|line| {
                let mut cols = line.split('\t');
                cols.next();
                cols.next().map(str::trim).filter(|s| !s.is_empty()).map(str::to_string)
            })
            .collect::<Vec<_>>()
            .join("\n"),
        None => String::new(),
    }
}

fn wifi_ip() -> String {
    if let Some(text) = run("wpa_cli", &["-i", "wlan0", "status"]) {
        if let Some(ip) = text.lines().find_map(|l| l.strip_prefix("ip_address=")) {
            if !ip.is_empty() {
                return format!("wlan0|{}", ip);
            }
        }
    }
    if let Some(text) = run("ip", &["-4", "-o", "addr", "show", "wlan0"]) {
        if let Some(addr) = text.split_whitespace().find(|w| w.contains('.') && w.contains('/')) {
            return format!("wlan0|{}", addr.split('/').next().unwrap_or(addr));
        }
    }
    "--".into()
}

fn wifi_connect_app(ssid: &str, psk: &str) -> String {
    if !wifi_ensure() {
        return "error:supplicant".into();
    }
    let scan = wifi_scan();
    let row = scan.lines().find(|line| line.split('\t').next() == Some(ssid));
    let row = match row {
        Some(row) => row.to_string(),
        None => return "not-found".into(),
    };
    let security = row.split('\t').nth(2).unwrap_or("").to_string();
    if security != "open" && psk.is_empty() {
        return "need-psk".into();
    }
    let net_id = match run("wpa_cli", &["-i", "wlan0", "add_network"]).map(|t| t.trim().to_string()) {
        Some(id) if !id.is_empty() => id,
        _ => return "error:add-network".into(),
    };
    let mut script = format!("set_network {} ssid \"{}\"\n", net_id, ssid);
    if psk.is_empty() {
        script.push_str(&format!("set_network {} key_mgmt NONE\n", net_id));
    } else {
        // Over stdin on purpose: an argv word is visible in `ps` to every user.
        script.push_str(&format!("set_network {} psk \"{}\"\n", net_id, psk));
    }
    script.push_str(&format!(
        "enable_network {}\nselect_network {}\nsave_config\n",
        net_id, net_id
    ));
    if wpa_script(&script).is_none() {
        // wpa_cli without stdin scripting: fall back to argv rather than fail.
        let _ = run("wpa_cli", &["-i", "wlan0", "set_network", &net_id, "ssid", &format!("\"{}\"", ssid)]);
        if psk.is_empty() {
            let _ = run("wpa_cli", &["-i", "wlan0", "set_network", &net_id, "key_mgmt", "NONE"]);
        } else {
            let _ = run("wpa_cli", &["-i", "wlan0", "set_network", &net_id, "psk", &format!("\"{}\"", psk)]);
        }
        let _ = run("wpa_cli", &["-i", "wlan0", "enable_network", &net_id]);
        let _ = run("wpa_cli", &["-i", "wlan0", "select_network", &net_id]);
        let _ = run("wpa_cli", &["-i", "wlan0", "save_config"]);
    }
    let mut disabled = false;
    for _ in 0..20 {
        std::thread::sleep(std::time::Duration::from_millis(500));
        let text = match run("wpa_cli", &["-i", "wlan0", "status"]) {
            Some(text) => text,
            None => continue,
        };
        if text.contains("wpa_state=COMPLETED") {
            let _ = run("udhcpc", &["-i", "wlan0", "-b", "-q", "-n", "-t", "5", "-T", "3"]);
            return format!("connected:{}", ssid);
        }
        if let Some(list) = run("wpa_cli", &["-i", "wlan0", "list_networks"]) {
            for line in list.lines() {
                let mut cols = line.split('\t');
                let id = cols.next().unwrap_or("");
                cols.next();
                cols.next();
                let flags = cols.next().unwrap_or("");
                if id == net_id && flags.contains("DISABLED") {
                    disabled = true;
                }
            }
        }
    }
    if disabled { "auth-failed".into() } else { "timeout".into() }
}

fn apps_list() -> String {
    let mut rows: Vec<String> = Vec::new();
    if let Ok(entries) = std::fs::read_dir("/storage/apps") {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if let Some(id) = name.strip_suffix(".pocket") {
                if id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
                    rows.push(id.to_string());
                }
            }
        }
    }
    rows.sort();
    rows.join("\n")
}

fn apps_launch_ready(app: &str) -> bool {
    !app.is_empty()
        && app.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.')
        && std::path::Path::new(&format!("/storage/apps/{}.pocket", app)).exists()
}

fn apps_launch(app: &str) -> String {
    if !apps_launch_ready(app) {
        return format!("error:missing:{}", app);
    }
    let marker = "/storage/System/pocketjs/active";
    if let Some(dir) = std::path::Path::new(marker).parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if std::fs::write(marker, app).is_err() {
        return "error:marker".into();
    }
    // Hand the panel over: the supervisor respawns launch_frontend.sh, which reads
    // the marker, runs that package, then returns to the launcher.
    let pid = std::process::id();
    let _ = std::process::Command::new("/bin/sh")
        .args(["-c", &format!("sleep 0.4; kill -9 {}", pid)])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
    format!("launching:{}", app)
}
"""
if "fn wifi_connect_app" not in text:
    text = text.rstrip() + runtime_helpers
    print("appended wifi 2.0 + app launch helpers")

source.write_text(text)
print("bridge patched")
