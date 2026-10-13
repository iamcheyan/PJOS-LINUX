"""Minimal flattened-device-tree reader with same-size in-place value edits.

Only what the boot derivation needs: find one property by node path and
overwrite its value without changing any offset or length in the blob.
"""
from __future__ import annotations

import struct

MAGIC = 0xD00DFEED


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def walk(blob: bytes):
    """Yield (node_path, property, value_offset, value) for every property."""
    require(len(blob) >= 40, "truncated device tree")
    (magic, total, off_struct, off_strings, _reserved, version, compatible, _cpu,
     size_strings, size_struct) = struct.unpack_from(">10I", blob, 0)
    require(magic == MAGIC and version == 17 and compatible == 16, "not a version 17 device tree")
    require(total <= len(blob) and off_struct % 4 == 0 and 40 <= off_struct and
            off_struct + size_struct <= total and off_strings + size_strings <= total,
            "device-tree blocks out of bounds")
    strings = bytes(blob[off_strings:off_strings + size_strings])
    pos, end, stack = off_struct, off_struct + size_struct, []
    while True:
        require(pos + 4 <= end, "device-tree structure overruns its block")
        token, = struct.unpack_from(">I", blob, pos)
        pos += 4
        if token == 1:
            stop = blob.index(b"\0", pos, end)
            stack.append(bytes(blob[pos:stop]).decode("ascii"))
            pos = (stop + 4) & ~3
        elif token == 2:
            require(bool(stack), "unbalanced device tree")
            stack.pop()
        elif token == 3:
            require(bool(stack) and pos + 8 <= end, "device-tree property outside a node")
            length, name = struct.unpack_from(">II", blob, pos)
            pos += 8
            require(pos + length <= end and name < size_strings, "device-tree property out of bounds")
            yield ("/".join(stack) or "/", strings[name:strings.index(b"\0", name)].decode("ascii"),
                   pos, bytes(blob[pos:pos + length]))
            pos = (pos + length + 3) & ~3
        elif token == 9:
            require(not stack, "unbalanced device tree")
            return
        else:
            require(token == 4, f"bad device-tree token {token:#x}")


def find(blob: bytes, node: str, prop: str) -> tuple[int, bytes]:
    """Return (value_offset, value) of `prop` in the only node whose path ends in /`node`."""
    hits = [(at, value) for path, name, at, value in walk(blob) if name == prop and path.endswith("/" + node)]
    require(len(hits) == 1, f"{node}:{prop} matched {len(hits)} device-tree properties")
    return hits[0]


def replace(blob: bytearray, node: str, prop: str, old: bytes, new: bytes) -> int:
    """Overwrite a value that is exactly `old` with same-size `new`; return its offset."""
    at, value = find(blob, node, prop)
    require(value == old, f"{node}:{prop} is {value.hex()}, expected {old.hex()}")
    require(len(new) == len(old), f"{node}:{prop} replacement would move device-tree offsets")
    blob[at:at + len(new)] = new
    require(find(blob, node, prop) == (at, new), f"{node}:{prop} does not read back after the edit")
    return at
