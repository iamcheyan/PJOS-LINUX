import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'overlay/usr/share/pocketshell/System/compat/bin/baseos-settings'

class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
    def put(self, name, value):
        p = self.root / name.lstrip('/')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)
    def run_setting(self, key, *args):
        return subprocess.run(['sh', str(SCRIPT), key, *args], env=dict(os.environ, BASEOS_SETTINGS_ROOT=str(self.root)), text=True, capture_output=True)
    def test_adb_explicit_on_rebuilds_even_when_already_on(self):
        service = self.root/'services'
        service.write_text('#!/bin/sh\nif [ "$1" = set ]; then echo "$3" >> "$CALLS"; fi\necho adbusb.enabled=1\n')
        service.chmod(0o755)
        calls = self.root/'calls'
        env = dict(os.environ, BASEOS_SETTINGS_SERVICES=str(service), BASEOS_ADB_SETTINGS_LOG=str(self.root/"adb.log"), CALLS=str(calls))
        for _ in range(2):
            result = subprocess.run(['sh', str(SCRIPT), 'adb', 'on'], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), 'on')
        self.assertEqual(calls.read_text().splitlines(), ['on', 'on'])
    def test_wifi_off_disables_interface_instead_of_only_disconnecting(self):
        (self.root/'sys/class/net/wlan0').mkdir(parents=True)
        bindir=self.root/'bin'; bindir.mkdir()
        state=self.root/'state'; state.write_text('COMPLETED')
        ip=bindir/'ip'
        ip.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\nif [ "$4" = down ]; then echo INTERFACE_DISABLED > "$STATE"; else echo COMPLETED > "$STATE"; fi\n')
        ip.chmod(0o755)
        wpa=bindir/'wpa_cli';wpa.write_text('#!/bin/sh\nprintf "wpa_state=%s\\n" "$(cat "$STATE")"\n');wpa.chmod(0o755)
        calls=self.root/'calls'
        env=dict(os.environ, BASEOS_SETTINGS_ROOT=str(self.root), PATH=str(bindir)+':'+os.environ['PATH'], CALLS=str(calls), STATE=str(state))
        result=subprocess.run(['sh',str(SCRIPT),'wifi','off'],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'off')
        self.assertEqual(calls.read_text().strip(),'link set wlan0 down')
    def test_hostname(self):
        self.put('/proc/sys/kernel/hostname', 'rg34xx\n')
        result = self.run_setting('hostname')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'rg34xx')
    def test_bluetooth_blocked_and_enabled(self):
        self.put('/sys/class/rfkill/rfkill0/type', 'bluetooth\n')
        (self.root/'sys/class/bluetooth/hci0').mkdir(parents=True)
        for state, expected in [('0', 'off'), ('1', 'on')]:
            self.put('/sys/class/rfkill/rfkill0/state', state+'\n')
            self.assertEqual(self.run_setting('bluetooth').stdout.strip(), expected)
    def test_bluetooth_failed_attach_is_not_on(self):
        self.put('/sys/class/rfkill/rfkill0/type', 'bluetooth\n')
        self.put('/sys/class/rfkill/rfkill0/state', '1\n')
        self.assertEqual(self.run_setting('bluetooth').stdout.strip(), 'off')
    def test_headphone_fix(self):
        for state, expected in [('N', 'off'), ('Y', 'on')]:
            self.put('/sys/module/h700_speaker_amp/parameters/headphone_pop_fix', state+'\n')
            self.assertEqual(self.run_setting('headphoneFix').stdout.strip(), expected)
    def test_ntp_default_and_enabled(self):
        self.assertEqual(self.run_setting('ntp').stdout.strip(), 'off')
        self.put('/data/ntp-enabled', 'yes\n')
        self.assertEqual(self.run_setting('ntp').stdout.strip(), 'on')
    def test_invalid_toggle_rejected(self):
        result = self.run_setting('bluetooth', 'oops')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('error:', result.stdout)
    def test_headphone_write(self):
        self.put('/sys/module/h700_speaker_amp/parameters/headphone_pop_fix', 'N\n')
        result = self.run_setting('headphoneFix', 'on')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'error:reboot-required')
        self.assertEqual((self.root/'sys/module/h700_speaker_amp/parameters/headphone_pop_fix').read_text().strip(), 'N')
        self.assertIn('headphone_pop_fix=true', (self.root/'mnt/sdcard/baseos.conf').read_text())
    def test_ui_settings_persistence(self):
        self.assertEqual(self.run_setting('showClock').stdout.strip(), 'off')
        self.assertEqual(self.run_setting('animations').stdout.strip(), 'off')
        self.assertEqual(self.run_setting('fontSize').stdout.strip(), 'normal')
        self.assertEqual(self.run_setting('themeColor').stdout.strip(), 'purple')
        self.assertEqual(self.run_setting('showClock', 'on').stdout.strip(), 'on')
        self.assertEqual(self.run_setting('animations', 'on').stdout.strip(), 'on')
        self.assertEqual(self.run_setting('fontSize', 'huge').stdout.strip(), 'huge')
        self.assertEqual(self.run_setting('themeColor', 'pink').stdout.strip(), 'pink')
        # Check read back
        self.assertEqual(self.run_setting('showClock').stdout.strip(), 'on')
        self.assertEqual(self.run_setting('animations').stdout.strip(), 'on')
        self.assertEqual(self.run_setting('fontSize').stdout.strip(), 'huge')
        self.assertEqual(self.run_setting('themeColor').stdout.strip(), 'pink')
if __name__ == '__main__': unittest.main()
