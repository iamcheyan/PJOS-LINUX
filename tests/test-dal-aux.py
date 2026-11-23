#!/usr/bin/env python3
"""Exercise the installed CLI contract without touching host hardware."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


USR = Path(__file__).resolve().parents[1] / 'overlay/usr'


class AuxHardware(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.profile = self.root / 'profile.env'
        self.env = dict(os.environ, DAL_LIB=str(USR / 'lib/baseos/dal.sh'),
                        DAL_DIR=str(USR / 'lib/baseos/dal'), DAL_ENV=str(self.profile),
                        PJOS_PROFILE_FILE=str(self.profile), PJOS_SYS_ROOT=str(self.root / 'sys'),
                        PJOS_PROFILE_DIR=str(self.root), PATH=f"{self.root}:/usr/bin:/bin")
        for name, identity in [('board', '"id": "fixture"'), ('soc', None),
                               ('caps', '"board": "fixture"'), ('features', '"board": "fixture"')]:
            lines = [f'"schema": "pjos.{name}/1"', '"soc": "allwinner/h700"']
            if identity:
                lines.append(identity)
            (self.root / f'{name}.json').write_text('{\n' + ',\n'.join(lines) + '\n}\n')

    def metadata(self, *fields):
        self.profile.write_text('\n'.join(('schema=pjos.dal/1', 'board=fixture',
                                           'soc=allwinner/h700', *fields)) + '\n')

    def cli(self, *args, code=0):
        result = subprocess.run([USR / 'sbin/baseos-hw', *args], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, code, (args, result.stderr))
        return result.stdout.strip()

    def node(self, path, value):
        node = self.root / path
        node.parent.mkdir(parents=True, exist_ok=True)
        node.write_text(value + '\n')
        return node

    def test_explicit_unknown_never_dispatches(self):
        self.metadata('cap.wifi=no', 'cap.bluetooth=unknown', 'cap.audio=unknown')
        self.cli('network', 'wifi-up', code=4)
        self.cli('network', 'bt-up', code=3)
        self.cli('audio', 'set-volume', '65', code=3)
        self.cli('storage', 'expand', code=3)
        self.cli('storage', 'usb-mode', 'prepare', code=3)
        self.cli('storage', 'role', 'rootfs', code=3)

    def test_storage_active_entry_only(self):
        self.metadata('storage.layout=baseos-ab-v1', 'storage.boot_disk=/dev/mmcblk0',
                      'storage.role.rootfs=/dev/mmcblk0p5')
        self.assertEqual(self.cli('storage', 'role', 'rootfs'), '/dev/mmcblk0p5')
        self.assertEqual(self.cli('storage', 'roles'), 'rootfs=/dev/mmcblk0p5')
        self.cli('storage', 'role', 'inactive', code=2)

    def test_actual_led_value_and_checked_write(self):
        path = '/sys/class/power_supply/pmic/work_led'
        led = self.node(path.lstrip('/'), '0')
        self.metadata('led.work_node=' + path)
        self.cli('led', 'set', 'work', 'on')
        self.cli('led', 'set', 'work', 'auto', code=4)
        self.assertEqual(led.read_text(), '1\n')
        self.assertEqual(self.cli('led', 'list'), 'work=1')

    def test_network_interface_from_metadata(self):
        self.metadata('cap.wifi=yes', 'network.wifi_iface=radio1')
        self.node('sys/class/net/radio1/operstate', 'dormant')
        self.node('ip', '#!/bin/sh\nprintf "%s\\n" "$@"').chmod(0o755)
        self.assertIn('wifi_state=dormant', self.cli('network', 'info'))
        self.assertEqual(self.cli('network', 'wifi-up').splitlines(),
                         ['link', 'set', 'dev', 'radio1', 'up'])

    def test_analog_volume_and_speaker_follow_user_setting(self):
        self.metadata('cap.audio=yes', 'audio.card_prefix=codec', 'audio.volume_control=digital volume',
                      'audio.lineout_control=lineout volume', 'audio.speaker_control=SPK')
        self.node('sys/class/sound/card2/id', 'codec0')
        self.node('amixer', '#!/bin/sh\nprintf "%s\\n" "$*"').chmod(0o755)
        self.assertEqual(self.cli('audio', 'set-volume', '0').splitlines(), [
            '-q -c 2 sset lineout volume 0%', '-q -c 2 sset digital volume 0%', '-q -c 2 sset SPK off'])
        self.assertEqual(self.cli('audio', 'set-volume', '50').splitlines(), [
            '-q -c 2 sset lineout volume 50%', '-q -c 2 sset digital volume 50%', '-q -c 2 sset SPK on'])

    def test_audio_matches_card_and_quotes_control(self):
        self.metadata('cap.audio=yes', 'audio.card_prefix=codec', 'audio.volume_control=digital volume')
        self.node('sys/class/sound/card2/id', 'codec0')
        self.node('amixer', '#!/bin/sh\nif [ "$3" = sget ]; then echo "Mono: [74%]"; '
                  'else printf "%s\\n" "$@"; fi').chmod(0o755)
        self.assertEqual(self.cli('audio', 'get-volume'), '74')
        self.assertEqual(self.cli('audio', 'set-volume', '0').splitlines(),
                         ['-q', '-c', '2', 'sset', 'digital volume', '0%'])
        self.cli('audio', 'set-volume', '101', code=2)
        self.cli('audio', 'mute', 'on', code=3)


if __name__ == '__main__':
    unittest.main()
