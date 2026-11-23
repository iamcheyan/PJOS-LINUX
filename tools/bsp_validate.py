#!/usr/bin/env python3
"""Validate BSP profiles or generate the four build-time JSON artifacts."""
import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
SCHEMAS = PROJECT / 'bsp/schema'
DEPENDENCIES = {
    'bt_sink': 'bluetooth', 'bt_source': 'bluetooth', 'audio_hw_volume': 'audio',
    'audio_hw_mute': 'audio', 'display_output_switch': 'hdmi', 'rtc_alarm': 'rtc',
    'usb_storage_export': 'usb_gadget', 'usb_adb': 'usb_gadget',
    'usb_host_input': 'usb_host', 'wifi_ap': 'wifi',
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate field {key!r}')
        result[key] = value
    return result


def finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f'invalid JSON number {text}')
    return value


def load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                          parse_float=finite_float, parse_constant=finite_float)
    except ValueError as exc:
        raise ValueError(f'{path}: {exc}') from exc


@lru_cache(maxsize=None)
def schema(name):
    return load(SCHEMAS / f'{name}.schema.json')


# The build environment provides stock Python only. Interpret the assertion
# keywords used by the checked-in schemas and fail closed on new keywords.
KEYWORDS = set('type const enum pattern required properties additionalProperties items prefixItems '
               'anyOf minItems maxItems minLength minimum exclusiveMinimum $ref $defs '
               '$schema $id title description minProperties'.split())
JSON_TYPES = {dict: 'object', list: 'array', str: 'string', int: 'integer',
              float: 'number', bool: 'boolean', type(None): 'null'}


def check(value, rule, path, spec):
    def require(ok, message):
        if not ok:
            raise ValueError(f'{path}: {message}')

    require(not (rule.keys() - KEYWORDS), f'unsupported schema keywords {rule.keys() - KEYWORDS}')
    if '$ref' in rule:
        filename, pointer = rule['$ref'].split('#/', 1)
        source = schema('soc') if filename == 'soc-1.json' else spec
        require(filename in ('', 'soc-1.json'), 'invalid schema reference')
        target = source
        for part in pointer.split('/'):
            target = target[part]
        check(value, target, path, source)
    kind = JSON_TYPES[type(value)]
    if 'type' in rule:
        types = rule['type'] if isinstance(rule['type'], list) else [rule['type']]
        require(kind in types or (kind == 'integer' and 'number' in types), f'expected {types}')
    if 'const' in rule or 'enum' in rule:
        choices = rule['enum'] if 'enum' in rule else [rule['const']]
        require(any(type(value) is type(item) and value == item for item in choices),
                f'expected one of {choices}')
    if isinstance(value, dict):
        missing = set(rule.get('required', ())) - value.keys()
        require(not missing, f'missing fields {sorted(missing)}')
        props = rule.get('properties', {})
        for key, entry in value.items():
            child = props.get(key, rule.get('additionalProperties', True))
            require(child is not False, f'unknown field {key!r}')
            if isinstance(child, dict):
                check(entry, child, f'{path}.{key}', spec)
    if 'anyOf' in rule:
        for variant in rule['anyOf']:
            try:
                check(value, variant, path, spec)
                break
            except ValueError:
                pass
        else:
            raise ValueError(f'{path}: expected one of {rule["anyOf"]}')
    if isinstance(value, dict):
        require(len(value) >= rule.get('minProperties', 0), 'too few object properties')
    if isinstance(value, list):
        require(rule.get('minItems', 0) <= len(value) <= rule.get('maxItems', len(value)),
                'invalid array length')
        prefix = rule.get('prefixItems', [])
        for i, item in enumerate(value):
            child = prefix[i] if i < len(prefix) else rule.get('items', {})
            check(item, child, f'{path}[{i}]', spec)
    if isinstance(value, str):
        require(len(value) >= rule.get('minLength', 0), 'string too short')
        if 'pattern' in rule:
            require(re.search(rule['pattern'], value), f'expected pattern {rule["pattern"]}')
    if 'minimum' in rule:
        require(value >= rule['minimum'], f'must be >= {rule["minimum"]}')
    if 'exclusiveMinimum' in rule:
        require(value > rule['exclusiveMinimum'], f'must be > {rule["exclusiveMinimum"]}')


def validate(value, name, path):
    spec = schema(name)
    check(value, spec, path, spec)


def key_order(group):
    return schema('board')['properties'][group]['required']


def profile(root, name, selector):
    base = root / 'boards' if name == 'board' else root
    pattern = r'[a-z0-9]+' if name == 'board' else r'[a-z0-9]+/[a-z0-9]+'
    path = (base / selector / f'{name}.json' if re.fullmatch(pattern, str(selector))
            else Path(selector))
    data = load(path)
    validate(data, name, path)
    ident = data['id' if name == 'board' else 'soc']
    if not re.fullmatch(pattern, ident) or path.resolve() != (base / ident / f'{name}.json').resolve():
        raise ValueError(f'{path}: directory does not match {name} {ident!r}')
    return data


def validate_deps(data, label):
    caps = data.get('capabilities', {})
    for feat, cap in DEPENDENCIES.items():
        state = data.get('features', {}).get(feat)
        if state is not None and caps.get(cap) == 'no' and state != 'no':
            raise ValueError(f'{label}: {cap}=no requires {feat}=no')
        if state == 'yes' and cap in caps and caps[cap] != 'yes':
            raise ValueError(f'{label}: {feat}=yes requires {cap}=yes')


def load_soc(root, selector):
    soc = profile(root, 'soc', selector)
    for group in ('capabilities', 'features'):
        extra = set(soc.get(group, {})) - set(key_order(group))
        if extra:
            raise ValueError(f'{selector}: unknown {group}: {sorted(extra)}')
    validate_deps(soc, selector)
    return soc


def merge(base, patch):
    """Merge objects recursively; null removes a key, arrays replace."""
    result = base.copy() if isinstance(base, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            result[key] = merge(result.get(key), value)
        else:
            result[key] = value
    return result


def compose(root, board):
    data = profile(root, 'board', board)
    validate_deps(data, board)
    soc = merge(load_soc(root, data['soc']), data.get('overrides', {}))
    validate(soc, 'soc', f'{board}: composed soc')
    firmware = data['firmware']
    if firmware['mode'] == 'image':
        if 'profiles' not in soc['kernel'] or 'harvest' not in soc:
            raise ValueError(f'{board}: image mode requires an audited variant registry and harvest list')
        soc_dir = root / soc['soc']
        registry = Path(soc['kernel']['profiles'])
        if registry.is_absolute() or '..' in registry.parts:
            raise ValueError(f'{board}: unsafe variant registry path')
        path = (soc_dir / registry).resolve()
        if not path.is_relative_to(root.resolve().parent):
            raise ValueError(f'{board}: registry resolves outside project')
        variants = load(path)
        variant = firmware['variant']
        if not isinstance(variants, dict) or variant not in variants:
            raise ValueError(f'{board}: unknown kernel variant {variant!r}')
        record = variants[variant]
        if not isinstance(record, dict) or not all(
                isinstance(record.get(key), str) and re.fullmatch('[a-f0-9]{64}', record[key])
                for key in ('image_sha256', 'config_sha256')):
            raise ValueError(f'{board}: missing audited hashes for {variant!r}')
        if data['id'] in variants and variant != data['id']:
            raise ValueError(f'{board}: variant differs from audited target')
    if data['soc'] == 'allwinner/h700':
        for radio in ('wifi', 'bluetooth'):
            state = data.get('network', {}).get(radio)
            if state is None or data['capabilities'][radio] != ('yes' if state else 'no'):
                raise ValueError(f'{board}: network.{radio} must agree with capabilities.{radio}')
    common = {'board': data['id'], 'soc': data['soc'], 'verified': False}
    caps = dict(common, schema='pjos.caps/1', caps=data['capabilities'],
                generated_from='board.json+soc.json')
    features = dict(common, schema='pjos.features/1', features=data['features'],
                    bitmask_version=1, bitmask_order=key_order('features'))
    return {'board': data, 'soc': soc, 'caps': caps, 'features': features}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bsp-root', type=Path, default=PROJECT / 'bsp')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('all', help='validate every SoC and board profile')
    for name in ('board', 'soc', 'compose', 'generate'):
        sub = commands.add_parser(name)
        sub.add_argument('profile', help='profile ID or JSON file path')
        if name == 'generate':
            sub.add_argument('out_dir', type=Path)
    args = parser.parse_args()
    root = args.bsp_root
    try:
        if args.command == 'all':
            boards = sorted(p for p in (root / 'boards').iterdir() if p.is_dir())
            socs = sorted(p for p in root.glob('*/*/soc.json') if p.parent.parent != root / 'boards')
            if not boards or not socs:
                raise ValueError(f'{root}: no boards or SoCs')
            for path in socs:
                load_soc(root, path)
            for path in boards:
                compose(root, path / 'board.json')
        elif args.command == 'soc':
            load_soc(root, args.profile)
        else:
            result = compose(root, args.profile)
            if args.command == 'compose':
                print(json.dumps(result, indent=2))
            elif args.command == 'generate':
                args.out_dir.mkdir(parents=True, exist_ok=True)
                for name, value in result.items():
                    (args.out_dir / f'{name}.json').write_text(json.dumps(value, indent=2) + '\n',
                                                             encoding='utf-8')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')


if __name__ == '__main__':
    main()
