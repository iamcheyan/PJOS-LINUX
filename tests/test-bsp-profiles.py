#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/bsp_validate.py'


class Profiles(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'bsp'
        shutil.copytree(ROOT / 'bsp', self.root)
        self.path = self.root / 'boards/fakeboard/board.json'
        self.path.parent.mkdir()
        self.board = json.loads((self.root / 'boards/rg28xx/board.json').read_text())
        self.board['id'] = 'fakeboard'

    def cli(self, *args, ok=True):
        self.path.write_text(json.dumps(self.board))
        result = subprocess.run([sys.executable, TOOL, '--bsp-root', self.root, *args],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return result.stdout

    def test_new_board_needs_no_registration(self):
        self.board['overrides'] = {'nodes': {'network': {'bt_uart': None, 'wifi_iface': 'test0'}}}
        self.cli('all')
        result = json.loads(self.cli('compose', 'fakeboard'))
        self.assertEqual(result['soc']['nodes']['network'], {
            'wifi_iface': 'test0', 'wifi_ctrl': '/sys/class/misc/sunxi-wlan/rf-ctrl'})
        out = self.root.parent / 'out'
        self.cli('generate', 'fakeboard', out)
        for name in ('soc', 'board', 'caps', 'features'):
            self.assertEqual(json.loads((out / (name + '.json')).read_text()), result[name])

    def test_invalid_board_profiles(self):
        original = json.dumps(self.board)
        for field, key, value in [('identity', 'extra', 1), ('network', 'wifi', True),
                                  ('firmware', 'variant', 'missing'),
                                  ('overrides', 'nodes', {'wifi': None}),
                                  ('overrides', 'nodes', {'display': {'typo': None}}), ('capabilities', 'gpu', False),
                                  ('features', 'bt_sink', 'unknown'), ('panel', 'width', True),
                                  ('overrides', 'hw_init', [{'step': 'missing when'}])]:
            with self.subTest(field=field, key=key):
                self.board = json.loads(original)
                self.board.setdefault(field, {})[key] = value
                self.cli('board', self.path, ok=False)
        for field, value in [('id', 'other'), ('soc', 'vendor/missing')]:
            self.board = dict(json.loads(original), **{field: value})
            self.cli('board', self.path, ok=False)
        self.board = json.loads(original)
        del self.board['features']['wifi_ap']
        self.cli('board', self.path, ok=False)

    def test_soc_id_must_match_directory(self):
        path = self.root / self.board['soc'] / 'soc.json'
        soc = json.loads(path.read_text())
        soc['soc'] = 'other/chip'
        path.write_text(json.dumps(soc))
        self.cli('soc', path, ok=False)

    def test_wrong_audited_target(self):
        self.path = self.root / 'boards/rg28xx/board.json'
        self.board['id'] = 'rg28xx'
        self.board['firmware']['variant'] = 'rg34xx'
        self.cli('board', self.path, ok=False)

    def test_card_is_not_an_image_target(self):
        self.board = json.loads((self.root / 'boards/tg5040/board.json').read_text())
        self.board['id'] = 'fakeboard'
        self.assertEqual(self.board['firmware']['mode'], 'card')
        self.assertEqual(self.board['firmware']['observed_kernel_release'], '4.9.191')
        effective = json.loads(self.cli('compose', 'fakeboard'))
        self.assertEqual(effective['board']['input']['roles']['power']['name'], 'axp2202-pek')
        self.assertNotIn('harvest', effective['soc'])
        self.assertNotIn('profiles', effective['soc']['kernel'])
        self.board['firmware'] = {'mode': 'image', 'variant': 'rg28xx'}
        self.cli('board', self.path, ok=False)

    def test_legacy_inputs_preserved(self):
        h700 = self.root / 'allwinner/h700'
        for old, new in [('manifest/harvest.list', 'harvest.list'),
                         ('src/h700-speaker-amp/profiles.json', 'kernel/profiles.json')]:
            self.assertEqual((ROOT / old).read_bytes(), (h700 / new).read_bytes())
        for target in json.loads((ROOT / 'devices.json').read_text())['targets']:
            board = json.loads((self.root / 'boards' / target['id'] / 'board.json').read_text())
            for new, old in [('model', 'model'), ('model_string', 'model_string'),
                             ('frontend_family', 'baseos_device'), ('firmware_prefix', 'stockmod_prefix')]:
                self.assertEqual(board['identity'][new], target[old])
            for radio in ('wifi', 'bluetooth'):
                self.assertEqual(board['network'][radio], target[radio])
            for new, old in [('width', 'bootlogo_width'), ('height', 'bootlogo_height'),
                             ('rotation_ccw', 'panel_rotation_ccw')]:
                self.assertEqual(board['panel'][new], target[old])


if __name__ == '__main__':
    unittest.main()
