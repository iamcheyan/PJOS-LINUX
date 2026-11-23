#!/usr/bin/env python3
"""Fake-tree checks for semantic operations without touching host hardware."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
USR = ROOT / 'overlay/usr'


class DalOperations(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = self.root / 'profile.env'
        self.env = dict(os.environ, DAL_LIB=str(USR / 'lib/baseos/dal.sh'),
                        DAL_DIR=str(USR / 'lib/baseos/dal'), DAL_ENV=str(self.profile),
                        PJOS_PROFILE_FILE=str(self.profile), PJOS_SYS_ROOT=str(self.root / 'sys'),
                        PJOS_DEV_ROOT=str(self.root), PJOS_PROFILE_DIR=str(self.root),
                        BASEOS_INPUT_STATE='/not-used', PATH=f"{self.root}:/usr/bin:/bin")
        for name, identity in [('board', '"id": "fixture"'), ('soc', None),
                               ('caps', '"board": "fixture"'), ('features', '"board": "fixture"')]:
            rows = [f'"schema": "pjos.{name}/1"', '"soc": "allwinner/h700"']
            if identity:
                rows.append(identity)
            (self.root / f'{name}.json').write_text('{' + ','.join(rows) + '}')

    def metadata(self, *fields):
        self.profile.write_text('\n'.join(('schema=pjos.dal/1', 'board=fixture',
                                           'soc=allwinner/h700', *fields)) + '\n')

    def call(self, *args, expected=0):
        p = subprocess.run([USR / 'sbin/baseos-hw', *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, expected, (args, p.stderr))
        return p.stdout

    def file(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_key_state_role_resolves_and_runs_actual_helper(self):
        self.metadata('input.gamepad.name=Game Pad')
        event = self.root / 'dev/input/event9'
        event.parent.mkdir(parents=True)
        event.touch()
        self.file('sys/class/input/event9/device/name', 'Game Pad')
        helper = self.file('key-state', '#!/bin/sh\nprintf "pressed=1\\n"\nprintf "%s %s\\n" "$1" "$2" > "$TRACE"')
        helper.chmod(0o755)
        trace = self.root / 'trace'
        self.env.update(BASEOS_INPUT_STATE=str(helper), TRACE=str(trace))
        self.assertEqual(self.call('input', 'key-state', 'gamepad', 'BTN_A'), 'pressed=1\n')
        self.assertEqual(trace.read_text(), f'{event} BTN_A\n')
        self.call('input', 'key-state', 'power', 'BTN_A', expected=3)

    def test_unknown_vibration_and_storage_never_call_unverified_adapters(self):
        self.metadata('cap.vibration=unknown', 'feature.storage_expand=yes',
                      'storage.expand_hook=/tmp/no-such-hook', 'feature.storage_card_mount=yes')
        self.call('led', 'vibrate', '90', expected=3)
        self.call('storage', 'expand', expected=3)
        self.call('storage', 'card-mount', expected=3)

    def test_profile_hook_routes_mount_and_expand(self):
        hook = self.file('adapter', '#!/bin/sh\nprintf "%s\\n" "$*"')
        hook.chmod(0o755)
        self.metadata('feature.storage_expand=yes', 'feature.storage_card_mount=yes',
                      f'storage.expand_hook={hook}', f'storage.card-mount_hook={hook}')
        self.assertEqual(self.call('storage', 'expand'), '\n')
        self.assertEqual(self.call('storage', 'card-mount'), '\n')

    def test_wifi_scan_normalizes_cli_output_and_mdns_uses_hook(self):
        self.metadata('cap.wifi=yes', 'network.wifi_iface=radio1', 'network.mdns_hook=/no-hook')
        (self.root / 'sys/class/net/radio1').mkdir(parents=True)
        iw = self.file('iw', '#!/bin/sh\nprintf "BSS aa (on radio1)\\n\\t signal: -48.00 dBm\\n\\t SSID: Example\\n\\t RSN: *\\n"')
        iw.chmod(0o755)
        self.assertEqual(self.call('network', 'wifi-scan'), 'ssid=Example signal=52 security=wpa2\n')
        self.call('network', 'mdns', 'refresh', expected=3)

    def test_led_vibrate_duration_uses_declared_node(self):
        node = self.file('sys/class/leds/haptic/duration', '0')
        self.metadata('cap.vibration=yes', 'led.vibration_node=/sys/class/leds/haptic/duration')
        self.call('led', 'vibrate', '120')
        self.assertEqual(node.read_text(), '120\n')


if __name__ == '__main__':
    unittest.main()
