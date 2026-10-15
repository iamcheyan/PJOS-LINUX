#!/usr/bin/env python3
"""Execute the linked A32 loader, decoder, libfdt and final kernel-call setup."""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

import capstone as c
import unicorn as u
from unicorn import arm_const as a

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fdt


def fnv(data):
    value = 2166136261
    for byte in data: value = (value ^ byte) * 16777619 & 0xffffffff
    return value


def symbols(directory):
    return {name: int(address, 16) for address, name in re.findall(
        r"^\s*([0-9a-f]+)\s+[0-9a-f]+\s+[0-9a-f]+\s+\d+\s+(\w+)(?:\s*=.*)?\s*$",
        (directory / "loader.map").read_text(), re.M)}


def verify(directory, inventory, spl=None, prepared_source=False):
    manifest = json.loads((directory / "manifest.json").read_text())
    inventory_manifest = json.loads((inventory / "inventory.json").read_text())
    serial = "1c00103dc2840671ed3" if prepared_source else inventory_manifest["serial"]
    assert re.fullmatch(r"[0-9a-f]{19}", serial)
    code, image = (directory / "loader.bin").read_bytes(), (directory / "image.bin").read_bytes()
    assert hashlib.sha256(code).hexdigest() == manifest["loader_sha256"]
    assert hashlib.sha256(image).hexdigest() == manifest["image_sha256"]
    expected_kernel = (directory / "kernel.bin").read_bytes()
    assert hashlib.sha256(expected_kernel).hexdigest() == manifest["kernel_sha256"]
    if not manifest.get("kernel_exception_witness"):
        assert manifest["kernel_sha256"] == manifest["source_kernel_sha256"], "clean kernel differs from source"
    if manifest.get("kernel_exception_witness"):
        offset = 0x4098d640 - 0x40080000
        fault_code = (directory / "kernel-fault.bin").read_bytes()
        expected_fault = bytearray(fault_code)
        if manifest.get("kernel_initcall_probe"):
            initcall = (directory / "initcall.bin").read_bytes()
            expected_fault[0x40:0x40 + len(initcall)] = initcall
        assert len(fault_code) == 0x9c0 and expected_kernel[offset:offset + len(fault_code)] == expected_fault
        source = bytearray(expected_kernel[:offset] + bytes(len(fault_code)) + expected_kernel[offset + len(fault_code):])
        if manifest.get("kernel_initcall_probe"):
            struct.pack_into("<I", source, 0x3954, 0xa9b77bfd)
        assert hashlib.sha256(source).hexdigest() == manifest["source_kernel_sha256"]
    sym = symbols(directory)
    words = list(struct.unpack_from("<32I", (inventory / "boot0.bin").read_bytes(), 0x38))
    ram_bytes = (words[7] >> 16) << 20
    assert ram_bytes in (0x40000000, 0x80000000)
    record_version = manifest.get("native_record_version", 1)
    assert record_version in (1, 2)
    record_bytes = 240 if record_version == 2 else 232
    record = bytearray(struct.pack("<4I4QI32I8s3I32s", 0x314e5342, record_version, record_bytes, manifest["model_id"],
                      ram_bytes, 1000, 2000, 3000, words[1], *words, bytes(8), len(image),
                      manifest["image_fnv"], 0, bytes.fromhex(manifest["generation"])))
    if record_version == 2:
        record += struct.pack("<2I", 5, 0)
    struct.pack_into("<I", record, 196, fnv(record))
    if spl:
        spl_manifest = json.loads((spl / "manifest.json").read_text())
        assert spl_manifest["native_loader"] == manifest
        record = bytearray((spl / "native-record.bin").read_bytes())
        assert len(record) == record_bytes
        words = list(struct.unpack_from("<32I", record, 52))
        ram_bytes = struct.unpack_from("<Q", record, 16)[0]
    decoder = c.Cs(c.CS_ARCH_ARM, c.CS_MODE_ARM)
    cp_instructions = {}
    for instruction in decoder.disasm(code[0x1000:sym["baseos_prepare_kernel"] - 0x4a000000], 0x4a001000):
        if instruction.mnemonic in ("mrc", "mcr", "mrrc", "smc"):
            cp_instructions[instruction.address] = instruction

    m = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_ARM)
    m.mem_map(0x40000000, 0x10000000)
    m.mem_map(0x03000000, 0x10000)
    m.mem_map(0x01008000, 0x1000)
    m.mem_map(0x07000000, 0x1000)
    m.mem_write(0x4a000000, code)
    m.mem_write(0x45000000, image)
    m.mem_write(0x4a300000, bytes(record))
    m.mem_write(sym["__bss_start"], b"\xa5" * (sym["__bss_end"] - sym["__bss_start"]))
    sid = (int(serial[:3], 16) << 20, int(serial[3:11], 16), int(serial[11:], 16))
    for offset, value in zip((0x204, 0x208, 0x20c), sid):
        m.mem_write(0x03006000 + offset, struct.pack("<I", value))
    m.reg_write(a.UC_ARM_REG_CPSR, 0x1d3)
    for i in range(13): m.reg_write(a.UC_ARM_REG_R0 + i, 0xdead0000 + i)
    cp = {(0, 1, 0, 0): 0x30c00820, (1, 0, 0, 1): 0x02000023,
          (1, 0, 0, 0): 2 | (3 << 3) | (7 << 13)}
    events, calls, ticks, translations = [], [], [4000], []
    dirty_guard = [None]
    sram_initial = {0x03000000: 0xffffffff, 0x03000004: 0xa5ffffff}
    for address, value in sram_initial.items():
        m.mem_write(address, struct.pack("<I", value))
    sram_writes = []
    prepare_completed = [False]
    prepare_hooks = []

    def prepare_return(machine, pc, size, data):
        assert machine.reg_read(a.UC_ARM_REG_R0) == 0
        prepare_completed[0] = True

    def prepare_entry(machine, pc, size, data):
        address = machine.reg_read(a.UC_ARM_REG_LR)
        prepare_hooks.append(machine.hook_add(u.UC_HOOK_CODE, prepare_return, begin=address, end=address))

    prepare_hooks.append(m.hook_add(u.UC_HOOK_CODE, prepare_entry,
                         begin=sym["baseos_prepare_kernel"], end=sym["baseos_prepare_kernel"]))

    def loader_mmio_write(machine, access, address, size, value, data):
        assert size == 4, (hex(address), size)
        if address in sram_initial:
            assert prepare_completed[0], "SRAM release preceded successful kernel preparation"
            sram_writes.append((address, value))
        else:
            assert manifest["panel_rule"] == 2 and address in (0x0300b090, 0x0300b0ac), \
                ("unexpected loader MMIO write", hex(address), hex(value))

    def forbidden_display_access(machine, access, address, size, value, data):
        raise AssertionError(("loader touched DE/CCU instead of leaving kernel initialization intact",hex(address),access))

    display_hooks = [m.hook_add(u.UC_HOOK_MEM_WRITE, loader_mmio_write, begin=0x03000000, end=0x0300ffff)]
    display_hooks += [m.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, forbidden_display_access,
                                begin=begin,end=end)
                      for begin,end in ((0x03001000, 0x03001fff), (0x01000000, 0x023fffff))]

    def reg(name):
        return {"sb": a.UC_ARM_REG_R9, "sl": a.UC_ARM_REG_R10,
                "fp": a.UC_ARM_REG_R11, "ip": a.UC_ARM_REG_R12}.get(name,
                getattr(a, "UC_ARM_REG_" + name.upper()))

    def cp_step(machine, address, size, data):
        ins = cp_instructions[address]
        if ins.mnemonic == "smc":
            calls.append([machine.reg_read(a.UC_ARM_REG_R0 + i) for i in range(4)])
            machine.emu_stop()
            return
        if ins.mnemonic == "mrrc":
            machine.reg_write(a.UC_ARM_REG_R0, ticks[0])
            machine.reg_write(a.UC_ARM_REG_R1, 0)
            ticks[0] += 1000
        else:
            match = re.fullmatch(r"p15, #(\d+), (\w+), c(\d+), c(\d+), #(\d+)", ins.op_str)
            assert match, ins.op_str
            op1, register, crn, crm, op2 = match.groups()
            key = tuple(map(int, (op1, crn, crm, op2)))
            if ins.mnemonic == "mrc":
                assert key in cp, (address, key)
                machine.reg_write(reg(register), cp[key])
            else:
                value = machine.reg_read(reg(register))
                if key == (0, 1, 0, 0) and value & 1:
                    table = struct.unpack("<4096I", machine.mem_read(0x4a0f8000, 16384))
                    for index, descriptor in enumerate(table):
                        expected = (index << 20) | (0x1c0e if index == 0 or 0x400 <= index < 0x500 else 0x10c16)
                        assert descriptor == expected
                    assert cp[0, 2, 0, 0] == 0x4a0f8000 and cp[0, 2, 0, 2] == 0 and cp[0, 3, 0, 0] == 1
                    translations.append({"entries": len(table), "normal_dram": True, "device_xn_mmio": True})
                    if dirty_guard[0] is not None:
                        machine.hook_del(dirty_guard[0])
                        dirty_guard[0] = None
                cp[key] = value
                events.append({"address": hex(address), "register": list(key), "value": hex(value)})
        machine.reg_write(a.UC_ARM_REG_PC, address + 4)

    for address in cp_instructions: m.hook_add(u.UC_HOOK_CODE, cp_step, begin=address, end=address)
    def before_mmu(machine, access, address, size, value, data):
        assert size == 1 or address % size == 0, (hex(address), size)
    dirty_guard[0] = m.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, before_mmu)
    m.emu_start(0x4a000000, 0x50000000, count=500000000)
    kernel_call_entry = manifest.get("kernel_smc_entry", 0x40080000)
    assert calls == [[0x8000ff04, kernel_call_entry, 0x44000000, 1]], calls
    expected_sram_writes = [(0x03000000,sram_initial[0x03000000] & 0x80000000),
                            (0x03000004,sram_initial[0x03000004] & 0xfeffffff)]
    assert sram_writes == expected_sram_writes, sram_writes
    for hook in display_hooks + prepare_hooks:
        m.hook_del(hook)
    assert not cp[0, 1, 0, 0] & 0x1005
    if "kernel_smc_entry" in manifest:
        from unicorn import arm64_const as x
        witnessed = manifest.get("entry_checksum_witness", False)
        for damaged in ((None, "kernel", "fdt") if witnessed else (None,)):
            probe = u.Uc(u.UC_ARCH_ARM64, u.UC_MODE_ARM)
            probe.mem_map(0x40000000, 0x10000000)
            probe.mem_map(0x07000000, 4096)
            probe.mem_write(0x4a000000, code)
            for address, length in ((0x40080000, len(expected_kernel)), (0x44000000, 0x100000), (0x4a300100, 8)):
                probe.mem_write(address, bytes(m.mem_read(address, length)))
            if damaged:
                address = 0x40080080 if damaged == "kernel" else 0x44000000
                probe.mem_write(address, bytes([probe.mem_read(address, 1)[0] ^ 1]))
            for index, value in enumerate((0x44000000, 0, 0, 0)):
                probe.reg_write(x.UC_ARM64_REG_X0 + index, value)
            probe.hook_add(u.UC_HOOK_CODE, lambda m, pc, size, data: m.emu_stop(), begin=0x40080000, end=0x40080000)
            probe.hook_add(u.UC_HOOK_MEM_WRITE,
                lambda m, access, address, size, value, data: m.emu_stop() if value & 0xffff in (0x9001, 0x9002) else None,
                begin=0x0700013c, end=0x0700013f)
            probe.emu_start(kernel_call_entry, 0x50000000, count=250000000)
            stage = struct.unpack("<I", probe.mem_read(0x0700013c, 4))[0]
            if damaged:
                assert stage == 0x42539001 + int(damaged == "fdt")
            else:
                assert probe.reg_read(x.UC_ARM64_REG_PC) == 0x40080000
                assert [probe.reg_read(x.UC_ARM64_REG_X0 + index) for index in range(4)] == [0x44000000, 0, 0, 0]
                assert stage == (0x42530033 if witnessed else 0x42530031)
                if manifest.get("kernel_exception_witness"):
                    assert probe.reg_read(x.UC_ARM64_REG_VBAR_EL1) == manifest["kernel_fault_vectors"]
                    fault_seen = []
                    def fault_write(machine, access, address, size, value, data):
                        fault_seen.append(value)
                        machine.emu_stop()
                    hook = probe.hook_add(u.UC_HOOK_MEM_WRITE, fault_write, begin=0x0700013c, end=0x0700013f)
                    for vector in range(16):
                        pc = 0x4098d22c if vector % 2 == 0 else 0xffffff8008d40184
                        probe.reg_write(x.UC_ARM64_REG_ELR_EL1, pc)
                        probe.emu_start(manifest["kernel_fault_vectors"] + 128 * vector, 0x50000000, count=100)
                        assert fault_seen[-1] == pc & 0xffffffff
                    probe.hook_del(hook)
        if witnessed:
            (directory / "kernel-entry-check.bin").write_bytes(bytes(m.mem_read(0x4a300100, 8)))
    assert bytes(m.mem_read(0x40080000, len(expected_kernel))) == expected_kernel
    properties = {(path, name): value for path, name, _, value in fdt.walk(bytes(m.mem_read(0x44000000, 0x100000)))}
    assert properties["/chosen", "baseos,native-boot"] == bytes.fromhex(manifest["generation"])
    assert struct.unpack(">2Q", properties["/memory@40000000", "reg"]) == (0x40000000, ram_bytes)
    command = properties["/chosen", "bootargs"].rstrip(b"\0").decode()
    reasons = ("button", "irq", "usb", "charger", "battery", "unknow")
    boot_reason, boot_reason_source = struct.unpack_from("<2I", record, 232) if record_version == 2 else (5, 0)
    assert "bootreason=" + reasons[boot_reason] in command.split()
    assert "androidboot.mode=normal" in command.split()
    assert "androidboot.serialno=" + serial in command.split()
    assert "snum=" + serial in command.split()
    low_panel = "old" if manifest["panel_rule"] == 0 else "boe"
    assert "disp_reserve=" not in command and "lcd_type=" + low_panel in command.split()
    assert ("maxcpus=1" in command.split()) == (manifest.get("diagnostic_maxcpus") == 1)
    assert properties["/soc@03000000/hdmi@06000000", "status"] == b"late\0"
    offset = 2048
    parts = []
    for field in (8, 16, 24, 1632, 1648):
        length = struct.unpack_from("<I", image, field)[0]
        parts.append(image[offset:offset + length])
        offset += (length + 2047) & ~2047
    assert bytes(m.mem_read(0x42000000, len(parts[1]))) == parts[1]
    assert properties["/chosen", "linux,initrd-start"] == struct.pack(">Q", 0x42000000)
    assert properties["/chosen", "linux,initrd-end"] == struct.pack(">Q", 0x42000000 + len(parts[1]))
    reserve = bytes(m.mem_read(0x44000000, 0x100000))
    at = struct.unpack_from(">I", reserve, 16)[0]
    reservations = []
    while True:
        entry = struct.unpack_from(">2Q", reserve, at)
        at += 16
        if entry == (0, 0): break
        reservations.append(entry)
    assert (0x42000000, len(parts[1])) in reservations and (0x48000000, 0x1000000) in reservations
    source_properties = {(path, name): value for path, name, _, value in fdt.walk(parts[4])}
    allowed = {(path, name) for path, name in properties if path == "/dram"}
    allowed |= {("/chosen", name) for name in ("bootargs", "linux,initrd-start", "linux,initrd-end",
                                               "baseos,native-boot", "baseos,native-timing")}
    allowed |= {("/memory@40000000", "reg"), ("/soc@03000000/hdmi@06000000", "status")}
    changed = {key for key in source_properties.keys() | properties.keys() if source_properties.get(key) != properties.get(key)}
    assert changed <= allowed, changed - allowed
    assert all(value == bytes(len(value)) for (path, name), value in properties.items()
               if "/disp@" in path and name.startswith(("boot_disp", "boot_fb")))
    if not prepared_source:
        live_properties = {(path, name): value for path, name, _, value in fdt.walk((inventory / "live.dtb").read_bytes())}
        live_allowed = allowed | {key for key in live_properties if "/disp@" in key[0] and key[1].startswith(("boot_disp", "boot_fb"))}
        live_changed = {key for key in live_properties.keys() | properties.keys() if live_properties.get(key) != properties.get(key)}
        assert live_changed <= live_allowed, live_changed - live_allowed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "variant-survey"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("native_bindings", Path(__file__).resolve().parents[1] / "variant-survey/fdt-contract.py")
    binding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(binding)
    for index, name in enumerate(binding.DRAM_PROPERTIES):
        assert properties["/dram", name] == struct.pack(">I", words[index])
    # Exercise each refusal before decompression; these calls run linked code.
    m.hook_add(u.UC_HOOK_CODE, lambda machine, pc, size, data: machine.emu_stop(), begin=0x4a0d0000, end=0x4a0d0000)
    refusals = []
    def prepare():
        m.reg_write(a.UC_ARM_REG_SP, 0x4a0f0000)
        m.reg_write(a.UC_ARM_REG_LR, 0x4a0d0000)
        m.emu_start(sym["baseos_prepare_kernel"], 0x50000000, count=1000000)
        assert m.reg_read(a.UC_ARM_REG_PC) == 0x4a0d0000
        return m.reg_read(a.UC_ARM_REG_R0)
    for offset, value, expected in ((0, 0, 1), (196, 0, 1)):
        bad = bytearray(record)
        struct.pack_into("<I", bad, offset, value)
        m.mem_write(0x4a300000, bytes(bad))
        assert prepare() == expected
        refusals.append({"record_offset": offset, "error": expected})
    if record_version == 2:
        for offset, value in ((4, 1), (8, 232), (232, 6), (236, 3)):
            bad = bytearray(record)
            struct.pack_into("<I", bad, offset, value)
            struct.pack_into("<I", bad, 196, 0)
            struct.pack_into("<I", bad, 196, fnv(bad))
            m.mem_write(0x4a300000, bytes(bad))
            assert prepare() == 1
            refusals.append({"record_offset": offset, "value": value, "checksum_recomputed": True, "error": 1})
        for reason, source in ((5, 1), (0, 0), (0, 2)):
            bad = bytearray(record)
            struct.pack_into("<2I", bad, 232, reason, source)
            struct.pack_into("<I", bad, 196, 0)
            struct.pack_into("<I", bad, 196, fnv(bad))
            m.mem_write(0x4a300000, bytes(bad))
            assert prepare() == 1
            refusals.append({"boot_reason": reason, "boot_reason_source": source,
                             "checksum_recomputed": True, "error": 1})
    m.mem_write(0x4a300000, bytes(record))
    for offset, value, expected in ((36, 4096, 2), (40, 1, 2), (24, 1, 2),
                                     (1632, 1, 2), (8, 0xffffffff, 3), (16, 0x100001, 3), (1648, 0, 3)):
        m.mem_write(0x45000000 + offset, struct.pack("<I", value))
        assert prepare() == expected
        m.mem_write(0x45000000 + offset, image[offset:offset + 4])
        refusals.append({"image_offset": offset, "error": expected})
    # Both strap outcomes execute the real policy renderer without decoding again.
    panels = []
    for level in (0, 1):
        m.mem_write(0x0300b0a0, struct.pack("<I", level * 0x40))
        m.reg_write(a.UC_ARM_REG_R0, 0x45000000)
        m.reg_write(a.UC_ARM_REG_SP, 0x4a0f0000)
        m.reg_write(a.UC_ARM_REG_LR, 0x4a0d0000)
        m.emu_start(sym["make_command_line"], 0x50000000, count=100000)
        assert m.reg_read(a.UC_ARM_REG_R0) == 0
        text = bytes(m.mem_read(sym["command_line"], 2048)).split(b"\0")[0].decode()
        expected = "old" if manifest["panel_rule"] == 0 or manifest["panel_rule"] == 2 and level else "boe"
        assert "lcd_type=" + expected in text.split()
        panels.append(expected)
    bootreason_cases = []
    if record_version == 2:
        for reason, expected in enumerate(reasons):
            changed_record = bytearray(record)
            struct.pack_into("<2I", changed_record, 232, reason, 0 if reason == 5 else 1)
            m.mem_write(0x4a300000, bytes(changed_record))
            m.reg_write(a.UC_ARM_REG_R0, 0x45000000)
            m.reg_write(a.UC_ARM_REG_SP, 0x4a0f0000)
            m.reg_write(a.UC_ARM_REG_LR, 0x4a0d0000)
            m.emu_start(sym["make_command_line"], 0x50000000, count=100000)
            assert m.reg_read(a.UC_ARM_REG_R0) == 0
            text = bytes(m.mem_read(sym["command_line"], 2048)).split(b"\0")[0].decode()
            assert "bootreason=" + expected in text.split() and "androidboot.mode=normal" in text.split()
            assert "@BOOTREASON@" not in text
            bootreason_cases.append(expected)
        m.mem_write(0x4a300000, bytes(record))
    (directory / "verified-kernel.dtb").write_bytes(bytes(m.mem_read(0x44000000, 0x100000)))
    report = {"passed": True, "loader_sha256": manifest["loader_sha256"],
              "image_sha256": manifest["image_sha256"], "kernel_sha256": hashlib.sha256(expected_kernel).hexdigest(),
              "kernel_bytes_exact": len(expected_kernel), "final_call_r0_r3": list(map(hex, calls[0])),
              "final_a32_sctlr": cp[0, 1, 0, 0], "kernel_smc_entry": kernel_call_entry,
              "translation_checks": translations, "modeled_cp15": events, "bootargs": command,
              "panel_results": panels, "refusals": refusals, "hardware_boot": False,
              "native_record_version": record_version, "native_record_bytes": record_bytes,
              "boot_reason": reasons[boot_reason], "boot_reason_source": boot_reason_source,
              "bootreason_render_cases": bootreason_cases,
              "unchanged_fdt_properties": len(source_properties.keys() - changed),
              "changed_fdt_properties": [list(key) for key in sorted(changed)], "initrd_exact": True,
              "live_fdt_static_properties_exact": not prepared_source,
              "fdt_reference_kind": "prepared-source" if prepared_source else "live-device",
              "sid_model_source": "fixture" if prepared_source else "inventory-serial",
              "serial_modeled": serial,
              "sram_release_writes": [{"address": hex(address), "value": hex(value)}
                                           for address, value in sram_writes],
              "sram_release_after_kernel_preparation": prepare_completed[0],
              "display_register_accesses": 0, "sram_release_unrelated_bits_preserved": True,
              "entry_checksum_witness_verified": manifest.get("entry_checksum_witness", False),
              "kernel_exception_witness_verified": manifest.get("kernel_exception_witness", False),
              "cache_coherency_modeled": False, "vendor_smc_dispatch_verified": False}
    if spl:
        report["spl_sha256"] = spl_manifest["spl_sha256"]
        report["record_sha256"] = hashlib.sha256(record).hexdigest()
    (directory / ("verification-from-spl.json" if spl else "verification.json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "loader_sha256", "kernel_bytes_exact",
                                                  "final_call_r0_r3", "panel_results")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--spl", type=Path)
    parser.add_argument("--prepared-source", action="store_true",
                        help="use the prepared source FDT only; do not claim a live-device comparison")
    args = parser.parse_args()
    verify(args.directory, args.inventory, args.spl, args.prepared_source)
