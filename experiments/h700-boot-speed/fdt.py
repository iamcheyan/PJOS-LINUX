"""Minimal flattened-device-tree reader with same-size in-place edits.

Only what the boot-speed experiments need: locate a property by node path and
overwrite its value without changing any offset or length in the blob.
"""
from __future__ import annotations

import struct

MAGIC = 0xD00DFEED


def total_size(blob: bytes) -> int:
    magic, total = struct.unpack_from(">II", blob, 0)
    if magic != MAGIC:
        raise ValueError("not a device tree")
    return total


def walk(blob: bytes):
    """Yield (node_path, property, value_offset, value) for every property."""
    magic, _total, off_struct, off_strings = struct.unpack_from(">4I", blob, 0)
    if magic != MAGIC:
        raise ValueError("not a device tree")
    pos, stack = off_struct, []
    while True:
        token, = struct.unpack_from(">I", blob, pos)
        pos += 4
        if token == 1:
            end = blob.index(b"\0", pos)
            stack.append(blob[pos:end].decode())
            pos = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, name_off = struct.unpack_from(">II", blob, pos)
            pos += 8
            end = blob.index(b"\0", off_strings + name_off)
            name = blob[off_strings + name_off:end].decode()
            yield "/".join(stack) or "/", name, pos, bytes(blob[pos:pos + length])
            pos = (pos + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            return
        else:
            raise ValueError(f"bad device-tree token {token:#x}")


def find(blob: bytes, node: str, prop: str):
    """Return (value_offset, value) for the single node whose path ends with `node`."""
    hits = [(off, value) for path, name, off, value in walk(blob)
            if name == prop and (path == node or path.endswith("/" + node))]
    if len(hits) != 1:
        raise ValueError(f"{node}:{prop} matched {len(hits)} properties")
    return hits[0]


def get(blob: bytes, node: str, prop: str, default=None):
    try:
        return find(blob, node, prop)[1]
    except ValueError:
        return default


def set_same_size(blob: bytearray, node: str, prop: str, value: bytes) -> bytes:
    """Overwrite a property value of identical length; return the old value."""
    off, old = find(bytes(blob), node, prop)
    if len(old) != len(value):
        raise ValueError(f"{node}:{prop} is {len(old)} bytes, replacement is {len(value)}")
    blob[off:off + len(value)] = value
    return old
