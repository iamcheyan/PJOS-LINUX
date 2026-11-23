#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_card

SHELL = ROOT / 'overlay/usr/share/pocketshell'
TG = 'trimui-tsp-fbdev'
H700 = 'rocknix-h700-kms'


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nset -eu\n' + body)
    path.chmod(0o755)


class CardBuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='pjos card test ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime = self.root / 'fixture runtime'
        self.package = self.root / 'fixture package'
        self.profile = self.root / 'export.json'
        self.inspector = self.root / 'fixture inspector'
        self.inspector.touch()
        self.output = self.root / 'payload'
        executable(self.runtime, '''
[ "$1" = --package ] && [ "$3" = --check ] || exit 2
read -r target abi digest < "$2"
[ "$target" = "$RUNTIME_TARGET" ] && [ "$digest" = "$RUNTIME_HASH" ] || exit 1
printf 'package admitted: %s (%s)\\n' "$2" "$target"
''')
        executable(self.root / 'bun', '''
[ "$1" = --no-install ] && [ -f "$2" ] && [ "$3" = inspect ] || exit 2
read -r target abi digest < "$4"
printf '  variant %s (abi %s) hash 1234\\n    profile %s\\n' "$target" "$abi" "$digest"
''')

    def build(self, target=TG, viewport=(1280, 720), layout='schema=pjos.input/1\nSTART key 315\n',
              export_target=None):
        def compose(root, target, stage):
            self.assertEqual(target, 'tg5040')
            stage.mkdir()
            (stage / 'profile.env').write_text(
                f'firmware.mode=card\nboard=tg5040\ndisplay.backend=fbdev\ndisplay.runtime_profile={TG}\n'
                'display.width=1280\ndisplay.height=720\n')
            for name in ('board', 'soc', 'caps', 'features'):
                (stage / f'{name}.json').touch()
            overlay = stage / 'overlay'
            for directory in ('usr/share/pocketshell/System/pocketjs/bin',
                              'usr/share/pocketshell/System/pocketjs/apps', 'usr/share/pocketshell/trimui/app',
                              'usr/lib/baseos/dal', 'usr/sbin', 'etc/pjos'):
                (overlay / directory).mkdir(parents=True)
            for file in ('usr/lib/baseos/dal.sh', 'usr/share/pocketshell/trimui/app/MainUI',
                         'usr/sbin/baseosctl', 'usr/sbin/baseos-hw', 'usr/sbin/baseos-hotkeys',
                         'usr/sbin/baseos-hotkey-service'):
                (overlay / file).touch()
            if layout is not None:
                (overlay / 'etc/pjos/input.map').write_text(layout)

        profile = {'id': export_target or target, 'display': {'physicalViewport': list(viewport)}}
        canonical = json.dumps(profile, sort_keys=True, separators=(',', ':'))
        digest = 'sha256:' + hashlib.sha256(canonical.encode()).hexdigest()
        self.profile.write_text(json.dumps(dict(format='pocket-profile/1', profile=profile,
                                               canonicalProfileJson=canonical, profileHash=digest, hostAbi=12)))
        self.package.write_text(f'{target} 12 {digest}\n')
        argv = ['build_card.py', '--output', str(self.output), '--profile', str(self.profile),
                '--runtime', str(self.runtime), '--package', str(self.package), '--inspector', str(self.inspector)]
        with (patch.object(build_card.bsp_compose, 'compose', compose),
              patch.object(build_card.platform, 'machine', return_value='aarch64'),
              patch.object(sys, 'argv', argv),
              patch.dict(os.environ, PATH=f'{self.root}:{os.environ["PATH"]}',
                         RUNTIME_TARGET=target, RUNTIME_HASH=digest)):
            build_card.main()

    def assert_rejected(self, expected, **kwargs):
        from contextlib import redirect_stderr
        from io import StringIO
        errors = StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
            self.build(**kwargs)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn(expected, errors.getvalue())
        self.assertFalse(self.output.exists())

    def test_missing_and_invalid_map(self):
        self.assert_rejected('missing input.map', layout=None)
        self.assert_rejected('at least one binding', layout='schema=pjos.input/1\n')
        self.assert_rejected('invalid input.map binding', layout='schema=pjos.input/1\nSTART key 768\n')

    def test_wrong_board_even_when_runtime_and_package_match(self):
        self.assert_rejected('requires admitted target trimui-tsp-fbdev', target=H700, viewport=(720, 480))

    def test_wrong_geometry_even_when_target_matches(self):
        self.assert_rejected('1280x720', viewport=(720, 480))

    def test_matching_card(self):
        self.build()
        self.assertTrue((self.output / 'System/profile/input.map').is_file())
        self.assertTrue((self.output / 'System/baseos-hotkey-service').is_file())


class GameHandoffTests(unittest.TestCase):
    def test_vendor_supervisor_handoff_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='pjos card test ') as tmp:
            card = Path(tmp)
            rom = card / 'Roms/GBA/My Game.gba'
            rom.parent.mkdir(parents=True)
            rom.touch()
            args_file = card / 'frontend args'
            ra = card / 'RetroArch'
            executable(ra / 'ra64.trimui', 'printf "%s\\n" "$PWD" "$@" > "$ARGS_FILE"\n')
            (ra / 'retroarch.cfg').touch()
            (ra / '.retroarch/cores').mkdir(parents=True)
            core = ra / '.retroarch/cores/mgba_libretro.so'
            core.touch()
            player = card / 'System/compat/bin/pocket-game-play'
            player.parent.mkdir(parents=True)
            shutil.copy2(SHELL / 'System/compat/bin/pocket-game-play', player)
            driver = card / 'System/compat/share/retroarch/driver-trimui.cfg'
            driver.parent.mkdir(parents=True)
            driver.touch()
            home = card / 'System/pocketjs'
            home.mkdir()
            marker = home / 'active'
            # Run the real supervisor's handoff before it starts another runtime.
            text = (SHELL / 'trimui/app/MainUI').read_text()
            loop = text.split('# 5. Main Supervisor Loop', 1)[1].split('\n', 1)[1]
            loop = loop.split('    echo "Starting pocket-linux-kms', 1)[0]
            env = dict(os.environ, PJOS_CARD_ROOT=tmp, SDCARD=tmp, POCKETJS_HOME=str(home),
                       LOG=str(card / 'boot log'), ARGS_FILE=str(args_file))
            for request in (str(rom), '/storage/Roms/GBA/My Game.gba', rom.name):
                with self.subTest(request=request):
                    marker.write_text(request + '\n')
                    subprocess.run(['sh', '-c', 'sleep() { exit 0; }\n' + loop + 'exit 99\ndone\n'],
                                   env=env, check=True, timeout=5)
                    self.assertFalse(marker.exists())
                    self.assertEqual(args_file.read_text().splitlines(), [str(ra), '-v', '--config',
                                     str(ra / 'retroarch.cfg'), '--appendconfig', str(driver), '-L', str(core), str(rom)])
                    self.assertEqual((card / '.config/pocketjs/last-active').read_text(), f'kind=rom\ntarget={rom}\n')
                    args_file.unlink()


if __name__ == '__main__':
    unittest.main()
