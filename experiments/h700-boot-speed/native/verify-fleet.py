#!/usr/bin/env python3
"""Generate clean per-model loaders and verify them offline against pinned sources."""
import argparse
import gzip
import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTRACT = HERE.parent / "evidence/compatibility.json"
LIVE_TARGETS = {"rg34xxsp", "rg40xxv"}
FIRMWARE_INPUTS = [
    HERE / name for name in ("build.py", "entry32.S", "loader.c", "runtime.c",
                            "kernel-trace64.S", "check-entry64.c", "kernel-fault64.S",
                            "monitor-probe64.S", "initcall64.S")
] + [HERE.parent / "fastboot/unpack.c"] + [
    HERE.parent / "spl" / name for name in
    ("native-handoff.h", "native-boot.c", "native-cache.c", "native-cache-off.S", "dram-select.c")
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def source_hashes():
    return {str(path.relative_to(ROOT)): file_sha(path) for path in FIRMWARE_INPUTS}


def toc_items(package):
    items = {}
    for index in range(struct.unpack_from("<I", package, 32)[0]):
        at = 64 + index * 368
        name = package[at:at + 64].split(b"\0", 1)[0].decode()
        offset, size = struct.unpack_from("<2I", package, at + 64)
        assert offset + size <= len(package) and name not in items
        items[name] = package[offset:offset + size]
    assert items.keys() == {"u-boot", "monitor", "dtbo", "dtb"}
    return items


def prepared_inputs(target, contract):
    directory = ROOT / "work" / target
    image_path = directory / "boot-prefix.img"
    with image_path.open("rb") as stream:
        prefix = stream.read(1024 * 1024)
        assert prefix[512:520] == b"EFI PART"
        header = bytearray(prefix[512:1024])
        header_size, header_crc = struct.unpack_from("<II", header, 12)
        assert 92 <= header_size <= 512
        struct.pack_into("<I", header, 16, 0)
        assert zlib.crc32(header[:header_size]) == header_crc
        table_lba, count, entry_size = struct.unpack_from("<QII", prefix, 584)
        assert 3 <= count <= 128 and entry_size == 128
        table = prefix[table_lba * 512:table_lba * 512 + count * entry_size]
        assert len(table) == count * entry_size
        assert zlib.crc32(table) == struct.unpack_from("<I", prefix, 600)[0]
        partitions = []
        for index in range(count):
            entry = table[index * entry_size:(index + 1) * entry_size]
            if any(entry[:16]):
                first, last = struct.unpack_from("<QQ", entry, 32)
                partitions.append({"number": index + 1,
                                   "name": entry[56:128].decode("utf-16-le").rstrip("\0"),
                                   "first_lba": first, "last_lba": last})
        env_entry = table[2 * entry_size:3 * entry_size]
        assert env_entry[56:128].decode("utf-16-le").rstrip("\0") == "env"
        env_first, env_last = struct.unpack_from("<QQ", env_entry, 32)
        assert (env_last - env_first + 1) * 512 >= 131072
        stream.seek(env_first * 512)
        env = stream.read(131072)
    assert len(env) == 131072
    assert zlib.crc32(env[4:]) == struct.unpack_from("<I", env)[0]
    boot0 = prefix[8192:8192 + 65536]
    assert sha(boot0) == contract["boot0_sha256"]
    candidates = []
    for candidate in contract["dram_candidates"]:
        offset = int(candidate["offset"], 0)
        words = struct.pack("<32I", *(int(word, 0) for word in candidate["words"]))
        assert boot0[offset:offset + 128] == words
        candidates.append({"offset": candidate["offset"], "type": candidate["type"],
                           "clock_mhz": candidate["clock_mhz"], "sha256": sha(words)})
    return {"source_image": str(image_path.relative_to(ROOT)),
            "source_image_bytes": image_path.stat().st_size,
            "source_image_sha256": file_sha(image_path),
            "extents": {"prefix.bin": {"offset": 0, "bytes": len(prefix), "sha256": sha(prefix)},
                        "boot0.bin": {"offset": 8192, "bytes": len(boot0), "sha256": sha(boot0)},
                        "env.bin": {"offset": env_first * 512, "bytes": len(env), "sha256": sha(env)}},
            "gpt_header_crc_valid": True, "gpt_table_crc_valid": True,
            "environment_crc_valid": True, "partitions": partitions,
            "dram_candidates": candidates}, {
                "prefix.bin": prefix, "boot0.bin": boot0, "env.bin": env}


def inventory_for(target, output, compatibility, resume):
    prepared, data = prepared_inputs(target, compatibility["targets"][target])
    if target in LIVE_TARGETS:
        inventory = ROOT / "work/h700-loader" / (target + "-inventory-v1")
        inventory_path = inventory / "inventory.json"
        lab = next(item for item in compatibility["lab_devices"] if item["target"] == target)
        assert file_sha(inventory_path) == lab["inventory_sha256"]
        live = json.loads(inventory_path.read_text())
        assert live["target"] == target
        for name in ("boot0.bin", "env.bin", "prefix.bin", "live.dtb"):
            actual = (inventory / name).read_bytes()
            assert len(actual) == live["files"][name]["bytes"]
            assert sha(actual) == live["files"][name]["sha256"]
        provenance = {"kind": "live-snapshot", "inventory": str(inventory.relative_to(ROOT)),
                      "inventory_sha256": file_sha(inventory_path),
                      "files": {name: live["files"][name] for name in
                                ("boot0.bin", "env.bin", "prefix.bin", "live.dtb")},
                      "prepared_source": prepared, "new_hardware_observation": False}
    else:
        inventory = output / "inventories" / target
        if not inventory.exists():
            inventory.mkdir(parents=True)
            for name, payload in data.items():
                (inventory / name).write_bytes(payload)
        else:
            assert resume, "existing inventory requires --resume"
            for name, payload in data.items():
                assert (inventory / name).read_bytes() == payload
        assert not (inventory / "live.dtb").exists(), "prepared inventory must not impersonate live FDT"
        provenance = {"kind": "prepared-source", **prepared,
                      "new_hardware_observation": False, "live_fdt_available": False}
        write_json(inventory / "inventory.json", {"target": target, **provenance})
    return inventory, provenance


def check_artifact(target, inventory, directory, contract):
    manifest = json.loads((directory / "manifest.json").read_text())
    source_dir = ROOT / "work" / target / "boot-gzip"
    source_manifest = json.loads((source_dir / "manifest.json").read_text())
    package = (source_dir / "boot-package.bin").read_bytes()
    assert sha(package) == contract["package_sha256"] == source_manifest["package_sha256"]
    toc = toc_items(package)
    original = (source_dir / "boot.img").read_bytes()
    assert sha(original) == source_manifest["boot_image_sha256"]
    assert original[:8] == b"ANDROID!"
    kernel_size, page_size = struct.unpack_from("<I", original, 8)[0], struct.unpack_from("<I", original, 36)[0]
    assert page_size == 2048
    kernel = gzip.decompress(original[page_size:page_size + kernel_size])
    assert (directory / "kernel.bin").read_bytes() == kernel
    assert sha(kernel) == source_manifest["kernel_sha256"] == manifest["source_kernel_sha256"] == manifest["kernel_sha256"]
    monitor = (directory / "monitor.bin").read_bytes()
    assert monitor == toc["monitor"]
    assert sha(monitor) == contract["monitor_sha256"] == manifest["source_monitor_sha256"] == manifest["monitor_sha256"]
    assert manifest["kernel_dtb_sha256"] == sha(toc["dtb"])
    assert manifest["environment_sha256"] == file_sha(inventory / "env.bin")
    assert manifest["target"] == target and manifest["diagnostic_maxcpus"] is None
    for key in ("native_diagnostic", "kernel_probes", "entry_checksum_witness", "kernel_exception_witness",
                "monitor_psci_probe", "kernel_initcall_probe", "durable_install_eligible"):
        assert manifest[key] is False, (target, key)
    assert "kernel_smc_entry" not in manifest
    assert "maxcpus=" not in manifest["bootargs_template"]
    rule = {("old", "old"): 0, ("boe", "boe"): 1, ("old", "boe"): 2}[
        contract["vendor_pe6_lcd_type"]["high"], contract["vendor_pe6_lcd_type"]["low"]]
    assert manifest["panel_rule"] == rule
    firmware = (directory / "firmware.bin").read_bytes()
    assert sha(firmware) == manifest["firmware_sha256"]
    for region in manifest["firmware_regions"]:
        payload = (directory / "loader.bin").read_bytes() if region["name"] == "loader" else toc[region["name"]]
        assert len(payload) == region["bytes"]
        assert firmware[region["offset"]:region["offset"] + region["bytes"]] == payload
    return manifest


def run(command, log):
    with log.open("w") as stream:
        subprocess.run([sys.executable, *map(str, command)], stdout=stream, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target", action="append", help="restrict to named models; default all eleven")
    parser.add_argument("--resume", action="store_true", help="reuse immutable builds after rechecking all source pins")
    args = parser.parse_args()
    output = args.output.resolve()
    assert not output.exists() or args.resume, "use a new output directory or --resume"
    output.mkdir(parents=True, exist_ok=True)
    (output / "logs").mkdir(exist_ok=True)
    compatibility = json.loads(CONTRACT.read_text())
    targets = sorted(args.target or compatibility["targets"])
    assert len(targets) == len(set(targets)) and set(targets) <= compatibility["targets"].keys()
    frozen = source_hashes()
    if args.resume and (output / "fleet.json").is_file():
        previous = json.loads((output / "fleet.json").read_text())
        assert previous["firmware_source_sha256"] == frozen, "cannot resume after firmware source changes"
        assert previous["compatibility_sha256"] == file_sha(CONTRACT), "cannot resume after compatibility changes"
    report = {"passed": False, "scope": "offline clean native-loader generation and host execution",
              "compatibility_sha256": file_sha(CONTRACT), "helper_sha256": file_sha(Path(__file__)),
              "firmware_source_sha256": frozen, "targets": {},
              "hardware_boot": False, "spl_built": False, "dram_training_executed": False,
              "durable_install_eligible": False,
              "unperformed": ["new hardware boots for these generated artifacts", "SPL builds and DRAM training",
                              "SD PIO transport", "cache coherency on hardware", "cold/charger bootreason and RTC protocol qualification"]}
    write_json(output / "fleet.json", report)
    for target in targets:
        assert source_hashes() == frozen, "firmware inputs changed during fleet generation"
        print(json.dumps({"target": target, "stage": "build"}), flush=True)
        inventory, provenance = inventory_for(target, output, compatibility, args.resume)
        directory = output / "loaders" / target
        if not directory.exists():
            run([HERE / "build.py", target, inventory, directory], output / "logs" / (target + ".build.log"))
        else:
            assert args.resume and (directory / "manifest.json").is_file(), "partial build needs a fresh output"
        manifest = check_artifact(target, inventory, directory, compatibility["targets"][target])
        write_json(directory / "provenance.json", provenance)
        verify_args = [HERE / "verify.py", directory, inventory]
        if provenance["kind"] == "prepared-source":
            verify_args.append("--prepared-source")
        print(json.dumps({"target": target, "stage": "A32 decoder/FDT/SMC"}), flush=True)
        run(verify_args, output / "logs" / (target + ".verify.log"))
        proof = json.loads((directory / "verification.json").read_text())
        assert proof["passed"] and proof["loader_sha256"] == manifest["loader_sha256"]
        assert proof["final_call_r0_r3"] == ["0x8000ff04", "0x40080000", "0x44000000", "0x1"]
        if provenance["kind"] == "prepared-source":
            assert proof["live_fdt_static_properties_exact"] is False
            assert proof["fdt_reference_kind"] == "prepared-source"
        else:
            assert proof["live_fdt_static_properties_exact"] is True
        print(json.dumps({"target": target, "stage": "vendor monitor"}), flush=True)
        monitor_path = directory / "monitor-verification.json"
        run([HERE.parent / "spl/verify-monitor.py", ROOT / "work" / target / "boot-gzip/boot-package.bin",
             inventory / "boot0.bin", monitor_path, "--native-loader", directory],
            output / "logs" / (target + ".monitor.log"))
        monitor = json.loads(monitor_path.read_text())
        assert monitor["native_kernel_smc_exception_modeled"] and not monitor["errors"]
        assert monitor["eret"][-1] == {"entry": "0x40080000", "spsr": "0x3c5", "x0": "0x44000000",
                                        "x1": "0x0", "x2": "0x0", "x3": "0x0"}
        report["targets"][target] = {
            "passed": True, "directory": str(directory.relative_to(output)),
            "inventory_kind": provenance["kind"], "generation": manifest["generation"],
            "kernel_sha256": manifest["kernel_sha256"], "monitor_sha256": manifest["monitor_sha256"],
            "kernel_and_monitor_source_bytes_exact": True, "panel_rule": manifest["panel_rule"],
            "panel_gpio_levels_verified": proof["panel_results"],
            "runtime_partition_map": next(word for word in manifest["bootargs_template"].split()
                                          if word.startswith("partitions=")),
            "dram_policy": "loader consumes the trained SPL record; no user DRAM selection",
            "prepared_dram_candidates": provenance.get("prepared_source", provenance)["dram_candidates"],
            "a32_decoder_fdt_smc_verified": True, "vendor_monitor_direct_handoff_verified": True,
            "live_fdt_comparison_performed": proof["live_fdt_static_properties_exact"], "hardware_boot": False}
        write_json(output / "fleet.json", report)
        print(json.dumps({"target": target, "stage": "passed"}), flush=True)
    assert source_hashes() == frozen, "firmware inputs changed during fleet generation"
    report["passed"] = len(report["targets"]) == len(targets)
    report["all_eleven_models"] = set(report["targets"]) == compatibility["targets"].keys()
    report["monitor_families"] = sorted({item["monitor_sha256"] for item in report["targets"].values()})
    write_json(output / "fleet.json", report)
    print(json.dumps({"passed": report["passed"], "models": len(targets),
                      "monitor_families": len(report["monitor_families"]), "hardware_boot": False}), flush=True)


if __name__ == "__main__":
    main()
