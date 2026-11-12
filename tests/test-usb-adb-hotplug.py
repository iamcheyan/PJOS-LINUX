#!/usr/bin/env python3
"""Hotplug policy without touching the development machine's USB controllers."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'overlay/usr/sbin/hotplug'

class AdbHotplug(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.sys = self.base/'sys'
        self.run = self.base/'run'
        self.run.mkdir()
        (self.run/'usb-adb-hotplug-ready').touch()
        self.gadget = self.sys/'kernel/config/usb_gadget/g1'
        (self.gadget/'configs/c.1/ffs.adb').mkdir(parents=True)
        (self.gadget/'UDC').write_text('')
        self.role = self.sys/'devices/platform/soc/usbc0/otg_role'
        self.role.parent.mkdir(parents=True)
        self.role.write_text('usb_device\n')
        self.online = self.sys/'class/power_supply/axp2202-usb/online'
        self.online.parent.mkdir(parents=True)
        self.online.write_text('1\n')
        self.calls = self.base/'calls'
        setup = self.base/'setup'
        setup.write_text('#!/bin/sh\necho "$*" >> "$TEST_CALLS"\n')
        setup.chmod(0o755)
        self.env = dict(os.environ, BASEOS_SYS_ROOT=str(self.sys), BASEOS_RUN_ROOT=str(self.run), BASEOS_ADB_SETUP=str(setup), TEST_CALLS=str(self.calls), SUBSYSTEM='power_supply', ACTION='change')
    def tearDown(self): self.tmp.cleanup()
    def invoke(self):
        subprocess.run(['sh', str(SCRIPT)], env=self.env, check=True, timeout=4)
        return self.calls.read_text().splitlines() if self.calls.exists() else []
    def test_connected_device_recovers(self): self.assertEqual(self.invoke(), ['setup'])
    def test_bound_gadget_is_untouched(self):
        (self.gadget/'UDC').write_text('5100000.udc-controller\n')
        self.assertEqual(self.invoke(), [])
    def test_host_role_is_never_overridden(self):
        self.role.write_text('usb_host\n')
        self.assertEqual(self.invoke(), [])
        self.assertEqual(self.role.read_text(), 'usb_host\n')
    def test_disconnect_is_ignored(self):
        self.online.write_text('0\n')
        self.assertEqual(self.invoke(), [])
    def test_boot_selection_finishes_before_hotplug(self):
        (self.run/'usb-adb-hotplug-ready').unlink()
        self.assertEqual(self.invoke(), [])
    def test_unrelated_event_ignored(self):
        self.env['SUBSYSTEM'] = 'input'
        self.assertEqual(self.invoke(), [])
    def test_opt_out(self):
        self.env['BASEOS_DISABLE_ADB'] = '1'
        self.assertEqual(self.invoke(), [])
    def test_only_existing_adb_function_recovers(self):
        (self.gadget/'configs/c.1/ffs.adb').rmdir()
        self.assertEqual(self.invoke(), [])

if __name__ == '__main__': unittest.main()
