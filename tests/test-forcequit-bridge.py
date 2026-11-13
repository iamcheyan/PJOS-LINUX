#!/usr/bin/env python3
"""Exercise the actual additive patch and Rust one-shot event consumer."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('forcequit', ROOT / 'src/apply-pocketjs-forcequit.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


class ForceQuitBridgeTest(unittest.TestCase):
    def test_patch_is_additive_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bridge.rs'
            source.write_text('pub fn command(input: &str) {\n    match fields.as_slice() {\n        ["WIFI", "scan"] => existing_network(),\n    }\n}\n')
            patch.main(source)
            first = source.read_text()
            patch.main(source)
            self.assertEqual(first, source.read_text())
            self.assertIn('["WIFI", "scan"] => existing_network()', first)
            self.assertEqual(first.count('["FORCEQUIT"] => consume_force_quit()'), 1)

    def test_consumer_claims_once_and_discards_invalid_ids(self):
        rustc = shutil.which('rustc')
        if not rustc:
            self.skipTest('rustc unavailable')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            marker = directory / 'force-quit'
            helper = patch.HELPER.replace('/run/baseos-force-quit', str(marker))
            source = directory / 'test.rs'
            source.write_text(helper + '\nfn main() { println!("{}", consume_force_quit()); }\n')
            binary = directory / 'consumer'
            subprocess.run([rustc, str(source), '-o', str(binary)], check=True)
            for event, expected in [('kanade\n', 'kanade'), ('game\n', 'game'), ('../secret', ''), ('a' * 65, '')]:
                marker.write_text(event)
                result = subprocess.check_output([binary], text=True).strip()
                self.assertEqual(result, expected)
                self.assertFalse(marker.exists())
                self.assertEqual(subprocess.check_output([binary], text=True).strip(), '')
            self.assertFalse(list(directory.glob('force-quit.consume.*')))


if __name__ == '__main__':
    unittest.main()
