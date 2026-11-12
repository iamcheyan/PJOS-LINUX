#!/usr/bin/env python3
"""Compile and execute SYSTEM against a throwaway Linux filesystem fixture."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "src/apply-pocketjs-system-info.py"
ANCHOR = '        ["LANGUAGE"] | ["LANGUAGE", _] => language_command(&fields),\n'

with tempfile.TemporaryDirectory(prefix="system-info-") as directory:
    fixture = Path(directory)
    source = fixture / "engine/guest-rquickjs/src/pocketshell_launcher.rs"
    source.parent.mkdir(parents=True)
    (fixture / "package.json").write_text('{"version":"9.8.7-fixture"}\n')
    (fixture / "contracts/spec").mkdir(parents=True)
    (fixture / "contracts/spec/binding-generation.ts").write_text(
        "export const POCKET_BINDING_GENERATION = 47 as const;\n"
    )
    source.write_text(
        "fn language_command(_: &[&str]) -> String { \"lang\".into() }\n"
        "pub fn command(value: &str) -> String {\n"
        "    let fields: Vec<&str> = value.split('\\t').collect();\n"
        "    match fields.as_slice() {\n"
        + '        ["SYSTEM"] => system_snapshot(),\n'
        + ANCHOR
        + '        _ => "unknown".into(),\n    }\n}\n'
    )

    for path, content in {
        "proc/device-tree/model": "Fixture RG34XX\0",
        "proc/device-tree/compatible": "vendor,fixture\0soc,h700\0",
        "proc/cpuinfo": "processor : 0\nprocessor : 1\n",
        "proc/meminfo": "MemTotal: 1024000 kB\nMemAvailable: 512000 kB\n",
        "proc/stat": "cpu 100 0 20 80 0 0 0 0\n",
        "proc/sys/kernel/hostname": "fixture-host\n",
        "etc/os-release": 'NAME="Fixture OS"\nVERSION="Fixture 42"\nVERSION_ID="42"\n',
        "etc/baseos-release": "BASEOS_BUILD=fixture-build\n",
        "sys/class/thermal/thermal_zone0/temp": "43500\n",
        "sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "1200000\n",
        "sys/class/graphics/fb0/virtual_size": "720,960\n",
        "sys/class/graphics/fb0/modes": "U:720x480p-59\n",
        "sys/class/drm/card0-DSI-1/modes": "720x480\n",
    }.items():
        target = fixture / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    subprocess.run(
        ["python3", str(PATCH), str(source), "--root", str(fixture)],
        check=True,
        capture_output=True,
        text=True,
    )
    source.write_text(source.read_text() + "\nfn keep_after_system_patch() {}\n")
    subprocess.run(
        ["python3", str(PATCH), str(source), "--root", str(fixture)],
        check=True,
        capture_output=True,
        text=True,
    )

    generated = source.read_text()
    assert generated.count('["SYSTEM"] => system_snapshot(),') == 1
    assert generated.count("fn system_snapshot() -> String") == 1
    assert "fn keep_after_system_patch() {}" in generated
    executable = fixture / "system-info-fixture"
    source.write_text(
        'fn run(program: &str, _: &[&str]) -> Option<String> {\n'
        '    match program {\n'
        '        "uname" => Some("fixture-kernel\\n".into()),\n'
        '        "df" => Some("Filesystem 1K-blocks Used Available Use% Mounted on\\n'
        '/dev/test 40000000 10000000 30000000 25% /storage\\n".into()),\n'
        '        _ => None,\n'
        '    }\n}\n'
        + generated
        + '\nfn main() { print!("{}", command("SYSTEM")); }\n'
    )
    compile_result = subprocess.run(["rustc", str(source), "-o", str(executable)], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    output = subprocess.run([str(executable)], check=True, capture_output=True, text=True).stdout
    fields = dict(line.split("\t", 1) for line in output.splitlines())

    expected = {
        "model": "Fixture RG34XX",
        "hardware": "vendor,fixture,soc,h700",
        "cpu": "2 cores",
        "ramTotalKb": "1024000",
        "ramAvailableKb": "512000",
        "ramVariant": "1.0 GB",
        "storageUsed": "9.5 GB",
        "storageTotal": "38.1 GB",
        "storagePercent": "25",
        "os": "Fixture OS Fixture 42",
        "kernel": "fixture-kernel",
        "temperature": "43.5C",
        "frequency": "1200 MHz",
        "display": "720×480",
        "displayBuffer": "720×960",
        "sdk": "9.8.7-fixture",
        "abi": "47",
        "build": "fixture-build",
        "runtime": "9.8.7-fixture · ABI 47 · fixture-build",
    }
    for key, value in expected.items():
        assert fields.get(key) == value, (key, fields.get(key), value)

print("SYSTEM bridge fixture execution passed")
