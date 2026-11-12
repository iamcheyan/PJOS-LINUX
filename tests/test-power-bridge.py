#!/usr/bin/env python3
"""Exercise generated Rust dispatcher against real temporary INI files."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('power_patch', ROOT / 'src/apply-pocketjs-power-bridge.py')
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)
FIXTURE = '''pub fn command(value: &str) -> String {
    let fields: Vec<&str> = value.split('\\t').collect();
    match fields.as_slice() {
        ["STATE", "timeout"] => { "30m".into() }
        ["SLEEP", timeout] if ["never", "10s", "30s", "1m", "5m", "15m", "30m", "1h"].contains(timeout) => { "old".into() }
        _ => "Unknown launcher action".into(),
    }
}
fn main() { print!("{}", command(&std::env::args().nth(1).unwrap())); }
'''

class PowerBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        source = cls.base / 'bridge.rs'
        source.write_text(FIXTURE)
        PATCH.main(str(source))
        once = source.read_text()
        PATCH.main(str(source))
        assert once == source.read_text(), 'patch must be idempotent'
        cls.runtime = cls.base / 'runtime.conf'
        cls.override = cls.base / 'screen-idle.conf'
        text = source.read_text().replace('/storage/.config/pocketjs/runtime.conf', str(cls.runtime)).replace('/storage/.config/baseos/screen-idle.conf', str(cls.override))
        source.write_text(text)
        cls.binary = cls.base / 'bridge'
        subprocess.run(['rustc', '--edition=2021', str(source), '-o', str(cls.binary)], check=True, capture_output=True)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def setUp(self):
        self.runtime.write_text('[sleep]\ntimeout = 10s\n[power]\ntimeout = never\n')
        self.override.write_text('timeout = 1m\nauto_stop_timeout = 5m\n')
    def call(self, command):
        return subprocess.check_output([str(self.binary), command], text=True)
    def test_effective_values_and_unified_aliases(self):
        self.assertEqual(self.call('SETTING\tautoPoweroff'), '5m')
        self.assertEqual(self.call('STATE\tpower_timeout'), '5m')
        self.assertEqual(self.call('SETTING\ttimeout'), '1m')
        self.assertEqual(self.call('STATE\ttimeout'), '1m')
    def test_writes_update_effective_override(self):
        self.call('SETTING\tautoPoweroff\tnever')
        self.assertEqual(self.call('STATE\tpower_timeout'), 'never')
        self.assertIn('auto_stop_timeout = never', self.override.read_text())
        self.call('SLEEP\t30s')
        self.assertEqual(self.call('STATE\ttimeout'), '30s')
        self.assertIn('timeout = 30s', self.runtime.read_text())
    def test_new_key_goes_inside_existing_section(self):
        self.override.unlink()
        self.runtime.write_text('[power]\n# empty section\n[sleep]\ntimeout = 10s\n')
        self.call('POWER\t5m')
        self.assertEqual(self.call('STATE\tpower_timeout'), '5m')
        self.assertEqual(self.call('STATE\ttimeout'), '10s')
    def test_invalid_request_does_not_change_files(self):
        before = self.runtime.read_text(), self.override.read_text()
        self.call('SETTING\tautoPoweroff\tpotato')
        self.assertEqual(before, (self.runtime.read_text(), self.override.read_text()))

if __name__ == '__main__': unittest.main()
