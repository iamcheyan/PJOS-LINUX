#!/usr/bin/env python3
"""Exercise the real wrapper with disposable processes and fake media binaries."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'overlay/usr/share/pocketshell/System/compat/bin/mpv'

class MpvWrapper(unittest.TestCase):
    def test_video_waits_for_child_before_resuming_ui(self):
        self.exercise(False)

    def test_audio_keeps_ui_alive_and_cleans_its_marker(self):
        self.exercise(True)

    def exercise(self, audio):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ui = subprocess.Popen(['sleep', '120'])
            wrapper = None
            def wait_until(predicate):
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.01)
                self.fail('timed out waiting for wrapper')
            def ui_stopped():
                return '\nState:\tT' in Path(f'/proc/{ui.pid}/status').read_text()
            try:
                bindir = root / 'bin'; bindir.mkdir()
                pidof = bindir / 'pidof'
                pidof.write_text(f'#!/bin/sh\necho {ui.pid}\n'); pidof.chmod(0o755)
                fake = root / 'mpv'
                fake.write_text('''#!/bin/sh
trap 'touch "$TEST_ROOT/terminating"; sleep .3; touch "$TEST_ROOT/finished"; exit 0' TERM
 touch "$TEST_ROOT/started"
while :; do sleep .05; done
'''); fake.chmod(0o755)
                pan = root / 'pan'; pan.write_text('0,480')
                source = SOURCE.read_text().replace('D=/storage/System/compat/mpv', f'D={root}').replace('/sys/class/graphics/fb0/pan', str(pan)).replace('/run/baseos-audio-playing', str(root / 'audio-playing')).replace('/storage/System/compat/bin/baseos-mpv-keys', str(root / 'missing-helper'))
                script = root / 'wrapper'; script.write_text(source)
                env = dict(os.environ, TEST_ROOT=str(root), PATH=str(bindir)+':'+os.environ['PATH'])
                wrapper = subprocess.Popen(['sh', str(script)] + (['--vo=null'] if audio else []), env=env)
                wait_until(lambda: (root / 'started').exists())
                self.assertEqual(ui_stopped(), not audio)
                if audio:
                    self.assertEqual((root / 'audio-playing').read_text().strip(), str(wrapper.pid))
                wrapper.terminate()
                wait_until(lambda: (root / 'terminating').exists())
                # The mock player deliberately takes time to release its output.
                self.assertEqual(ui_stopped(), not audio)
                self.assertIsNone(wrapper.poll())
                self.assertEqual(wrapper.wait(timeout=4), 143)
                self.assertTrue((root / 'finished').exists())
                self.assertFalse(ui_stopped())
                self.assertFalse((root / 'audio-playing').exists())
            finally:
                if wrapper is not None and wrapper.poll() is None:
                    wrapper.kill(); wrapper.wait()
                os.kill(ui.pid, signal.SIGCONT)
                ui.terminate(); ui.wait()

if __name__ == '__main__': unittest.main()
