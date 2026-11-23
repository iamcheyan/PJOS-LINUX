#!/usr/bin/env python3
"""Display metadata remains useful on panels without brightness controls."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAL = ROOT / 'overlay/usr/lib/baseos/dal/display.sh'


class DisplayMetadata(unittest.TestCase):
    def test_static_geometry_succeeds_without_brightness(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / 'meta').write_text(
                'display.backend=framebuffer\n'
                'display.width=720\n'
                'display.height=480\n'
                'display.bpp=32\n'
                'display.rotation_ccw=0\n'
                'display.logical_width=720\n'
                'display.logical_height=480\n'
                'display.vsync=unknown\n'
                'display.outputs=lcd\n'
            )
            script = f'''\
PJOS_META_FILE={base}/meta
. {DAL}
dal_init() {{ :; }}
dal_meta() {{ sed -n "s/^$1=//p" "$PJOS_META_FILE"; }}
dal_display_level_get() {{ return 4; }}
export PJOS_META_FILE
 dal_display_info
'''
            result = subprocess.run(['sh', '-c', script], text=True, capture_output=True, env=os.environ.copy())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('width=720\n', result.stdout)
            self.assertIn('height=480\n', result.stdout)
            self.assertIn('brightness=unknown\n', result.stdout)


if __name__ == '__main__':
    unittest.main()
