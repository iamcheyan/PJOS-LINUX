"""Version-gated TMC string-table extraction.

Text glyph bytes are retained as explicit raw tokens until a Unicode mapping is
proven for that ROM. This avoids presenting guessed kana/hanzi as extracted text.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

PROFILES = {
    # TMC JP asset manifest: translation_1_JP starts at ROM file offset 0x9B1A30.
    "16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38": {
        "language": "ja",
        "table_offset": 0x9B1A30,
        "expected_game_code": "BZMJ",
        "expected_category_count": 80,
        "text_encoding": "tmc-jp-glyph-bytecode-raw",
    },
    # This exact device ROM contains a second 80-category TMC table at 0xDCA000.
    "f51c6c2f90e18ee91203dd767307271e06901b5bff35c3a567d52f61a39d166d": {
        "language": "zh",
        "table_offset": 0xDCA000,
        "expected_game_code": "BZMJ",
        "expected_category_count": 80,
        "text_encoding": "tmc-zh-glyph-bytecode-raw",
    },
}


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f"table read outside ROM at 0x{offset:x}")
    return struct.unpack_from("<I", data, offset)[0]


def _glyph_string(raw: bytes) -> list[dict[str, Any]]:
    """Render only known ASCII and explicit glyph/control tokens."""
    entries: list[dict[str, Any]] = []
    display: list[str] = []
    controls: list[str] = []
    page_start = 0
    page_index = 0
    line_breaks = 0
    cursor = 0

    def finish_page(end: int) -> None:
        entries.append({
            "page_index": page_index,
            "text": "".join(display) or "[EMPTY]",
            "raw_hex": raw[page_start:end].hex(),
            "controls": list(controls),
            "page_byte_start": page_start,
        })

    while cursor < len(raw):
        code = raw[cursor]
        start = cursor
        cursor += 1
        if code == 0:
            break
        if code == 0x01:
            controls.append("01")
            display.append("[WAIT]")
            line_breaks += 1
            if line_breaks % 2 == 0:
                finish_page(cursor)
                page_index += 1
                display = []
                controls = []
                page_start = cursor
            continue
        if code == 0x0A:
            display.append("\\n")
            continue
        if code in (0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09):
            needed = {0x02: 1, 0x03: 2, 0x04: 1, 0x05: 1, 0x06: 1, 0x07: 2, 0x08: 1, 0x09: 1}[code]
            if code == 0x04 and cursor < len(raw) and raw[cursor] == 0x10:
                needed = 2
            if code == 0x05 and cursor < len(raw) and raw[cursor] != 0xFF:
                needed = 2
            if cursor + needed > len(raw):
                raise ValueError(f"truncated control 0x{code:02x} at text byte {start}; length={len(raw)} near={raw[max(0, start-4):start+8].hex()}")
            args = raw[cursor:cursor + needed]
            cursor += needed
            control = f"{code:02X}" + "".join(f":{byte:02X}" for byte in args)
            controls.append(control)
            display.append(f"[C{control}]")
            continue
        if code in (0x0B, 0x0C, 0x0D, 0x0E, 0x0F):
            if cursor >= len(raw):
                raise ValueError(f"truncated glyph-bank code 0x{code:02x} at text byte {start}")
            glyph = raw[cursor]
            cursor += 1
            group = {0x0B: 4, 0x0C: 7, 0x0D: 5, 0x0E: 6, 0x0F: 3}[code]
            controls.append(f"{code:02X}:{glyph:02X}")
            display.append(f"[G{group}:{glyph:02X}]")
            continue
        if 0x20 <= code <= 0x7E:
            display.append(chr(code))
        else:
            display.append(f"[G1:{code:02X}]")

    if display or not entries:
        finish_page(len(raw))
    return entries

def _read_encoded_string(data: bytes, start: int, limit: int) -> tuple[bytes, int]:
    cursor = start
    while cursor < limit:
        code = data[cursor]
        cursor += 1
        if code == 0:
            return data[start:cursor - 1], cursor
        needed = {
            0x01: 0, 0x02: 1, 0x03: 2, 0x04: 1, 0x05: 1,
            0x06: 1, 0x07: 2, 0x08: 1, 0x09: 1, 0x0A: 0,
            0x0B: 1, 0x0C: 1, 0x0D: 1, 0x0E: 1, 0x0F: 1,
        }.get(code, 0)
        if code == 0x04 and cursor < limit and data[cursor] == 0x10:
            needed = 2
        if code == 0x05 and cursor < limit and data[cursor] != 0xFF:
            needed = 2
        if cursor + needed > limit:
            raise ValueError(f"truncated TMC token 0x{code:02x} at ROM offset 0x{cursor - 1:x}")
        cursor += needed
    raise ValueError(f"unterminated TMC string at ROM offset 0x{start:x}")


def extract_tmc_rom(path: Path, language: str) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 0xC0 or len(data) > 32 * 1024 * 1024:
        raise ValueError("not a supported-size GBA ROM")
    sha256 = hashlib.sha256(data).hexdigest()
    profile = PROFILES.get(sha256)
    if profile is None:
        code = data[0xAC:0xB0].decode("ascii", "replace")
        raise ValueError(f"no verified {language} text-table profile for SHA-256 {sha256} (game code {code})")
    if profile["language"] != language:
        raise ValueError(f"ROM profile is {profile['language']}, not requested language {language}")
    game_code = data[0xAC:0xB0].decode("ascii", "replace")
    if game_code != profile["expected_game_code"]:
        raise ValueError(f"profile game-code mismatch: expected {profile['expected_game_code']}, found {game_code}")

    table = profile["table_offset"]
    category_table_bytes = _u32(data, table)
    if category_table_bytes == 0 or category_table_bytes % 4 or category_table_bytes > 0x400:
        raise ValueError(f"invalid category table size 0x{category_table_bytes:x}")
    category_count = category_table_bytes // 4
    if category_count != profile["expected_category_count"]:
        raise ValueError(f"expected {profile['expected_category_count']} categories, found {category_count}")
    category_offsets = struct.unpack_from(f"<{category_count}I", data, table)
    if category_offsets[0] != category_table_bytes:
        raise ValueError("category table does not begin immediately after its offset vector")

    entries: list[dict[str, Any]] = []
    for category, relative_category in enumerate(category_offsets):
        category_base = table + relative_category
        next_categories = [offset for offset in category_offsets if offset > relative_category]
        category_limit = table + min(next_categories) if next_categories else len(data)
        if category_base < table + category_table_bytes or category_base + 4 > category_limit:
            raise ValueError(f"invalid category offset 0x{relative_category:x}")
        table_size = _u32(data, category_base)
        if table_size == 0:
            continue
        if table_size % 4 or table_size > 0x2000 or category_base + table_size > category_limit:
            raise ValueError(f"invalid string-offset table for category 0x{category:02x}")
        string_count = table_size // 4
        offsets = struct.unpack_from(f"<{string_count}I", data, category_base)
        if offsets[0] != table_size:
            raise ValueError(f"category 0x{category:02x} does not begin after its offset vector")
        for string_index, relative_string in enumerate(offsets):
            string_start = category_base + relative_string
            if relative_string < table_size or string_start >= category_limit:
                raise ValueError(f"invalid string offset in category 0x{category:02x}, entry 0x{string_index:02x}")
            try:
                raw, _ = _read_encoded_string(data, string_start, len(data))
            except ValueError as exc:
                raise ValueError(f"category 0x{category:02x} entry 0x{string_index:02x} at 0x{string_start:x}: {exc}") from exc
            try:
                pages = _glyph_string(raw)
            except ValueError as exc:
                raise ValueError(f"category 0x{category:02x} entry 0x{string_index:02x} at 0x{string_start:x}: {exc}") from exc
            for page in pages:
                entries.append({
                    "source_id": f"{category:02X}{string_index:02X}",
                    "rom_offset": string_start + page["page_byte_start"],
                    "script_reference": None,
                    "context_id": "",
                    "page_index": page["page_index"],
                    "text": page["text"],
                    "raw_hex": page["raw_hex"],
                    "text_encoding": profile["text_encoding"],
                    "decode_status": "raw_glyph_codes",
                    "controls": page["controls"],
                })
    title = data[0xA0:0xAC].decode("ascii", "replace").rstrip("\0 ")
    return {
        "game": "zelda_minish_cap",
        "language": language,
        "rom_sha256": sha256,
        "rom_title": title,
        "rom_metadata": {
            "title": title,
            "game_code": game_code,
            "header_checksum_valid": data[0xBD] == ((-sum(data[0xA0:0xBD]) - 0x19) & 0xFF),
        },
        "table_offset": profile["table_offset"],
        "category_count": category_count,
        "entries": entries,
    }
