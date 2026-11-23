#!/usr/bin/env python3
"""Stage a PJOS card payload; never mount, erase or update a device."""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

import bsp_compose

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default='tg5040')
    parser.add_argument('--output', type=Path, required=True, help='new host directory')
    parser.add_argument('--runtime', type=Path, required=True, help='matched AArch64 release runtime')
    parser.add_argument('--package', type=Path, required=True, help='launcher built for this board')
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
        card = Path(tmp) / 'card'
        system = card / 'System'
        shutil.copytree(overlay / 'usr/share/pocketshell/System', system)
        profile = system / 'profile'
        profile.mkdir()
        for name in ('board.json', 'soc.json', 'caps.json', 'features.json', 'profile.env'):
            shutil.copyfile(stage / name, profile / name)
        layout = overlay / 'etc/pjos/input.map'
        if layout.is_file():
            shutil.copyfile(layout, profile / 'input.map')
        shutil.copyfile(overlay / 'usr/lib/baseos/dal.sh', system / 'dal.sh')
        shutil.copytree(overlay / 'usr/lib/baseos/dal', system / 'dal')
        for name in ('baseosctl', 'baseos-hw', 'baseos-hotkeys'):
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
        runner = [] if platform.machine() in ('aarch64', 'arm64') else ['qemu-aarch64']
        subprocess.run([*runner, runtime, '--package', package, '--check'], check=True)
        card.rename(out)


if __name__ == '__main__':
    main()
