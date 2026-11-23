#!/usr/bin/env python3
"""The system owner re-resolves roles after a failed input reader."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'overlay/usr/sbin/baseos-hotkey-service'


class HotkeyService(unittest.TestCase):
    def test_disconnect_rebinds_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'run').mkdir()
            lib = base / 'dal.sh'
            lib.write_text('dal_init() { :; }\ndal_meta() { echo ignore; }\n')
            ctl = base / 'baseosctl'
            ctl.write_text('''#!/bin/sh
n=$(cat "$FIXTURE/generation" 2>/dev/null || echo 0)
case "$*" in
  'input node power') echo "/dev/input/power-$n" ;;
  'input node gamepad') echo "/dev/input/pad-$n" ;;
  *) exit 2 ;;
esac
''')
            daemon = base / 'hotkeys'
            daemon.write_text('''#!/bin/sh
printf '%s\n' "$*" >> "$FIXTURE/calls"
if [ ! -f "$FIXTURE/generation" ]; then
    echo 1 > "$FIXTURE/generation"
    exit 1
fi
exit 0
''')
            for path in (ctl, daemon):
                path.chmod(0o755)
            env = dict(os.environ, FIXTURE=directory, PJOS_BASEOSCTL=str(ctl),
                       BASEOS_HOTKEY_DAEMON=str(daemon), DAL_LIB=str(lib), PJOS_RUN_ROOT=directory)
            result = subprocess.run(['sh', str(SERVICE)], env=env, capture_output=True,
                                    text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((base / 'calls').read_text().splitlines(), [
                f'--baseosctl {ctl} --power-dev /dev/input/power-0 --pad-dev /dev/input/pad-0 --long-press ignore',
                f'--baseosctl {ctl} --power-dev /dev/input/power-1 --pad-dev /dev/input/pad-1 --long-press ignore',
            ])


if __name__ == '__main__':
    unittest.main()
