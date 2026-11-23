#!/usr/bin/env python3
"""Stage a PJOS card payload; never mount, erase or update a device."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

import bsp_compose

ROOT = Path(__file__).resolve().parents[1]

BUTTONS = set('UP DOWN LEFT RIGHT START SELECT CIRCLE CROSS SQUARE TRIANGLE LTRIGGER RTRIGGER ZL ZR'.split())


def validate_input_map(path):
    if not path.is_file():
        raise ValueError('missing input.map')
    lines = path.read_text(encoding='ascii').splitlines()
    if len(lines) < 2 or lines[0] != 'schema=pjos.input/1':
        raise ValueError('input.map requires schema=pjos.input/1 and at least one binding')
    for number, line in enumerate(lines[1:], 2):
        fields = line.split()
        if len(fields) >= 3 and fields[0] in BUTTONS:
            op, *values = fields[1:]
            if op == 'key' and all(re.fullmatch(r'\+?[0-9]+', n) and int(n) < 768 for n in values):
                continue
            if op in ('lt', 'gt') and len(values) == 2:
                code, threshold = values
                if (re.fullmatch(r'\+?[0-9]+', code) and int(code) < 64
                        and re.fullmatch(r'[+-]?[0-9]+', threshold)
                        and -(2**31) <= int(threshold) < 2**31):
                    continue
        raise ValueError(f'invalid input.map binding on line {number}')


def check_admission(runtime, package, export, inspector, flat):
    expected_target = flat.get('display.runtime_profile')
    if not expected_target:
        raise ValueError('composed board is missing display.runtime_profile')
    runner = [] if platform.machine() in ('aarch64', 'arm64') else ['qemu-aarch64']
    check = subprocess.check_output([*runner, runtime, '--package', package, '--check'], text=True)
    if f'package admitted: {package} ({expected_target})' not in check.splitlines():
        raise ValueError(f'{flat["board"]} requires admitted target {expected_target}; got {check.strip()!r}')

    metadata = json.loads(export.read_text(encoding='utf-8'))
    canonical = metadata['canonicalProfileJson']
    profile = metadata['profile']
    panel = [int(flat['display.width']), int(flat['display.height'])]
    if (metadata['format'] != 'pocket-profile/1' or json.loads(canonical) != profile
            or profile['id'] != expected_target or profile['display']['physicalViewport'] != panel):
        raise ValueError(f'profile export must describe {expected_target} at {panel[0]}x{panel[1]}')
    digest = 'sha256:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    if metadata['profileHash'] != digest:
        raise ValueError('profile export hash does not match its canonical profile')

    inspection = subprocess.check_output(['bun', '--no-install', inspector, 'inspect', package], text=True)
    variants = re.findall(r'^  variant (\S+) \(abi (\d+)\) hash [0-9a-f]+\n    profile (sha256:[0-9a-f]{64})$',
                          inspection, re.MULTILINE)
    matching = [(abi, hash_) for target, abi, hash_ in variants if target == expected_target]
    if matching != [(str(metadata['hostAbi']), digest)]:
        raise ValueError(f'package variant for {expected_target} does not match the exported profile hash and ABI')
    print(check, end='')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default='tg5040')
    parser.add_argument('--output', type=Path, required=True, help='new host directory')
    parser.add_argument('--runtime', type=Path, required=True, help='matched AArch64 release runtime')
    parser.add_argument('--package', type=Path, required=True, help='launcher built for this board')
    parser.add_argument('--profile', type=Path, required=True, help='matching PocketJS profile export JSON')
    parser.add_argument('--inspector', type=Path, required=True, help='local PocketJS tools/pocket-pack.ts')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or out == ROOT or out in ROOT.parents:
        parser.error('output must be a new host staging directory')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        stage = Path(tmp) / 'bsp'
        bsp_compose.compose(ROOT, args.target, stage)
        flat = dict(line.split('=', 1) for line in (stage / 'profile.env').read_text().splitlines())
        if flat['firmware.mode'] != 'card':
            parser.error('target is not a vendor-SD profile')
        overlay = stage / 'overlay'
        layout = overlay / 'etc/pjos/input.map'
        try:
            validate_input_map(layout)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        card = Path(tmp) / 'card'
        system = card / 'System'
        shutil.copytree(overlay / 'usr/share/pocketshell/System', system)
        profile = system / 'profile'
        profile.mkdir()
        for name in ('board.json', 'soc.json', 'caps.json', 'features.json', 'profile.env'):
            shutil.copyfile(stage / name, profile / name)
        shutil.copyfile(layout, profile / 'input.map')
        shutil.copyfile(overlay / 'usr/lib/baseos/dal.sh', system / 'dal.sh')
        shutil.copytree(overlay / 'usr/lib/baseos/dal', system / 'dal')
        for name in ('baseosctl', 'baseos-hw', 'baseos-hotkeys', 'baseos-hotkey-service'):
            shutil.copy2(overlay / 'usr/sbin' / name, system / name)
        hook = card / 'trimui/app/MainUI'
        hook.parent.mkdir(parents=True)
        shutil.copy2(overlay / 'usr/share/pocketshell/trimui/app/MainUI', hook)
        hook.chmod(0o755)
        # Admission is a build gate, not evidence of gameplay or power-key behavior.
        runtime = system / 'pocketjs/bin/pocket-linux-kms'
        package = system / 'pocketjs/apps/boot.pocket'
        shutil.copy2(args.runtime, runtime)
        shutil.copy2(args.package, package)
        try:
            check_admission(runtime, package, args.profile, args.inspector.resolve(), flat)
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
            parser.error(f'card admission failed: {exc}')
        card.rename(out)


if __name__ == '__main__':
    main()
