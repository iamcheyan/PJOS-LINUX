#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'overlay/usr/share/pocketshell/System/compat/bin/rocknix-services'
class AdbService(unittest.TestCase):
    def test_explicit_set_and_repeat_enable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            tool=p/'gadget'
            tool.write_text('#!/bin/sh\ncase "$1" in status) cat "$TEST_STATE";; enable) echo enable >> "$TEST_CALLS"; echo on > "$TEST_STATE";; disable) echo disable >> "$TEST_CALLS"; echo off > "$TEST_STATE";; esac\n')
            tool.chmod(0o755)
            state=p/'state';state.write_text('off\n')
            calls=p/'calls'
            env=dict(os.environ, BASEOS_USB_GADGET_ADB=str(tool), TEST_STATE=str(state), TEST_CALLS=str(calls))
            def call(*args): return subprocess.check_output(['sh',str(SCRIPT),*args],text=True,env=env).strip()
            self.assertEqual(call('status','adbusb.enabled'),'adbusb.enabled=0')
            self.assertEqual(call('set','adbusb.enabled','on'),'adbusb.enabled=1')
            self.assertEqual(call('set','adbusb.enabled','on'),'adbusb.enabled=1')
            self.assertEqual(call('toggle','adbusb.enabled','off'),'adbusb.enabled=0')
            self.assertEqual(calls.read_text().splitlines(),['enable','enable','disable'])
            self.assertEqual(call('toggle','adbusb.enabled'),'adbusb.enabled=1')
if __name__ == '__main__': unittest.main()
