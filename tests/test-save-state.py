#!/usr/bin/env python3
"""Resume follows the active session, never a previously exited application."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'overlay/usr/sbin/baseos-save-state'

class SaveState(unittest.TestCase):
    def run_case(self, foreground, running=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bindir=root/'bin';bindir.mkdir()
            for name,body in [('sync','exit 0'),('pidof','[ "$1" = pocket-linux-kms ] && [ "$TEST_RUNNING" = 1 ]')]:
                path=bindir/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o755)
            (root/'last-active').write_text('kind=app\ntarget=exited-app\n')
            (root/'resume.state').write_text('kind=app\ntarget=stale-resume\n')
            if foreground is not None:(root/'foreground').write_text(foreground+'\n')
            source=SOURCE.read_text().replace('STATE_DIR=/storage/.config/pocketjs','STATE_DIR='+str(root)).replace('/run/baseos-foreground-app',str(root/'foreground')).replace('/tmp/baseos-save-state.log',str(root/'log'))
            script=root/'save.sh';script.write_text(source)
            subprocess.run(['sh',str(script)],env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'],TEST_RUNNING='1' if running else '0'),check=True)
            resume=root/'resume.state'
            return resume.read_text() if resume.exists() else None

    def test_launcher_shutdown_does_not_reopen_last_exited_app(self):
        self.assertIsNone(self.run_case(None))

    def test_current_app_identity_wins_over_old_history(self):
        self.assertEqual(self.run_case('kanade'),'kind=app\ntarget=kanade\n')

    def test_missing_runtime_and_invalid_identity_do_not_resume(self):
        self.assertIsNone(self.run_case('kanade',False))
        self.assertIsNone(self.run_case('../bad'))

if __name__=='__main__':unittest.main()
