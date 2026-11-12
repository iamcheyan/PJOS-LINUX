"""Compile the generated helper and round-trip NAS password JSON bodies."""
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / 'src/apply-pocketjs-kanade.py'))

class KanadeBridge(unittest.TestCase):
    def test_generated_rust_and_password_json(self):
        helper = MODULE['HELPER']
        branch = helper.split('Some(password) => {', 1)[1].split('\n            }', 1)[0]
        source = 'use std::process::{Command, Stdio};\n' + helper
        source += '\nfn password_body(password: String) -> Option<(&\'static str, String, Option<String>)> {' + branch + '\n}\n'
        source += '''fn main() {
            let value = std::env::args().nth(1).unwrap();
            let decoded = kanade_unhex(&value).unwrap();
            println!("{}", password_body(decoded).unwrap().2.unwrap());
        }'''
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path / 'test.rs').write_text(source)
            rustc = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc')
            result = subprocess.run([rustc, '--edition=2021', str(path / 'test.rs'), '-o', str(path / 'test')], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for text in ('simple', 'a"b\\c', '', '日本語🔑', 'line\nreturn\rtab\t\x00\x1f'):
                with self.subTest(text=text):
                    output = subprocess.check_output([str(path / 'test'), text.encode().hex()], text=True)
                    self.assertEqual(json.loads(output), {'password': text})

if __name__ == '__main__': unittest.main()
