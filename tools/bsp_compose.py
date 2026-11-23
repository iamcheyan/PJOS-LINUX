#!/usr/bin/env python3
"""Compose one validated BSP target and its distribution, SoC and board overlays."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

import bsp_validate


PROJECT = Path(__file__).resolve().parents[1]


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def merge(source, dest):
    """Copy a layer without following symlinks from either layer."""
    if source.is_symlink():
        remove(dest)
        dest.symlink_to(source.readlink())
    elif source.is_dir():
        if dest.is_symlink() or not dest.is_dir():
            remove(dest)
            dest.mkdir()
        for entry in sorted(source.iterdir()):
            merge(entry, dest / entry.name)
        shutil.copystat(source, dest)
    elif source.is_file():
        remove(dest)
        shutil.copy2(source, dest)
    else:
        raise ValueError(f'unsupported overlay entry: {source}')


def dal_profile(profiles, release):
    """Plain key=value records for the target; never shell source this file."""
    board = profiles['board']
    values = {'schema': 'pjos.dal/1', 'board': board['id'], 'soc': board['soc'],
              'version': release.read_text().strip() if release.exists() else 'unknown'}
    for name, prefix in [('caps', 'cap'), ('features', 'feature')]:
        for key, value in profiles[name][name].items():
            values[f'{prefix}.{key}'] = value
    for section in ('panel', 'display'):
        for key, value in board.get(section, {}).items():
            values[f'display.{key}'] = ' '.join(value) if isinstance(value, list) else value
    declared = board.get('features', {})
    for key in ('storage_expand', 'storage_card_mount'):
        if key not in values:
            values[f'feature.{key}'] = declared.get(key, 'unknown')
    values['power.long_press'] = board.get('power', {}).get('long_press', 'unknown')
    values.setdefault('display.brightness_node', 'unknown')
    inputs = board.get('input', {})
    for role in sorted({'keyboard', 'power', 'gamepad', 'touch'} | inputs.get('roles', {}).keys()):
        record = inputs.get('roles', {}).get(role, {})
        name = record.get('name', inputs.get(f'{role}_name', 'unknown'))
        values[f'input.{role}'] = name
        if name != 'unknown':
            values[f'input.{role}.name'] = name
        for field, value in record.items():
            values[f'input.{role}.{field}'] = value
    if inputs.get('event_hint'):
        values['input.keyboard_node'] = inputs['event_hint']
    for key in ('battery', 'charger'):
        device = board.get('power', {}).get(key, 'unknown')
        if device is None:
            device = 'no'
        elif device not in ('no', 'unknown') and not device.startswith('/'):
            device = f'/sys/class/power_supply/{device}'
        values[f'power.{key}'] = device

    nodes = profiles['soc']['nodes']
    for key in ('rtc', 'poweroff', 'reboot', 'suspend_node'):
        if key in nodes.get('power', {}):
            values[f'power.{key}'] = nodes['power'][key]
    if 'menu_source' in inputs:
        values['input.menu_source'] = inputs['menu_source']
    # The driver namespace stays in the BSP; project only the records the DAL consumes.
    for group in ('audio', 'network', 'storage', 'led'):
        for key, value in nodes.get(group, {}).items():
            if isinstance(value, (str, int, float)):
                values[f'{group}.{key}'] = value
            elif group == 'storage' and key == 'roles' and isinstance(value, dict):
                for role, number in value.items():
                    values[f'storage.role.{role}'] = f"{nodes['storage']['boot_disk']}p{number}"
    for group in ('storage', 'network', 'led'):
        for key, value in board.get(group, {}).items():
            if isinstance(value, (str, int, float)):
                values[f'{group}.{key}'] = value
    for group in ('storage', 'network', 'led'):
        for key, value in board.get('overrides', {}).get('nodes', {}).get(group, {}).items():
            if isinstance(value, (str, int, float)):
                values[f'{group}.{key}'] = value

    audio = board.get('audio', {})
    for key in ('card_name', 'volume_control', 'pcm_gain_control', 'pcm_gain_raw', 'soft_volume_control'):
        if key in audio:
            values[f'audio.{key}'] = audio[key]
    values['profile.source'] = f"bsp/boards/{board['id']}/board.json+bsp/{board['soc']}/soc.json"
    values['firmware.mode'] = board['firmware']['mode']
    feature = profiles['features']
    mask = 1 << 31
    for bit, name in enumerate(feature['bitmask_order']):
        state = feature['features'][name]
        if state == 'yes':
            mask |= 1 << bit
        elif state == 'unknown':
            mask |= 1 << 30
    values['feature.bitmask'] = mask
    lines = []
    for key, value in sorted(values.items()):
        record = f'{key}={value}'
        if any(char in record for char in '\r\n\0') or '=' in key:
            raise ValueError(f'invalid DAL record for {key!r}')
        lines.append(record + '\n')
    return ''.join(lines)


def compose(root, target, output):
    root = root.resolve()
    bsp = root / 'bsp' if (root / 'bsp').is_dir() else root
    generic = bsp.parent / 'overlay'
    output = output.resolve()
    for source in (bsp, generic):
        if source == output or source in output.parents or output in source.parents:
            raise ValueError(f'output overlaps input: {source}')

    profiles = bsp_validate.compose(bsp, target)
    board = profiles['board']
    layers = (generic, bsp / board['soc'] / 'overlay',
              bsp / 'boards' / board['id'] / 'overlay')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        stage = Path(tmp)
        for name in ('board', 'soc', 'caps', 'features'):
            text = json.dumps(profiles[name], sort_keys=True, indent=2, allow_nan=False)
            (stage / f'{name}.json').write_text(text + '\n', encoding='utf-8')
        (stage / 'profile.env').write_text(dal_profile(profiles, bsp.parent / 'VERSION'),
                                           encoding='utf-8')
        for layer in layers:
            if layer != generic and not layer.exists() and not layer.is_symlink():
                continue
            if layer.is_symlink() or not layer.is_dir():
                raise ValueError(f'expected overlay directory: {layer}')
            merge(layer, stage / 'overlay')
        # Publish a fresh tree: reusing an output for another target must not
        # retain files from its predecessor. Leave unrelated artifacts alone.
        for item in sorted(stage.iterdir()):
            dest = output / item.name
            if item.name == 'overlay':
                remove(dest)
            item.replace(dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, help='board profile ID')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=PROJECT,
                        help='project root (or its bsp directory)')
    args = parser.parse_args()
    try:
        compose(args.root, args.target, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
