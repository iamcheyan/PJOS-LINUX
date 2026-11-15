import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "src/apply-pocketjs-settings.py"
OLD_KEYS = '["wifi", "bluetooth", "btAudio", "headphoneFix", "hostname", "ntp", "adb", "ssh", "mdns", "showClock", "animations", "fontSize", "themeColor"]'


class SettingsRuntimePatchTest(unittest.TestCase):
    def test_upgrades_an_existing_setting_bridge_with_every_persisted_ui_key(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Path(directory) / "pocketshell_launcher.rs"
            bridge.write_text(
                "fn baseos_setting() {}\n"
                f'        ["SETTING", key] if {OLD_KEYS}.contains(key) => baseos_setting(key, None),\n'
                f'        ["SETTING", key, value] if {OLD_KEYS}.contains(key) => baseos_setting(key, Some(value)),\n'
            )
            subprocess.run(["python3", str(PATCH), str(bridge)], check=True, capture_output=True)
            text = bridge.read_text()
            self.assertEqual(text.count('"zeldaLastRom"'), 2)


if __name__ == "__main__":
    unittest.main()
