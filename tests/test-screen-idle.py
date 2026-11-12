#!/usr/bin/env python3
"""Run the real idle loop with a fake panel, time, and empty input directory."""
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'overlay/usr/sbin/baseos-screen-idle'

class ScreenIdle(unittest.TestCase):
    def test_auto_blank_marker_does_not_block_input_wake(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            for name in ['bin', 'run', 'input']: (base/name).mkdir()
            (base/'last').write_text('0')
            (base/'config').write_text('timeout = 10s\nauto_stop_timeout = never\n')
            def program(name, code):
                path = base/'bin'/name
                path.write_text('#!/bin/sh\n'+code)
                path.chmod(0o755)
            program('panel', 'case "$1" in\nlevel) echo 50;;\noff) echo off >> "$TEST_BASE/actions"; touch "$TEST_BASE/run/panel.off";;\non) echo on >> "$TEST_BASE/actions"; rm -f "$TEST_BASE/run/panel.off";;\nesac\n')
            program('date', 'case "$1" in +%s) echo 100;; *) echo now;; esac\n')
            program('stat', 'cat "$TEST_BASE/last"\n')
            program('sleep', 'n=$(cat "$TEST_BASE/count" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$TEST_BASE/count"; echo 100 > "$TEST_BASE/last"; if [ "$n" -ge 3 ]; then kill -TERM "$PPID"; fi\n')
            source = SOURCE.read_text().replace('/run/', str(base/'run')+'/').replace('/tmp/baseos-screen-idle.log', str(base/'log')).replace('/storage/.config/baseos/screen-idle.conf', str(base/'config')).replace('/storage/.config/pocketjs/runtime.conf', str(base/'missing-runtime')).replace('/dev/input/event*', str(base/'input/event*')).replace('/usr/sbin/baseos-panel', str(base/'bin/panel')).replace('/mnt/sdcard/System/bin/baseos-panel', str(base/'missing-panel'))
            daemon = base/'idle.sh'
            daemon.write_text(source)
            env = dict(os.environ, TEST_BASE=d, PATH=str(base/'bin')+':'+os.environ['PATH'])
            subprocess.run(['sh', str(daemon)], env=env, timeout=3, capture_output=True)
            self.assertEqual((base/'actions').read_text().splitlines(), ['off', 'on'])
    def test_valid_duration_units_and_leading_zeroes(self):
        prefix = SOURCE.read_text().split('configured_timeout() {')[0]
        for value, expected in [('never', 0), ('off', 0), ('none', 0), ('0', 0), ('10s', 10), ('1m', 60), ('2h', 7200), ('08s', 8)]:
            with self.subTest(value=value):
                result = subprocess.run(['sh', '-c', prefix+'\nseconds "$1" 0', 'test', value], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), str(expected))

    def test_malformed_power_timeout_fails_closed(self):
        # Source only the pure parser, with no daemon side effects.
        prefix = SOURCE.read_text().split('configured_timeout() {')[0]
        for value in ['potato', 'oopsm', '-1', '1;exit', '10ms']:
            with self.subTest(value=value):
                result = subprocess.run(['sh', '-c', prefix+'\nseconds "$1" 0', 'test', value], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), '0')

if __name__ == '__main__': unittest.main()
