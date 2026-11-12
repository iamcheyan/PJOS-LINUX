"""A PCM ramp's transient maximum must never become the user's volume."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / 'overlay/usr/share/pocketshell/System/compat/bin/heya-control'

class VolumeState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.cache = self.path / 'volume.percent'
        self.env = dict(os.environ, PATH=str(self.path)+':'+os.environ['PATH'], BASEOS_VOLUME_STATE=str(self.cache))
        mixer = self.path / 'amixer'
        mixer.write_text('#!/bin/sh\n[ \"${MIXER_FAIL:-0}\" = 0 ] || exit 1\ncase "$*" in *sget*) echo "  Mono: Playback 63 [100%]" ;; esac\n')
        mixer.chmod(0o755)
    def run_control(self, *args):
        return subprocess.run(['sh', str(CONTROL), *args], env=self.env, text=True, capture_output=True)
    def test_pcm_transient_maximum_does_not_replace_requested_volume(self):
        result = self.run_control('volume', '40')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cache.read_text().strip(), '40')
        self.assertEqual(self.run_control('volume-state').stdout.strip(), '40')
    def test_boot_without_cache_reads_mixer(self):
        result = self.run_control('volume-state')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '100')
    def test_invalid_cache_falls_back_to_mixer(self):
        for value in ('garbage', '101', '-1', ''):
            self.cache.write_text(value)
            self.assertEqual(self.run_control('volume-state').stdout.strip(), '100')
    def test_failed_mixer_does_not_publish(self):
        self.cache.write_text("35\n")
        self.env["MIXER_FAIL"] = "1"
        self.assertNotEqual(self.run_control("volume", "40").returncode, 0)
        self.assertEqual(self.cache.read_text(), "35\n")
    def test_invalid_volume_does_not_publish(self):
        self.assertNotEqual(self.run_control('volume', '101').returncode, 0)
        self.assertFalse(self.cache.exists())

if __name__ == '__main__': unittest.main()
