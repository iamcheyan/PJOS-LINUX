#!/usr/bin/env python3
"""Execute candidate retries, ARM stack unwind and runtime timing dispatch.

Training success and detected geometry are modeled. Actual upstream rank/width
retry, timeout unwind adapter and timing register writes execute from SRAM.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import unicorn as u
from unicorn import arm_const, arm64_const


def verify(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    native = manifest.get("native_dram", False)
    blob = (directory / ("spl.bin" if native else "probe.bin")).read_bytes()
    sha_key = "spl_sha256" if native else "probe_sha256"
    assert (native or manifest["autodetect"]) and hashlib.sha256(blob).hexdigest() == manifest[sha_key]
    if native:
        symbols = {name: int(address,16) for address,name in re.findall(
            r"^([0-9a-f]+) [a-zA-Z] (\w+)$", (directory / "symbols.txt").read_text(), re.M)}
        arch, R0, PC, SP, LR = u.UC_ARCH_ARM64, arm64_const.UC_ARM64_REG_X0, arm64_const.UC_ARM64_REG_PC, arm64_const.UC_ARM64_REG_SP, arm64_const.UC_ARM64_REG_X30
    else:
        symbols = {name: int(address, 16) for address, name in re.findall(
        r"^\s*([0-9a-f]+)\s+[0-9a-f]+\s+[0-9a-f]+\s+\d+\s+(\w+)\s*$",
        (directory / "probe.map").read_text(), re.M)}
        arch, R0, PC, SP, LR = u.UC_ARCH_ARM, arm_const.UC_ARM_REG_R0, arm_const.UC_ARM_REG_PC, arm_const.UC_ARM_REG_SP, arm_const.UC_ARM_REG_LR
    cases = []
    return_address, stack, params = (0x55ff0, 0x52a00, 0x53000) if native else (0x27ff0, 0x27800, 0x27000)

    def machine():
        m = u.Uc(arch, u.UC_MODE_ARM)
        m.mem_map(0x20000, 0x38000 if native else 0x8000)
        m.mem_map(0x03000000, 0x1000)
        m.mem_map(0x07010000, 0x1000)
        m.mem_map(0x047fb000, 0x2000)
        m.mem_write(0x20000, blob)
        if not native: m.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13)
        m.reg_write(SP, stack)
        m.reg_write(LR, return_address)
        if native and "baseos_dram_power" in symbols:
            m.mem_write(symbols["baseos_dram_power"], struct.pack("<I", 1))
        return m

    def read_word(m, address): return struct.unpack("<I", m.mem_read(address, 4))[0]

    for working_type in sorted(set(manifest["candidate_types"])) + [0]:
        for timeout in (False, True):
            m = machine()
            attempted, outcome, voltages = [], [], []
            def return_value(value):
                m.reg_write(R0, value)
                m.reg_write(PC, m.reg_read(LR))
            def code(uc, address, size, user):
                if address == symbols["mctl_core_init"]:
                    param = uc.reg_read(R0)
                    kind = read_word(uc, param + 4)
                    attempted.append(kind)
                    if timeout and kind != working_type:
                        # The same non-local exit is used by upstream's timeout panic.
                        uc.reg_write(PC, symbols["dram_panic"])
                    else: return_value(int(kind == working_type))
                elif address == symbols["mctl_auto_detect_dram_size"]:
                    uc.mem_write(uc.reg_read(R0 + 1), bytes((10, 15, 1, 1)))
                    return_value(0)
                elif address == symbols["mctl_calc_size"]: return_value(0x40000000)
                elif address == symbols["baseos_set_master_priority"]: return_value(0)
                elif native and address == symbols.get("axp_set_dcdc3"):
                    voltages.append(uc.reg_read(R0))
                    return_value(0)
                elif native and address == symbols.get("udelay"): return_value(0)
                elif address in (symbols["panic"], return_address):
                    outcome.append("failed-all" if address == symbols["panic"] else "selected")
                    uc.emu_stop()
            m.hook_add(u.UC_HOOK_CODE, code)
            m.emu_start(symbols["sunxi_dram_init"], 0x58000 if native else 0x28000, count=100000)
            assert outcome == (["selected"] if working_type else ["failed-all"]), attempted
            tries = read_word(m, symbols["dram_probe_attempts"])
            expected = manifest["candidate_types"].index(working_type) + 1 if working_type else len(manifest["candidate_types"])
            assert tries == expected
            assert read_word(m, symbols["dram_probe_selected_type"]) == working_type
            if working_type:
                assert m.reg_read(SP) == stack and m.reg_read(R0) == 0x40000000
                if native and "trained_vendor_params" in symbols:
                    words = struct.unpack("<32I", m.mem_read(symbols["trained_vendor_params"], 128))
                    assert words[1] == working_type and words[6:8] == (0x30fa, 0x04000000)
            if native and "baseos_dram_power" in symbols:
                assert voltages == [{3: 1500, 7: 1200, 8: 1100}[kind] for kind in manifest["candidate_types"][:tries]]
            cases.append({"working_type": working_type, "timeout_exit": timeout, "attempts": tries,
                          "core_calls": attempted, "outcome": outcome[0], "modeled_voltage_writes_mv": voltages})

    # Execute the real timing register writes, including the mixed-clock RG28XX case.
    timings = []
    for kind in (3, 7, 8):
        for clock in (672, 792):
            m = machine()
            m.mem_write(params, struct.pack("<12I", clock, kind, *([0] * 10)))
            m.reg_write(R0, params)
            visited = []
            def trace(uc, address, size, user):
                for label in ("ddr3", "lpddr3", "lpddr4"):
                    if address == symbols["timing_" + label]: visited.append(label)
                if address == return_address: uc.emu_stop()
            m.hook_add(u.UC_HOOK_CODE, trace)
            m.emu_start(symbols["mctl_set_timing_params"], 0x58000 if native else 0x28000, count=10000)
            assert visited == [{3: "ddr3", 7: "lpddr3", 8: "lpddr4"}[kind]]
            refresh = read_word(m, 0x047fb000 + 0x64)
            # The high half is refresh interval; each upstream timing uses its own division.
            nanoseconds, divisor = {3: (7800, 32), 7: (7800, 64), 8: (3904, 32)}[kind]
            expected = ((nanoseconds * (clock // 2) + 999) // 1000) // divisor
            assert refresh >> 16 == expected, (kind, clock, hex(refresh), expected)
            timings.append({"type": kind, "clock_mhz": clock, "rfshtmg": hex(refresh)})
    report = {sha_key: manifest[sha_key], "native_aarch64": native, "training_modeled": True,
              "geometry_modeled": True, "retry_cases": cases, "timing_cases": timings}
    (directory / "selection-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
