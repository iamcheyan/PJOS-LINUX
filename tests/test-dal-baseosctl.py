#!/usr/bin/env python3
"""Integration tests for the composed profile.env runtime interface."""
import os
from pathlib import Path
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / 'tools' / 'bsp_compose.py'
CTL = ROOT / 'overlay' / 'usr' / 'sbin' / 'baseosctl'


def run(env, *args):
    return subprocess.run([str(CTL), *args], env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix='dal-baseosctl-') as tmp:
        tmp = Path(tmp)
        output = tmp / 'composed'
        subprocess.run(['python3', str(COMPOSE), '--target', 'tg5040', '--output', str(output)],
                       cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        profile_dir = output
        profile = output / 'profile.env'
        require(profile.is_file(), 'composer did not generate profile.env')
        text = profile.read_text()
        require('schema=pjos.dal/1\n' in text, 'unexpected composed DAL schema')
        require('board=tg5040\n' in text and 'soc=allwinner/a133\n' in text,
                'composed identity missing')

        fake = tmp / 'fake'
        sysroot = fake / 'sys'
        devroot = fake / 'dev'
        runroot = fake / 'run'
        battery = sysroot / 'sys/class/power_supply/axp2202-battery'
        charger = sysroot / 'sys/class/power_supply/axp2202-usb'
        led = sysroot / 'sys/class/led/tg5040_exterme_brightness'
        for path, data in ((battery / 'capacity', '79\n'), (battery / 'present', '1\n'),
                           (battery / 'status', 'Discharging\n'), (battery / 'voltage_now', '3980000\n'),
                           (battery / 'health', 'Good\n'), (battery / 'type', 'Battery\n'),
                           (charger / 'online', '1\n'), (charger / 'type', 'USB\n'), (led, '5\n')):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        event = devroot / 'dev/input/event3'
        event.parent.mkdir(parents=True)
        event.touch()
        name = sysroot / 'sys/class/input/event3/device/name'
        name.parent.mkdir(parents=True)
        name.write_text('TRIMUI Player1\n')
        env = os.environ.copy()
        env.update({'DAL_ENV': str(profile), 'DAL_LIB': str(ROOT / 'overlay/usr/lib/baseos/dal.sh'),
                    'DAL_DIR': str(ROOT / 'overlay/usr/lib/baseos/dal'),
                    'PJOS_PROFILE_DIR': str(profile_dir), 'PJOS_SYS_ROOT': str(sysroot),
                    'PJOS_DEV_ROOT': str(devroot), 'PJOS_RUN_ROOT': str(runroot)})

        result = run(env, 'cap', 'get', 'wifi')
        require((result.returncode, result.stdout.strip()) == (0, 'yes'), 'cap get failed')
        cap_json = run(env, '--json', 'cap', 'list')
        parsed = json.loads(cap_json.stdout)
        require(parsed['schema'] == 'pjos.caps/1' and parsed['caps']['wifi'] == 'yes' and
                parsed['caps']['bluetooth'] == 'unknown', 'capability JSON contract failed')
        require(run(env, 'cap', 'has', 'wifi').returncode == 0, 'cap has yes failed')
        require(run(env, 'cap', 'has', 'bluetooth').returncode == 2, 'unknown cap status lost')
        bitmask = run(env, 'feature', 'bitmask')
        require(bitmask.returncode == 0 and 'bitmask=3221225472' in bitmask.stdout and
                'bitmask_version=1' in bitmask.stdout, 'unknown feature bitmask encoding failed')
        require('board=tg5040' in run(env, 'version').stdout, 'version diagnostics missing identity')
        require(run(env, 'input', 'node', 'gamepad').stdout.strip() == '/dev/input/event3',
                'role based input lookup failed')
        h700 = tmp / 'h700'
        subprocess.run(['python3', str(COMPOSE), '--target', 'rg35xxh', '--output', str(h700)],
                       cwd=ROOT, check=True, capture_output=True)
        gpio = tmp / 'gpio'
        helpers = tmp / 'helpers'
        helpers.mkdir()
        marker = tmp / 'action'
        for action in ('reboot', 'poweroff'):
            helper = helpers / f'baseos-{action}'
            helper.write_text('#!/bin/sh\nprintf "%s" "${0##*/}" > "$ACTION_LOG"\n')
            helper.chmod(0o755)
        hook = ROOT / 'bsp/allwinner/h700/overlay/etc/init.d/soc-hw-init'
        hw = env | {'DAL_ENV': str(h700 / 'profile.env'), 'PJOS_PROFILE_DIR': str(h700),
                    'BASEOS_SOC_HOOK': str(hook), 'BASEOS_GPIO_DEBUG': str(gpio),
                    'BASEOS_SBINDIR': str(helpers), 'ACTION_LOG': str(marker)}
        for level, held in [('hi', 'no'), ('lo', 'yes')]:
            gpio.write_text(f' gpio-17 ( |GPIO Key Menu ) in {level}\n')
            result = run(hw, 'input', 'menu-held')
            require((result.returncode, result.stdout.strip()) == (0, f'held={held}'),
                    'vendor GPIO key level lost')
        gpio.write_text('unrelated GPIO\n')
        require(run(hw, 'input', 'menu-held').returncode == 3, 'missing GPIO reported released')
        fake_hook = tmp / 'soc-hook'
        fake_hook.write_text('SOC_ID=allwinner/h700\nsoc_boot_reason() { boot_mode=1; }\n')
        result = run(hw | {'BASEOS_SOC_HOOK': str(fake_hook)}, 'power', 'boot-reason')
        require(result.returncode == 0 and 'reason=charger' in result.stdout, 'boot hook ignored')
        state = sysroot / 'sys/power/state'
        state.parent.mkdir(parents=True)
        state.write_text('freeze mem\n')
        for action in ('poweroff', 'reboot'):
            result = run(hw, 'power', action)
            require(result.returncode == 0 and marker.read_text() == f'baseos-{action}',
                    f'{action} did not use the lifecycle helper')
        usb = runroot / 'run/usb-storage-device'
        usb.parent.mkdir(parents=True, exist_ok=True)
        usb.write_text('active\n')
        require(run(hw, 'power', 'suspend').returncode == 5 and state.read_text() == 'freeze mem\n',
                'suspend not blocked during USB export')
        usb.unlink()
        require(run(hw, 'power', 'suspend').returncode == 0 and state.read_text() == 'mem\n',
                'suspend did not select declared state')
        require(run(hw, 'power', 'alarm', 'set', '1000').returncode == 3,
                'unverified alarm should not write')
        require('/dev/input/' not in run(env, 'input', 'list').stdout and
                '/dev/input/event3' in run(env, 'input', 'list', '--nodes').stdout,
                'input enumeration disclosed or lost diagnostic path')
        (event.parent / 'event4').touch()
        duplicate = name.parents[2] / 'event4/device/name'
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(name.read_text())
        result = run(env, 'input', 'node', 'gamepad')
        require(result.returncode == 3 and not result.stdout, 'duplicate role was guessed')
        version = json.loads(run(env, '--json', 'version').stdout)
        require(version['profile_source'] == str(profile) and version['board'] == 'tg5040',
                'version lost active profile source')
        for args in [('power', 'invalid'), ('power', 'alarm', 'set', '-1'),
                     ('--timeout', '2', 'version'), ('--quiet', 'version'),
                     ('--version', 'ignored')]:
            require(run(env, *args).returncode == 2, f'invalid usage accepted: {args}')
        battery_out = run(env, 'power', 'battery')
        require(battery_out.returncode == 0 and 'capacity=79' in battery_out.stdout and
                'voltage_uv=3980000' in battery_out.stdout, 'dynamic battery query failed')
        charger_out = run(env, 'power', 'charger')
        require(charger_out.returncode == 0 and 'online=1' in charger_out.stdout,
                'dynamic charger query failed')
        supplies = run(env, 'power', 'supplies')
        require('supply=axp2202-battery type=Battery' in supplies.stdout and
                'supply=axp2202-usb type=USB' in supplies.stdout, 'supply enumeration failed')

        result = run(env, 'display', 'get-brightness')
        require((result.returncode, result.stdout.strip()) == (0, '12'),
                f'TG live level must normalize from 5/100, got {result.returncode}: {result.stdout!r}')
        result = run(env, 'display', 'set-brightness', '128')
        require(result.returncode == 0 and led.read_text().strip() == '50',
                'brightness set did not quantize to declared 0..100 hardware range')
        require(run(env, 'display', 'set-brightness', '256').returncode == 2,
                'brightness out-of-range must be usage error')
        led.write_text('5\n')
        require(run(env, 'display', 'blank', 'on', 'manual').returncode == 0 and
                led.read_text().strip() == '0', 'manual blank failed')
        require(run(env, 'display', 'set-brightness', '200').returncode == 0 and
                led.read_text().strip() == '0', 'slider changed visible level while blank')
        require(run(env, 'display', 'blank', 'off', 'idle').returncode == 0 and
                led.read_text().strip() == '0', 'idle call woke manual blank')
        require(run(env, 'display', 'blank', 'toggle', 'manual').returncode == 0 and
                led.read_text().strip() == '78', 'manual toggle did not restore slider-adjusted level')
        require(run(env, 'display', 'blank', 'toggle', 'manual').returncode == 0 and
                led.read_text().strip() == '0', 'repeated toggle failed to blank')
        require(run(env, 'display', 'blank', 'off', 'manual').returncode == 0 and
                led.read_text().strip() == '78', 'manual wake failed')

        malicious = tmp / 'malicious.env'
        malicious.write_text(text + 'display.node=$(touch /tmp/dal-data-execution)\n')
        hostile_env = env | {'DAL_ENV': str(malicious)}
        require(run(hostile_env, 'display', 'info').returncode == 0,
                'data value should remain inert')
        require(not Path('/tmp/dal-data-execution').exists(), 'profile data was executed')
        malformed = tmp / 'malformed.env'
        malformed.write_text('schema=pjos.dal/999\nboard=tg5040\nsoc=allwinner/a133\n')
        require(run(env | {'DAL_ENV': str(malformed)}, 'cap', 'list').returncode == 6,
                'unknown schema must fail closed')

    print('DAL/baseosctl integration: PASS')


if __name__ == '__main__':
    main()
