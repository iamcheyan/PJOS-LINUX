#!/usr/bin/env python3
"""Restore the Wi-Fi, Bluetooth and device STATUS bridge protocol."""
from pathlib import Path
import sys

HELPERS = r'''
fn baseos_network_status(key: &str) -> String {
    let service = match key { "ssh" => "ssh.enabled", "adb" => "adbusb.enabled", _ => return "unknown".into() };
    run("rocknix-services", &["status", service])
        .and_then(|text| text.trim().split('=').nth(1).map(str::to_owned))
        .unwrap_or_else(|| "unknown".into())
}

fn baseos_ip_status() -> String {
    if let Some(text) = run("ip", &["-o", "-4", "addr", "show"]) {
        for line in text.lines() {
            let fields: Vec<&str> = line.split_whitespace().collect();
            if fields.len() < 4 || fields.get(2) != Some(&"inet") || line.contains("scope host") { continue; }
            let iface = fields[1].trim_end_matches(':').split('@').next().unwrap_or("");
            if iface.is_empty() || iface == "lo" { continue; }
            let address = fields[3].split('/').next().unwrap_or("");
            if !address.is_empty() { return format!("{}|{}", iface, address); }
        }
    }
    "--".into()
}

fn baseos_usb_status() -> String {
    if std::path::Path::new("/run/usb-storage-device").is_file() { return "file_transfer".into(); }
    for link in ["/sys/kernel/config/usb_gadget/g1/configs/c.1/mass_storage.usb0",
                 "/sys/kernel/config/usb_gadget/g1/configs/c.1/mass_storage.0"] {
        if std::path::Path::new(link).exists() { return "file_transfer".into(); }
    }
    "none".into()
}

fn baseos_wifi_ensure() -> bool {
    let _ = run("rfkill", &["unblock", "wlan"]);
    let _ = run("ip", &["link", "set", "wlan0", "up"]);
    if run("wpa_cli", &["-i", "wlan0", "ping"]).is_some() { return true; }
    let _ = std::fs::create_dir_all("/run/wpa_supplicant");
    let _ = std::fs::create_dir_all("/storage/.config");
    let config = "/storage/.config/wpa_supplicant.conf";
    if !std::path::Path::new(config).exists() {
        let _ = std::fs::write(config, "ctrl_interface=/run/wpa_supplicant\nupdate_config=1\n");
    }
    let _ = run("wpa_supplicant", &["-B", "-i", "wlan0", "-c", config, "-D", "nl80211"]);
    for _ in 0..4 {
        std::thread::sleep(std::time::Duration::from_millis(250));
        if run("wpa_cli", &["-i", "wlan0", "ping"]).is_some() { return true; }
    }
    false
}

fn baseos_wifi_status() -> String {
    match run("wpa_cli", &["-i", "wlan0", "status"]) {
        Some(text) => {
            let get = |key: &str| text.lines().find_map(|line| line.strip_prefix(&format!("{}=", key))).unwrap_or("");
            format!("state={}\nssid={}\nip={}", get("wpa_state"), get("ssid"), get("ip_address"))
        }
        None => "state=INACTIVE".into(),
    }
}

fn baseos_wifi_saved() -> String {
    run("wpa_cli", &["-i", "wlan0", "list_networks"]).map(|text| text.lines().skip(1)
        .filter_map(|line| line.split('\t').nth(1).map(str::trim).filter(|s| !s.is_empty()).map(str::to_owned))
        .collect::<Vec<_>>().join("\n")).unwrap_or_default()
}

fn baseos_wifi_scan() -> String {
    if !baseos_wifi_ensure() { return "error:supplicant".into(); }
    let _ = run("wpa_cli", &["-i", "wlan0", "scan"]);
    let mut rows = Vec::new();
    for _ in 0..8 {
        std::thread::sleep(std::time::Duration::from_millis(400));
        if let Some(text) = run("wpa_cli", &["-i", "wlan0", "scan_results"]) {
            for line in text.lines().filter(|line| line.contains('\t')) {
                let cols: Vec<&str> = line.split('\t').collect();
                if cols.len() < 5 || cols[0].len() != 17 || cols[0].bytes().filter(|b| *b == b':').count() != 5 { continue; }
                let ssid = cols[4..].join(" ");
                if ssid.is_empty() || rows.iter().any(|row: &String| row.starts_with(&format!("{}\t", ssid))) { continue; }
                let security = if cols[3].contains("WPA") || cols[3].contains("RSN") { "wpa" }
                    else if cols[3].contains("WEP") { "wep" } else { "open" };
                rows.push(format!("{}\t{}\t{}", ssid, cols[2], security));
            }
            if !rows.is_empty() { break; }
        }
    }
    if rows.is_empty() { "empty".into() } else { rows.join("\n") }
}

fn baseos_wifi_connect(ssid: &str, psk: &str) -> String {
    if !baseos_wifi_ensure() { return "error:supplicant".into(); }
    let scan = baseos_wifi_scan();
    let row = match scan.lines().find(|line| line.split('\t').next() == Some(ssid)) {
        Some(row) => row, None => return "not-found".into(),
    };
    if row.split('\t').nth(2) != Some("open") && psk.is_empty() { return "need-psk".into(); }
    let id = match run("wpa_cli", &["-i", "wlan0", "add_network"]).map(|s| s.trim().to_owned()) {
        Some(id) if !id.is_empty() => id, _ => return "error:add-network".into(),
    };
    let ssid_hex = ssid.as_bytes().iter().map(|b| format!("{:02x}", b)).collect::<String>();
    let mut script = format!("set_network {} ssid {}\n", id, ssid_hex);
    if psk.is_empty() { script.push_str(&format!("set_network {} key_mgmt NONE\n", id)); }
    else {
        let escaped = psk.replace('\\', "\\\\").replace('"', "\\\"");
        script.push_str(&format!("set_network {} psk \"{}\"\n", id, escaped));
    }
    script.push_str(&format!("enable_network {}\nselect_network {}\nsave_config\n", id, id));
    use std::io::Write;
    let mut child = match std::process::Command::new("/usr/bin/timeout").args(["2", "wpa_cli", "-i", "wlan0"])
        .stdin(std::process::Stdio::piped()).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn() {
        Ok(child) => child, Err(_) => return "error:supplicant".into(),
    };
    if let Some(mut input) = child.stdin.take() { let _ = input.write_all(format!("{}quit\n", script).as_bytes()); }
    let _ = child.wait();
    for _ in 0..10 {
        std::thread::sleep(std::time::Duration::from_millis(500));
        if run("wpa_cli", &["-i", "wlan0", "status"]).is_some_and(|s| s.contains("wpa_state=COMPLETED")) {
            let _ = run("udhcpc", &["-i", "wlan0", "-b", "-q", "-n", "-t", "2", "-T", "2"]);
            return format!("connected:{}", ssid);
        }
    }
    "timeout".into()
}

fn baseos_wifi_forget(ssid: &str) -> String {
    let id = run("wpa_cli", &["-i", "wlan0", "list_networks"]).and_then(|text| text.lines().skip(1).find_map(|line| {
        let mut cols = line.split('\t'); let id = cols.next()?.trim();
        (cols.next().map(str::trim) == Some(ssid)).then(|| id.to_owned())
    }));
    match id {
        Some(id) => { let _ = run("wpa_cli", &["-i", "wlan0", "remove_network", &id]); let _ = run("wpa_cli", &["-i", "wlan0", "save_config"]); format!("ok:forgot:{}", ssid) }
        None => format!("error:not-saved:{}", ssid),
    }
}

fn baseos_wifi_ip() -> String {
    run("wpa_cli", &["-i", "wlan0", "status"]).and_then(|text| text.lines().find_map(|line| line.strip_prefix("ip_address=").filter(|ip| !ip.is_empty()).map(str::to_owned)))
        .map(|ip| format!("wlan0|{}", ip)).unwrap_or_else(|| "--".into())
}

fn baseos_bt_status() -> String {
    let Some(text) = run("bluetoothctl", &["show"]) else { return "powered=no\naddress=".into(); };
    let address = text.lines().find_map(|line| line.trim().strip_prefix("Controller ")).and_then(|s| s.split_whitespace().next()).unwrap_or("");
    let powered = text.lines().any(|line| line.trim() == "Powered: yes");
    format!("powered={}\naddress={}", if powered { "yes" } else { "no" }, address)
}

fn baseos_bt_ready() -> bool {
    // Do not unblock a user-disabled radio. Adapter setup is owned by SETTING bluetooth.
    if std::fs::read_to_string("/sys/class/rfkill/rfkill0/state").ok().is_some_and(|s| s.trim() == "0") { return false; }
    run("hciconfig", &["hci0", "up"]).is_some() && run("/usr/sbin/systemctl", &["start", "bluetooth"]).is_some()
}

fn baseos_bt_start_scan() {
    let _ = std::process::Command::new("bluetoothctl")
        .args(["--timeout", "12", "scan", "on"])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
}

fn baseos_bt_scan() -> String {
    if !baseos_bt_ready() { return "error:bluez".into(); }
    baseos_bt_start_scan();
    let Some(all) = run("bluetoothctl", &["devices"]) else { return "error:bluez".into(); };
    let paired = run("bluetoothctl", &["devices", "Paired"]).unwrap_or_default();
    let mut rows = Vec::new();
    for line in all.lines() {
        let Some(rest) = line.strip_prefix("Device ") else { continue };
        let Some((mac, name)) = rest.split_once(' ') else { continue };
        if mac.len() != 17 || mac.bytes().filter(|b| *b == b':').count() != 5 { continue; }
        let is_paired = paired.lines().any(|entry| entry.contains(mac));
        rows.push(format!("{}\t{}\t-127\t{}", mac, name.trim(), if is_paired { 1 } else { 0 }));
    }
    if rows.is_empty() { "empty".into() } else { rows.join("\n") }
}

fn baseos_bt_action(verb: &str, address: &str) -> String {
    if !baseos_bt_ready() { return "error:bluez".into(); }
    let result = match verb {
        "connect" => run("bluetoothctl", &["connect", address]).map(|s| if s.contains("successful") || s.contains("already connected") { format!("connected:{}", address) } else { format!("error:connect:{}", address) }),
        "forget" => run("bluetoothctl", &["remove", address]).map(|_| format!("ok:forgot:{}", address)),
        "disconnect" => run("bluetoothctl", &["disconnect", address]).map(|_| format!("ok:disconnected:{}", address)),
        _ => None,
    };
    result.unwrap_or_else(|| format!("error:{}:{}", verb, address))
}
'''

ARMS = r'''        ["STATUS", "usb"] => baseos_usb_status(),
        ["STATUS", key] if ["ssh", "adb"].contains(key) => baseos_network_status(key),
        ["LEVEL", "ip"] => baseos_ip_status(),
        ["STATE", "wifi"] => baseos_setting("wifi", None),
        ["STATE", "bluetooth"] => baseos_setting("bluetooth", None),
        ["WIFI", "status"] => baseos_wifi_status(),
        ["WIFI", "scan"] => baseos_wifi_scan(),
        ["WIFI", "connect", ssid] => baseos_wifi_connect(ssid, ""),
        ["WIFI", "connect", ssid, psk] => baseos_wifi_connect(ssid, psk),
        ["WIFI", "saved"] => baseos_wifi_saved(),
        ["WIFI", "forget", ssid] => baseos_wifi_forget(ssid),
        ["WIFI", "disconnect"] => { let _ = run("wpa_cli", &["-i", "wlan0", "disconnect"]); "ok:disconnected".into() },
        ["WIFI", "ip"] => baseos_wifi_ip(),
        ["WIFI", "off"] => { let _ = run("wpa_cli", &["-i", "wlan0", "disconnect"]); let _ = run("ip", &["link", "set", "wlan0", "down"]); "off".into() },
        ["BT", "status"] => baseos_bt_status(),
        ["BT", "scan"] => baseos_bt_scan(),
        ["BT", "connect", address] => baseos_bt_action("connect", address),
        ["BT", "forget", address] => baseos_bt_action("forget", address),
        ["BT", "disconnect", address] => baseos_bt_action("disconnect", address),
'''

def patch_text(text: str) -> str:
    marker = "// BaseOS network protocol (v1)."
    if marker in text:
        return text
    anchor = "    match fields.as_slice() {\n"
    if text.count(anchor) != 1:
        raise SystemExit(f"network bridge dispatcher anchor appears {text.count(anchor)} times")
    text = text.replace(anchor, anchor + ARMS, 1)
    # Put helpers after imports/run() and before other patch helpers.
    anchor = "const LANGUAGE_PATH: &str ="
    if text.count(anchor) != 1:
        raise SystemExit("network bridge helper insertion point missing or ambiguous")
    text = text.replace(anchor, HELPERS + "\n// BaseOS network protocol (v1).\n" + anchor, 1)
    return text

def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    old = path.read_text()
    new = patch_text(old)
    if new != old:
        path.write_text(new)
        print("network bridge: restored WIFI, BT and STATUS protocols")
    else:
        print("network bridge: already applied")

if __name__ == "__main__":
    main()
