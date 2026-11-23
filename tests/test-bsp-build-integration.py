#!/usr/bin/env python3
"""Host-only BSP integration checks. No Docker, toolchain or vendor image needed."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'rg28xx'


class BspIntegration(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'repo'
        shutil.copytree(ROOT / 'bsp', self.root / 'bsp')
        shutil.copytree(ROOT / 'docs/bsp-v2/schema', self.root / 'docs/bsp-v2/schema')
        shutil.copy(ROOT / 'devices.json', self.root)
        shutil.copy(ROOT / 'VERSION', self.root)
        (self.root / 'tools').mkdir()
        for name in ('device_profile.py', 'bsp_compose.py', 'bsp_validate.py'):
            shutil.copy(ROOT / 'tools' / name, self.root / 'tools')
        (self.root / 'overlay').mkdir()
        self.out = Path(tmp.name) / 'out'

    def cli(self, name, *args, success=True):
        result = subprocess.run([sys.executable, self.root / 'tools' / name, *args],
                                capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        return result.stdout

    def test_profile_parity_and_drift(self):
        path = self.root / 'devices.json'
        legacy = json.loads(path.read_text())
        for profile in legacy['targets']:
            args = ('shell', profile['id'])
            old = shlex.split(self.cli('device_profile.py', '--profiles', path, *args))
            new = shlex.split(self.cli('device_profile.py', *args))
            self.assertTrue(set(old).issubset(new))
            self.assertIn(f"PROFILE_TARGET={profile['id']}", new)
            self.assertIn('SOC_ID=h700', new)
            self.assertIn(f"BOARD_ID={profile['id']}", new)
        legacy['targets'][0]['model'] += ' drift'
        path.write_text(json.dumps(legacy))
        self.cli('device_profile.py', 'list', success=False)
        self.cli('device_profile.py', '--profiles', path, 'list')

    def test_compose_layer_order_and_reproducibility(self):
        board_dir = self.root / 'bsp/boards' / TARGET
        board = json.loads((board_dir / 'board.json').read_text())
        soc_dir = self.root / 'bsp' / board['soc']
        for i, layer in enumerate((self.root, soc_dir, board_dir)):
            directory = layer / 'overlay' / 'integration'
            directory.mkdir(parents=True)
            for filename in ('all', f'layer{i}'):
                (directory / filename).write_text(str(i))
            if i < 2:
                (directory / 'soc-over-generic').write_text(str(i))
        args = ('--target', TARGET, '--output')
        self.cli('bsp_compose.py', *args, self.out)
        merged = self.out / 'overlay/integration'
        self.assertEqual((merged / 'all').read_text(), '2')
        self.assertEqual((merged / 'soc-over-generic').read_text(), '1')
        for i in range(3):
            self.assertEqual((merged / f'layer{i}').read_text(), str(i))
        self.assertEqual(json.loads((self.out / 'board.json').read_text()), board)
        self.assertEqual(json.loads((self.out / 'soc.json').read_text()),
                         json.loads((soc_dir / 'soc.json').read_text()))
        self.assertEqual(json.loads((self.out / 'caps.json').read_text())['caps']['wifi'], 'no')
        self.assertEqual(json.loads((self.out / 'features.json').read_text())['board'], TARGET)
        second = self.out.with_name('second')
        self.cli('bsp_compose.py', *args, second)
        for name in ('board', 'soc', 'caps', 'features'):
            path = f'{name}.json'
            self.assertEqual((self.out / path).read_bytes(), (second / path).read_bytes())

    def test_rootfs_requires_prepared_vendor_inputs(self):
        shutil.copy(ROOT / 'build-rootfs.sh', self.root)
        shutil.copy(ROOT / 'tools/docker-platform.sh', self.root / 'tools')
        result = subprocess.run(['sh', self.root / 'build-rootfs.sh', TARGET],
                                capture_output=True, text=True, cwd=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source.json', result.stdout + result.stderr)

    def test_unknown_target_has_no_generated_metadata(self):
        self.cli('bsp_compose.py', '--target', 'notaboard', '--output', self.out, success=False)
        self.assertFalse((self.out / 'board.json').exists())


if __name__ == '__main__':
    unittest.main()
