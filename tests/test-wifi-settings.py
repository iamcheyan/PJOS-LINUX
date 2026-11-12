import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'overlay/usr/share/pocketshell/System/compat/bin/rocknix-settings'
class WifiSettings(unittest.TestCase):
    def test_state(self):
        with tempfile.TemporaryDirectory() as d:
            probe = Path(d) / 'wpa_cli'
            probe.write_text('#!/bin/sh\nprintf "%s\\n" "$WIFI_STATE"\n')
            probe.chmod(0o755)
            for state, expected in [('wpa_state=COMPLETED', '1'), ('wpa_state=DISCONNECTED', '1'), ('wpa_state=INTERFACE_DISABLED', '0')]:
                with self.subTest(state=state):
                    result = subprocess.run(['sh', str(SCRIPT), '--command', 'load', '--key', 'wifi.enabled'], env=dict(os.environ, PATH=d+':'+os.environ['PATH'], WIFI_STATE=state), text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout.strip(), expected)
if __name__ == '__main__': unittest.main()
