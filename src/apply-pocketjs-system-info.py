#!/usr/bin/env python3
"""Add the read-only SYSTEM snapshot command to the current PocketJS bridge."""
from __future__ import annotations

import sys
import argparse
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("--root", type=Path, default=Path("/"), help="device root; used by fixture tests")
args = parser.parse_args()
source = args.source
text = source.read_text()

runtime_source = source.parents[3]
try:
    sdk_manifest = json.loads((runtime_source / "package.json").read_text())
    sdk_version = str(sdk_manifest["version"])
    abi_text = (runtime_source / "contracts/spec/binding-generation.ts").read_text()
    abi = re.search(r"POCKET_BINDING_GENERATION\s*=\s*(\d+)", abi_text).group(1)
except (OSError, KeyError, AttributeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"cannot derive PocketJS SDK/ABI from runtime source: {exc}")

arm = '        ["SYSTEM"] => system_snapshot(),\n'
anchor = '        ["LANGUAGE"] | ["LANGUAGE", _] => language_command(&fields),\n'
if arm not in text:
    if text.count(anchor) != 1:
        raise SystemExit(f"SYSTEM command anchor appears {text.count(anchor)} times")
    text = text.replace(anchor, arm + anchor, 1)

helpers = r'''

// BEGIN POCKETSHELL SYSTEM INFO
// Read-only device facts consumed by PocketShell's three System pages.
const SYSTEM_INFO_ROOT: &str = __SYSTEM_INFO_ROOT__;
const SYSTEM_SDK_VERSION: &str = __SYSTEM_SDK_VERSION__;
const SYSTEM_BINDING_ABI: &str = __SYSTEM_BINDING_ABI__;

fn system_path(path: &str) -> std::path::PathBuf {
    std::path::Path::new(SYSTEM_INFO_ROOT).join(path.trim_start_matches('/'))
}

fn system_read(path: &str) -> Option<String> {
    std::fs::read_to_string(system_path(path)).ok().map(|value| value.trim_matches('\0').trim().to_owned())
}

fn system_meminfo_kb(key: &str) -> Option<u64> {
    system_read("/proc/meminfo")?.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        (name == key).then(|| value.split_whitespace().next()?.parse().ok()).flatten()
    })
}

fn system_cpu_percent() -> Option<u32> {
    fn sample() -> Option<(u64, u64)> {
        let line = system_read("/proc/stat")?.lines().next()?.to_owned();
        let values: Vec<u64> = line.split_whitespace().skip(1).map(str::parse).collect::<Result<_, _>>().ok()?;
        if values.len() < 4 { return None; }
        Some((values[3] + values.get(4).copied().unwrap_or(0), values.iter().sum()))
    }
    let (idle0, total0) = sample()?;
    std::thread::sleep(std::time::Duration::from_millis(180));
    let (idle1, total1) = sample()?;
    let total = total1.saturating_sub(total0);
    let idle = idle1.saturating_sub(idle0);
    (total > 0).then(|| (total.saturating_sub(idle) * 100 / total).min(100) as u32)
}

fn system_storage() -> Option<(String, String, u32)> {
    let output = run("df", &["-k", "/storage"])?;
    let fields: Vec<&str> = output.lines().nth(1)?.split_whitespace().collect();
    if fields.len() < 4 { return None; }
    let total: u64 = fields[1].parse().ok()?;
    let used: u64 = fields[2].parse().ok()?;
    if total == 0 { return None; }
    let human = |kb: u64| if kb < 1_048_576 { format!("{} MB", kb / 1024) } else { format!("{:.1} GB", kb as f64 / 1_048_576.0) };
    Some((human(used), human(total), (used * 100 / total).min(100) as u32))
}

fn system_resolution(value: &str) -> Option<String> {
    let bytes = value.trim().as_bytes();
    let separator = bytes.iter().position(|byte| *byte == b'x')?;
    let mut left = separator;
    while left > 0 && bytes[left - 1].is_ascii_digit() { left -= 1; }
    let mut right = separator + 1;
    while right < bytes.len() && bytes[right].is_ascii_digit() { right += 1; }
    if left == separator || right == separator + 1 { return None; }
    let width: u32 = value.trim()[left..separator].parse().ok()?;
    let height: u32 = value.trim()[separator + 1..right].parse().ok()?;
    (width > 0 && height > 0).then(|| format!("{}×{}", width, height))
}

fn system_snapshot() -> String {
    let mut rows = Vec::new();
    let mut push = |key: &str, value: String| rows.push(format!("{}\t{}", key, value));
    let model = system_read("/proc/device-tree/model").unwrap_or_else(|| "Unknown device".into());
    push("model", model);
    let hardware = system_read("/proc/device-tree/compatible").unwrap_or_default().replace('\0', ",").trim_matches(',').to_owned();
    if !hardware.is_empty() { push("hardware", hardware); }
    let cpuinfo = system_read("/proc/cpuinfo").unwrap_or_default();
    let cores = cpuinfo.lines().filter(|line| line.starts_with("processor")).count();
    push("cpu", format!("{} cores", cores.max(1)));
    if let Some(value) = system_cpu_percent() { push("cpuUsagePercent", value.to_string()); }
    if let Some(value) = system_meminfo_kb("MemTotal") { push("ramTotalKb", value.to_string()); }
    if let Some(value) = system_meminfo_kb("MemAvailable") { push("ramAvailableKb", value.to_string()); }
    if let Some(value) = system_meminfo_kb("MemTotal") { push("ramVariant", format!("{:.1} GB", value as f64 / 1_048_576.0)); }
    let release = system_read("/etc/os-release").unwrap_or_default();
    let field = |key: &str| release.lines().find_map(|line| {
        let (name, value) = line.split_once('=')?;
        (name == key).then(|| value.trim_matches('"').to_owned())
    }).unwrap_or_default();
    let name = field("NAME");
    let version = { let value = field("VERSION"); if value.is_empty() { field("VERSION_ID") } else { value } };
    if !name.is_empty() { push("osName", name.clone()); }
    if !version.is_empty() { push("osVersion", version.clone()); }
    let os = format!("{} {}", name, version).trim().to_owned();
    if !os.is_empty() { push("os", os); }
    if let Some(value) = run("uname", &["-r"]) { push("kernel", value.trim().to_owned()); }
    if let Some((used, total, percent)) = system_storage() {
        push("storageUsed", used);
        push("storageTotal", total);
        push("storagePercent", percent.to_string());
    }
    if let Some(value) = system_read("/sys/class/thermal/thermal_zone0/temp").and_then(|v| v.parse::<i64>().ok()) {
        push("temperature", format!("{:.1}C", value as f64 / 1000.0));
    }
    if let Some(value) = system_read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").and_then(|v| v.parse::<u64>().ok()) {
        push("frequency", format!("{} MHz", value / 1000));
    }
    // fb0/modes describes the visible panel mode. virtual_size describes the
    // framebuffer allocation and can include stacked page-flip buffers.
    let mut display_mode = None;
    if let Some(modes) = system_read("/sys/class/graphics/fb0/modes") {
        display_mode = modes.lines().find_map(system_resolution);
    }
    if let Ok(entries) = std::fs::read_dir(system_path("/sys/class/drm")) {
        for entry in entries.flatten().filter(|_| display_mode.is_none()) {
            let Some(name) = entry.file_name().to_str().map(str::to_owned) else { continue };
            let path = format!("/sys/class/drm/{}/modes", name);
            let Some(mode) = system_read(&path) else { continue };
            if let Some(value) = mode.lines().find_map(system_resolution) {
                display_mode = Some(value);
                break;
            }
        }
    }
    let framebuffer = system_read("/sys/class/graphics/fb0/virtual_size");
    if let Some(value) = display_mode { push("display", value); }
    if let Some(value) = framebuffer { push("displayBuffer", value.replace(',', "×")); }
    let runtime = system_read("/etc/baseos-release").unwrap_or_default();
    let release_value = |key: &str| runtime.lines().find_map(|line| line.strip_prefix(&format!("{}=", key)))
        .map(|value| value.trim_matches('"').to_owned()).filter(|value| !value.is_empty());
    let sdk = release_value("PJOS_SDK_VERSION").unwrap_or_else(|| SYSTEM_SDK_VERSION.to_owned());
    let abi = release_value("POCKETJS_ABI").unwrap_or_else(|| SYSTEM_BINDING_ABI.to_owned());
    let build = release_value("BASEOS_BUILD");
    push("sdk", sdk.clone());
    push("abi", abi.clone());
    if let Some(value) = build.as_ref() { push("build", value.clone()); }
    // The row label already says runtime; keep the value inside the 30-column
    // field width instead of clipping the build hash off the panel.
    let identity = match build {
        Some(build) => format!("{} · ABI {} · {}", sdk, abi, build),
        None => format!("{} · ABI {}", sdk, abi),
    };
    push("runtime", identity);
    rows.join("\n")
}
// END POCKETSHELL SYSTEM INFO
'''

helpers = helpers.replace("__SYSTEM_INFO_ROOT__", json.dumps(str(args.root.resolve())))
helpers = helpers.replace("__SYSTEM_SDK_VERSION__", json.dumps(sdk_version))
helpers = helpers.replace("__SYSTEM_BINDING_ABI__", json.dumps(abi))

begin_marker = "// BEGIN POCKETSHELL SYSTEM INFO"
end_marker = "// END POCKETSHELL SYSTEM INFO"
if begin_marker in text:
    start = text.index(begin_marker)
    end = text.index(end_marker, start) + len(end_marker)
    text = text[:start].rstrip() + "\n\n" + text[end:].lstrip()
else:
    # Migrate the earlier version only when its known helper block is the file
    # suffix. If later patches appended code, refuse instead of deleting it.
    legacy = "// Read-only device facts consumed by PocketShell's three System pages."
    if legacy in text:
        start = text.index(legacy)
        suffix = text[start:]
        names = set(re.findall(r"\bfn\s+(\w+)\s*\(", suffix))
        if names != {"system_read", "system_meminfo_kb", "system_cpu_percent", "sample", "system_storage", "system_snapshot"} or not suffix.rstrip().endswith("}"):
            raise SystemExit("legacy SYSTEM block is not an isolated known suffix; refusing to replace")
        text = text[:start].rstrip()
text = text.rstrip() + helpers + "\n"

source.write_text(text)
print("SYSTEM bridge command present:", '"SYSTEM"] => system_snapshot()' in text)
