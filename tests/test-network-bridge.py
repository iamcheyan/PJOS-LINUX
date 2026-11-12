#!/usr/bin/env python3
"""Compile and exercise restored launcher network bridge protocols."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("network_patch", ROOT / "src/apply-pocketjs-network-bridge.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)

FIXTURE = r'''use std::process::{Command, Stdio};
fn run(program: &str, args: &[&str]) -> Option<String> {
    let mut argv: Vec<&str> = vec!["2", program]; argv.extend_from_slice(args);
    let out = Command::new("/usr/bin/timeout").args(&argv).stdin(Stdio::null()).stderr(Stdio::null()).output().ok()?;
    out.status.success().then(|| String::from_utf8_lossy(&out.stdout).into_owned())
}
fn baseos_setting(key: &str, _value: Option<&str>) -> String { format!("setting:{}", key) }
const LANGUAGE_PATH: &str = "/unused";
pub fn command(value: &str) -> String {
    let fields: Vec<&str> = value.split('\t').collect();
    match fields.as_slice() {
        _ => "unknown".into(),
    }
}
fn main() { print!("{}", command(&std::env::args().nth(1).unwrap())); }
'''

class NetworkBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        source = cls.root / "bridge.rs"
        source.write_text(PATCH.patch_text(FIXTURE))
        # Redirect only read-only device paths used by USB/Bluetooth status.
        text = source.read_text().replace('"/run/usb-storage-device"', f'"{cls.root}/run/usb-storage-device"')
        text = text.replace('"/sys/kernel/config/usb_gadget/g1/configs/c.1/mass_storage.usb0"', f'"{cls.root}/configfs/mass_storage.usb0"')
        text = text.replace('"/sys/kernel/config/usb_gadget/g1/configs/c.1/mass_storage.0"', f'"{cls.root}/configfs/mass_storage.0"')
        text = text.replace('"/sys/class/rfkill/rfkill0/state"', f'"{cls.root}/rfkill-state"')
        text = text.replace('"/usr/sbin/systemctl"', f'"{cls.root}/bin/systemctl"')
        source.write_text(text)
        cls.binary = cls.root / "bridge"
        result = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.bindir = cls.root / "bin"
        cls.bindir.mkdir()
        cls.env = dict(os.environ, PATH=f"{cls.bindir}:{os.environ['PATH']}")

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def fake(self, name, body):
        path = self.bindir / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def call(self, value):
        return subprocess.check_output([str(self.binary), value], text=True, env=self.env)

    def test_usb_and_service_status(self):
        run = self.root / "run"
        run.mkdir(exist_ok=True)
        self.assertEqual(self.call("STATUS\tusb"), "none")
        (run / "usb-storage-device").write_text("/dev/mmcblk1\n")
        self.assertEqual(self.call("STATUS\tusb"), "file_transfer")
        self.fake("rocknix-services", 'exit 1')
        self.assertEqual(self.call("STATUS\tssh"), "unknown")  # missing status response is not a fabricated enabled state
        self.fake("rocknix-services", 'echo "$2=1"')
        self.assertEqual(self.call("STATUS\tssh"), "1")
        self.assertEqual(self.call("STATUS\tadb"), "1")

    def test_ip_uses_interface_column_not_scope(self):
        self.fake("ip", 'printf "2: wlan0@if3: inet 192.0.2.4/24 brd 192.0.2.255 scope global wlan0\\n"')
        self.assertEqual(self.call("LEVEL\tip"), "wlan0|192.0.2.4")

    def test_wifi_scan_skips_header_and_connect_is_fixture_only(self):
        self.fake("rfkill", "exit 0")
        self.fake("ip", "exit 0")
        self.fake("wpa_supplicant", "exit 0")
        self.fake("udhcpc", "exit 0")
        self.fake("wpa_cli", r'''if [ "$1" = -i ]; then shift 2; fi
case "$1" in
  ping) echo PONG ;;
  scan|disconnect|save_config|enable_network|select_network|remove_network) echo OK ;;
  scan_results) printf 'bssid / frequency / signal level / flags / ssid\nAA:BB:CC:DD:EE:FF\t2412\t-45\t[WPA2-PSK-CCMP][ESS]\tHomeNet\n' ;;
  add_network) echo 7 ;;
  status) printf 'wpa_state=COMPLETED\nssid=HomeNet\nip_address=192.0.2.8\n' ;;
  list_networks) printf 'network id / ssid / bssid / flags\n7\tHomeNet\tany\t\n' ;;
esac
while IFS= read -r line; do
  case "$line" in *secret*) echo leaked >&2 ;; esac
done''')
        scan = self.call("WIFI\tscan")
        self.assertEqual(scan.strip(), "HomeNet\t-45\twpa")
        self.assertEqual(self.call("WIFI\tstatus"), "state=COMPLETED\nssid=HomeNet\nip=192.0.2.8")
        # No command reaches the host radio: every command above resolves to these fixtures.
        self.assertEqual(self.call("WIFI\tconnect\tHomeNet\tsecret"), "connected:HomeNet")

    def test_bluetooth_ui_protocol(self):
        (self.root / "rfkill-state").write_text("1\n")
        self.fake("hciconfig", "exit 0")
        self.fake("systemctl", "exit 0")
        self.fake("bluetoothctl", r'''case "$1" in
show) printf 'Controller 00:11:22:33:44:55 (public)\n\tPowered: yes\n' ;;
devices) if [ "$2" = Paired ]; then echo 'Device AA:BB:CC:DD:EE:FF Headphones'; else echo 'Device AA:BB:CC:DD:EE:FF Headphones'; fi ;;
connect) echo 'Connection successful' ;;
*) echo ok ;;
esac''')
        self.assertEqual(self.call("BT\tstatus"), "powered=yes\naddress=00:11:22:33:44:55")
        self.assertEqual(self.call("BT\tscan").strip(), "AA:BB:CC:DD:EE:FF\tHeadphones\t-127\t1")
        self.assertEqual(self.call("BT\tconnect\tAA:BB:CC:DD:EE:FF"), "connected:AA:BB:CC:DD:EE:FF")

if __name__ == "__main__": unittest.main()
