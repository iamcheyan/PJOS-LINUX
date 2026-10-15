#!/usr/bin/env python3
"""Generate clean per-model loaders and verify them offline against pinned sources."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTRACT = HERE.parent / "evidence/compatibility.json"
PANEL_CONTRACT = HERE / "panel-contract.json"
LIVE_TARGETS = {"rg34xxsp", "rg40xxv"}
FIRMWARE_INPUTS = [
    HERE / name for name in ("build.py", "entry32.S", "loader.c", "runtime.c",
                            "kernel-trace64.S", "check-entry64.c", "kernel-fault64.S",
                            "monitor-probe64.S", "initcall64.S", "panel-probe.h", "panel-contract.json",
                            "boot-logo-file.h", "boot-logo-pixels.h", "build-display.py", "early-display.c",
                            "display-engine.json", "display-handoff.json", "panel-init.json", "panel-spi9.h")
] + [HERE.parent / "fastboot/unpack.c"] + [
    HERE.parent / "spl" / name for name in
    ("native-handoff.h", "native-logo.h", "native-display.h", "native-boot.c", "native-cache.c", "native-cache-off.S", "dram-select.c")
] + [ROOT / "devices.json", ROOT / "tools/device_profile.py"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def source_hashes():
    return {str(path.relative_to(ROOT)): file_sha(path) for path in FIRMWARE_INPUTS}


def verifier_hashes():
    return {str(path.relative_to(ROOT)): file_sha(path) for path in
            (Path(__file__), HERE / "verify.py", HERE / "verify-kernel-logo.py", HERE / "verify-early-display.py")}


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


def check_artifact(target, inventory, directory, contract, panel):
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
    assert panel["package_sha256"] == sha(package)
    assert panel["vendor_uboot_sha256"] == sha(toc["u-boot"])
    assert (panel["rule"], panel["high"], panel["low"]) == (
        rule, contract["vendor_pe6_lcd_type"]["high"], contract["vendor_pe6_lcd_type"]["low"])
    assert type(panel["pull_up"]) is bool
    assert manifest["panel_contract"] == panel and manifest["panel_pull_up"] is panel["pull_up"]
    generated = (directory / "native-generated.h").read_text()
    assert re.search(rf"^#define BASEOS_PANEL_RULE {rule}$", generated, re.M)
    assert re.search(rf"^#define BASEOS_PANEL_PULL_UP {int(panel['pull_up'])}$", generated, re.M)
    profile_spec = importlib.util.spec_from_file_location("fleet_device_profiles", ROOT / "tools/device_profile.py")
    profiles = importlib.util.module_from_spec(profile_spec)
    profile_spec.loader.exec_module(profiles)
    profile = profiles.get_profile(target)
    prefix = (inventory / "prefix.bin").read_bytes()
    table, count, entry_size = struct.unpack_from("<QII", prefix, 584)
    logo_partitions = []
    for index in range(count):
        entry = prefix[table * 512 + index * entry_size:table * 512 + (index + 1) * entry_size]
        if any(entry[:16]) and entry[56:128].decode("utf-16-le").rstrip("\0") == "boot-resource":
            first, last = struct.unpack_from("<QQ", entry, 32)
            logo_partitions.append((first, last - first + 1))
    assert len(logo_partitions) == 1
    logo = manifest["boot_logo"]
    assert (logo["partition_lba"], logo["partition_sectors"]) == logo_partitions[0]
    assert (logo["width"], logo["height"]) == (profile["bootlogo_width"], profile["bootlogo_height"])
    assert 0 < logo["width"] * logo["height"] * 4 <= 0x400000
    for macro, value in {"BASEOS_LOGO_PARTITION_SECTOR": logo["partition_lba"],
                         "BASEOS_LOGO_PARTITION_SECTORS": logo["partition_sectors"],
                         "BASEOS_LOGO_WIDTH": logo["width"], "BASEOS_LOGO_HEIGHT": logo["height"]}.items():
        assert re.search(rf"^#define {macro} {value}u$", generated, re.M), (target, macro)
    assert (directory / "native-logo.h").read_bytes() == (HERE.parent / "spl/native-logo.h").read_bytes()
    assert (directory / "native-display.h").read_bytes() == (HERE.parent / "spl/native-display.h").read_bytes()
    handoff_contract = json.loads((HERE / "display-handoff.json").read_text())
    assert handoff_contract["version"] == 1
    handoff = handoff_contract["models"][target]
    assert handoff["package_sha256"] == manifest["package_sha256"]
    assert handoff["vendor_uboot_sha256"] == panel["vendor_uboot_sha256"]
    assert manifest["early_display"]["handoff"] == {key: handoff[key] for key in ("boot_disp", "boot_disp1", "boot_disp2")}
    for name in ("boot_disp", "boot_disp1", "boot_disp2"):
        assert re.search(rf"^#define BASEOS_DISPLAY_{name.upper()} 0x{handoff[name]:x}u$", generated, re.M)
    helper_directory = directory / "early-display"
    helper = json.loads((helper_directory / "manifest.json").read_text())
    assert helper == manifest["early_display_helper"]
    assert (helper["target"], helper["generation"], helper["address"]) == (target, manifest["generation"], 0x4a500000)
    assert helper["bytes"] <= 0x40000 and helper["sha256"] == file_sha(helper_directory / "helper.bin")
    assert helper["engine_contract_sha256"] == file_sha(HERE / "display-engine.json")
    assert helper["panel_contract_sha256"] == file_sha(HERE / "panel-init.json")
    assert helper["vendor_dtb_sha256"] == manifest["kernel_dtb_sha256"]
    assert helper["hardware_qualified"] is False
    for name in ("native-logo.h", "native-display.h"):
        assert (helper_directory / name).read_bytes() == (HERE.parent / "spl" / name).read_bytes()
    if "native_generated_header_sha256" in manifest:
        assert file_sha(directory / "native-generated.h") == manifest["native_generated_header_sha256"]
    firmware = (directory / "firmware.bin").read_bytes()
    assert sha(firmware) == manifest["firmware_sha256"]
    assert [(r["name"], r["destination"]) for r in manifest["firmware_regions"]] == [
        ("monitor", 0x48000000), ("dtbo", 0x4a100000), ("dtb", 0x4a200000),
        ("loader", 0x4a000000), ("early-display", 0x4a500000)]
    offset = 0
    for region in manifest["firmware_regions"]:
        payload = ((directory / "loader.bin").read_bytes() if region["name"] == "loader" else
                   (helper_directory / "helper.bin").read_bytes() if region["name"] == "early-display" else toc[region["name"]])
        assert region["offset"] == offset
        assert len(payload) == region["bytes"]
        assert firmware[region["offset"]:region["offset"] + region["bytes"]] == payload
        offset += (len(payload) + 511) & ~511
    assert offset == len(firmware) <= 0x100000
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
    panel_contract = json.loads(PANEL_CONTRACT.read_text())
    assert panel_contract["version"] == 1 and panel_contract["counter_hz"] == 24000000
    assert panel_contract["models"].keys() == compatibility["targets"].keys()
    assert panel_contract["prerequisites"] == {
        "pi_cfg1": "0x300b124", "pi_data": "0x300b130", "power_pin": 15, "reset_pin": 14,
        "power_wait_ms": 30, "reset_levels": [1, 0, 1], "reset_waits_ms": [15, 50, 100],
        "pe_cfg0": "0x300b090", "pe_pull0": "0x300b0ac", "pe_data": "0x300b0a0",
        "detect_pin": 6, "detect_function": 6}
    targets = sorted(args.target or compatibility["targets"])
    assert len(targets) == len(set(targets)) and set(targets) <= compatibility["targets"].keys()
    frozen = source_hashes()
    frozen_verifiers = verifier_hashes()
    if args.resume and (output / "fleet.json").is_file():
        previous = json.loads((output / "fleet.json").read_text())
        assert previous["firmware_source_sha256"] == frozen, "cannot resume after firmware source changes"
        assert previous["compatibility_sha256"] == file_sha(CONTRACT), "cannot resume after compatibility changes"
        assert previous["verification_source_sha256"] == frozen_verifiers, "cannot resume after verifier changes"
    report = {"passed": False, "scope": "offline clean native-loader generation and host execution",
              "compatibility_sha256": file_sha(CONTRACT), "helper_sha256": file_sha(Path(__file__)),
              "panel_contract_sha256": file_sha(PANEL_CONTRACT),
              "firmware_source_sha256": frozen, "targets": {},
              "verification_source_sha256": frozen_verifiers,
              "hardware_boot": False, "spl_built": False, "dram_training_executed": False,
              "durable_install_eligible": False,
              "unperformed": ["new hardware boots for these generated artifacts", "SPL builds and DRAM training",
                              "SD PIO transport", "cache coherency on hardware", "cold/charger bootreason and RTC protocol qualification"]}
    write_json(output / "fleet.json", report)
    for target in targets:
        assert source_hashes() == frozen, "firmware inputs changed during fleet generation"
        assert verifier_hashes() == frozen_verifiers, "verifiers changed during fleet generation"
        print(json.dumps({"target": target, "stage": "build"}), flush=True)
        inventory, provenance = inventory_for(target, output, compatibility, args.resume)
        directory = output / "loaders" / target
        if not directory.exists():
            run([HERE / "build.py", target, inventory, directory], output / "logs" / (target + ".build.log"))
        else:
            assert args.resume and (directory / "manifest.json").is_file(), "partial build needs a fresh output"
        panel = panel_contract["models"][target]
        manifest = check_artifact(target, inventory, directory, compatibility["targets"][target], panel)
        write_json(directory / "provenance.json", provenance)
        verify_args = [HERE / "verify.py", directory, inventory]
        if provenance["kind"] == "prepared-source":
            verify_args.append("--prepared-source")
        print(json.dumps({"target": target, "stage": "actual A64 early-display helper"}), flush=True)
        helper_proof_directory = directory / "early-display/proof"
        helper_proof_path = helper_proof_directory / "verification.json"
        if not helper_proof_path.exists():
            run([HERE / "verify-early-display.py", directory, "--output", helper_proof_directory],
                output / "logs" / (target + ".early-display.log"))
        else:
            assert args.resume, "existing early-display proof requires --resume"
        helper_proof = json.loads(helper_proof_path.read_text())
        assert helper_proof["passed"] and helper_proof["required_cases_complete"]
        assert helper_proof["verifier_sha256"] == file_sha(HERE / "verify-early-display.py")
        assert helper_proof["helper_sha256"] == manifest["early_display_helper"]["sha256"]
        assert helper_proof["generation"] == manifest["generation"]
        assert helper_proof["display_record_sha256"] == file_sha(helper_proof_directory / "display-record.bin")
        assert helper_proof["display_pixels_sha256"] == file_sha(helper_proof_directory / "display-pixels.bin")
        if (helper_proof_directory / "display-source.bmp").exists():
            assert helper_proof["fixture_sha256"] == file_sha(helper_proof_directory / "display-source.bmp")
        print(json.dumps({"target": target, "stage": "A32 decoder/FDT/SMC"}), flush=True)
        run(verify_args, output / "logs" / (target + ".verify.log"))
        proof = json.loads((directory / "verification.json").read_text())
        assert proof["passed"] and proof["loader_sha256"] == manifest["loader_sha256"]
        assert proof["verifier_sha256"] == file_sha(HERE / "verify.py")
        assert proof["final_call_r0_r3"] == ["0x8000ff04", "0x40080000", "0x44000000", "0x1"]
        assert proof["panel_results"] == [panel["low"], panel["high"]]
        expected_writes = 6 + int(panel["pull_up"]) if panel["rule"] == 2 else 0
        assert len(proof["panel_gpio_writes"]) == expected_writes
        assert len(proof["panel_sample_ticks"]) == int(panel["rule"] == 2)
        logo = proof["boot_logo"]
        assert logo["passed"] and logo["linked_symbol"] == "baseos_prepare_logo" and not logo["kernel_decode_repeated"]
        assert logo["missing_logo_main_call_verified"]
        assert logo["fixture_sha256"] == file_sha(ROOT / logo["fixture_path"])
        assert (logo["width"], logo["height"]) == (manifest["boot_logo"]["width"], manifest["boot_logo"]["height"])
        assert logo["prepared_fdt_sha256"] == file_sha(directory / "verified-logo-kernel.dtb")
        assert logo["pixels_sha256"] == file_sha(directory / "logo-pixels.bin")
        assert logo["descriptor_sha256"] == file_sha(directory / "logo-descriptor.bin")
        assert logo["missing_logo_fdt_sha256"] == file_sha(directory / "verified-kernel.dtb")
        assert [sum(case["return_value"] == value for case in logo["cases"]) for value in (0, 1, -1)] == [20, 3, 2]
        assert [(case["name"], case["return_value"]) for case in logo["geometry_cases"]] == [
            ("centered-smaller-odd-stride", 1), ("centered-one-pixel", 1),
            ("bmp-zero-width", 0), ("bmp-negative-width", 0)]
        early = proof["early_display"]
        assert early["passed"] and early["actual_helper_input"] and not early["kernel_decode_repeated"]
        assert early["no_panel_probe_or_reset"] and early["panel_display_mmio_accesses"] == 0
        assert early["helper_proof"]["proof_sha256"] == file_sha(helper_proof_path)
        assert early["display_record_sha256"] == helper_proof["display_record_sha256"]
        assert early["pixels_sha256"] == helper_proof["display_pixels_sha256"]
        assert early["fixture_sha256"] == helper_proof["fixture_sha256"] == file_sha(directory / "early-logo-source.bmp")
        assert early["prepared_fdt_sha256"] == file_sha(directory / "verified-early-logo-kernel.dtb")
        assert early["pixels_sha256"] == file_sha(directory / "early-logo-pixels.bin")
        assert early["display_record_sha256"] == file_sha(directory / "early-display-record.bin")
        if provenance["kind"] == "prepared-source":
            assert proof["live_fdt_static_properties_exact"] is False
            assert proof["fdt_reference_kind"] == "prepared-source"
        else:
            assert proof["live_fdt_static_properties_exact"] is True
        print(json.dumps({"target": target, "stage": "actual logo kernel consumer"}), flush=True)
        logo_consumer_path = directory / "kernel-logo-verification.json"
        if not logo_consumer_path.exists():
            run([HERE / "verify-kernel-logo.py", directory, "--dtb", directory / "verified-logo-kernel.dtb",
                 "--pixels", directory / "logo-pixels.bin", "--output", logo_consumer_path],
                output / "logs" / (target + ".kernel-logo.log"))
        else:
            assert args.resume, "existing logo consumer proof requires --resume"
        consumer = json.loads(logo_consumer_path.read_text())
        assert consumer["passed"] and not consumer["errors"] and len(consumer["cases"]) == 1
        assert consumer["verifier_sha256"] == file_sha(HERE / "verify-kernel-logo.py")
        consumed = consumer["cases"][0]
        assert consumed["input_mode"] == "generated-fdt-and-pixels"
        assert consumed["fdt_sha256"] == logo["prepared_fdt_sha256"]
        assert consumed["source_pixels_sha256"] == consumed["destination_pixels_sha256"] == logo["pixels_sha256"]
        assert consumed["manifest_sha256"] == file_sha(directory / "manifest.json")
        assert consumed["kernel_sha256"] == manifest["kernel_sha256"]
        assert consumed["pixels_copied_exact"] and consumed["source_held_reserved_for_boot"]
        assert consumed["handoff_mode"] == "cold" and consumed["boot_disp_sync"] == 0
        warm_consumer_path = directory / "kernel-early-logo-verification.json"
        if not warm_consumer_path.exists():
            run([HERE / "verify-kernel-logo.py", directory, "--warm", "--dtb", directory / "verified-early-logo-kernel.dtb",
                 "--pixels", directory / "early-logo-pixels.bin", "--output", warm_consumer_path],
                output / "logs" / (target + ".kernel-early-logo.log"))
        else:
            assert args.resume, "existing warm consumer proof requires --resume"
        warm_consumer = json.loads(warm_consumer_path.read_text())
        assert warm_consumer["passed"] and not warm_consumer["errors"] and len(warm_consumer["cases"]) == 1
        assert warm_consumer["verifier_sha256"] == file_sha(HERE / "verify-kernel-logo.py")
        warm = warm_consumer["cases"][0]
        assert warm["handoff_mode"] == "warm" and warm["boot_disp_sync"] == 1
        assert warm["fdt_sha256"] == early["prepared_fdt_sha256"]
        assert warm["source_pixels_sha256"] == warm["destination_pixels_sha256"] == early["pixels_sha256"]
        assert warm["warm_status"]["display_record_sha256"] == early["display_record_sha256"]
        assert warm["warm_status"]["fixture_sha256"] == early["fixture_sha256"]
        assert warm["manifest_sha256"] == file_sha(directory / "manifest.json")
        assert warm["kernel_sha256"] == manifest["kernel_sha256"]
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
            "panel_pull_up": panel["pull_up"], "panel_contract": panel,
            "panel_prerequisite_gpio_timing_verified": panel["rule"] == 2,
            "panel_gpio_levels_verified": proof["panel_results"],
            "boot_logo": {"policy": manifest["boot_logo"], "fixture_path": logo["fixture_path"],
                          "fixture_sha256": logo["fixture_sha256"], "pixels_sha256": logo["pixels_sha256"],
                          "prepared_fdt_sha256": logo["prepared_fdt_sha256"],
                          "descriptor_sha256": logo["descriptor_sha256"],
                          "native_generated_header_sha256": file_sha(directory / "native-generated.h"),
                          "native_logo_header_sha256": file_sha(directory / "native-logo.h"),
                          "producer_report_sha256": file_sha(directory / "verification.json"),
                          "consumer_report_sha256": file_sha(logo_consumer_path),
                          "producer_cases": len(logo["cases"]), "kernel_pixels_copied_exact": True},
            "early_display": {"helper_sha256": manifest["early_display_helper"]["sha256"],
                              "helper_proof_sha256": file_sha(helper_proof_path),
                              "display_record_sha256": early["display_record_sha256"],
                              "prepared_fdt_sha256": early["prepared_fdt_sha256"],
                              "pixels_sha256": early["pixels_sha256"],
                              "producer_cases": len(early["cases"]),
                              "warm_consumer_sha256": file_sha(warm_consumer_path),
                              "warm_kernel_pixels_copied_exact": True,
                              "no_second_panel_probe_or_reset": True},
            "runtime_partition_map": next(word for word in manifest["bootargs_template"].split()
                                          if word.startswith("partitions=")),
            "dram_policy": "loader consumes the trained SPL record; no user DRAM selection",
            "prepared_dram_candidates": provenance.get("prepared_source", provenance)["dram_candidates"],
            "a32_decoder_fdt_smc_verified": True, "vendor_monitor_direct_handoff_verified": True,
            "live_fdt_comparison_performed": proof["live_fdt_static_properties_exact"], "hardware_boot": False}
        write_json(output / "fleet.json", report)
        print(json.dumps({"target": target, "stage": "passed"}), flush=True)
    assert source_hashes() == frozen, "firmware inputs changed during fleet generation"
    assert verifier_hashes() == frozen_verifiers, "verifiers changed during fleet generation"
    report["passed"] = len(report["targets"]) == len(targets)
    report["all_eleven_models"] = set(report["targets"]) == compatibility["targets"].keys()
    report["monitor_families"] = sorted({item["monitor_sha256"] for item in report["targets"].values()})
    write_json(output / "fleet.json", report)
    print(json.dumps({"passed": report["passed"], "models": len(targets),
                      "monitor_families": len(report["monitor_families"]), "hardware_boot": False}), flush=True)


if __name__ == "__main__":
    main()
