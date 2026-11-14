#!/usr/bin/env python3
"""match_glyphs.py - Map extracted BZMJ font glyphs to Unicode characters.

Features:
1. Auto-resolves Bank 1 (ASCII letters, numbers, punctuation, common kana).
2. Auto-resolves Bank 3 (GBA game icons and button prompts).
3. Provides a seed table for known Chinese glyphs in Bank 4..7.
4. Reads/Writes data/glyph_mapping.json.
"""

import json
from pathlib import Path

INDEX_PATH = Path("data/glyphs/index.json")
MAPPING_PATH = Path("data/glyph_mapping.json")

# Standard ASCII and basic Latin mapping for Bank 1 (0x20..0x7E)
ASCII_PRINTABLE = {code: chr(code) for code in range(0x20, 0x7F)}

# TMC Kana and Fullwidth Punctuation for Bank 1 (0x80..0xFF)
BANK1_EXTENDED = {
    0x00: "",
    0x20: " ",
    0x21: "!",
    0x22: '"',
    0x27: "'",
    0x28: "(",
    0x29: ")",
    0x2C: ",",
    0x2D: "-",
    0x2E: ".",
    0x3F: "?",
    0x5B: "[",
    0x5D: "]",
    0x5F: "_",
    # Fullwidth / Japanese kana mappings commonly used in TMC
    0x80: "。", 0x81: "「", 0x82: "」", 0x83: "、", 0x84: "・",
    0x85: "ー", 0x86: "…", 0x87: "～", 0x88: "！", 0x89: "？",
    0x8A: "ぁ", 0x8B: "あ", 0x8C: "ぃ", 0x8D: "い", 0x8E: "ぅ",
    0x8F: "う", 0x90: "ぇ", 0x91: "え", 0x92: "ぉ", 0x93: "お",
    0x94: "か", 0x95: "が", 0x96: "き", 0x97: "ぎ", 0x98: "く",
    0x99: "ぐ", 0x9A: "け", 0x9B: "げ", 0x9C: "こ", 0x9D: "ご",
    0x9E: "さ", 0x9F: "ざ", 0xA0: "し", 0xA1: "じ", 0xA2: "す",
    0xA3: "ず", 0xA4: "せ", 0xA5: "ぜ", 0xA6: "そ", 0xA7: "ぞ",
    0xA8: "た", 0xA9: "だ", 0xAA: "ち", 0xAB: "ぢ", 0xAC: "っ",
    0xAD: "つ", 0xAE: "づ", 0xAF: "て", 0xB0: "で", 0xB1: "と",
    0xB2: "ど", 0xB3: "な", 0xB4: "に", 0xB5: "ぬ", 0xB6: "ね",
    0xB7: "の", 0xB8: "は", 0xB9: "ば", 0xBA: "ぱ", 0xBB: "ひ",
    0xBC: "び", 0xBD: "ぴ", 0xBE: "ふ", 0xBF: "ぶ", 0xC0: "ぷ",
    0xC1: "へ", 0xC2: "べ", 0xC3: "ぺ", 0xC4: "ほ", 0xC5: "ぼ",
    0xC6: "ぽ", 0xC7: "ま", 0xC8: "み", 0xC9: "む", 0xCA: "め",
    0xCB: "も", 0xCC: "ゃ", 0xCD: "や", 0xCE: "ゅ", 0xCF: "ゆ",
    0xD0: "ょ", 0xD1: "よ", 0xD2: "ら", 0xD3: "り", 0xD4: "る",
    0xD5: "れ", 0xD6: "ろ", 0xD7: "ゎ", 0xD8: "わ", 0xD9: "を",
    0xDA: "ん",
}

# Bank 3 Button Icons
BANK3_ICONS = {
    0x00: "[DPAD]",
    0x01: "[A]",
    0x02: "[B]",
    0x03: "[L]",
    0x04: "[R]",
    0x05: "[START]",
    0x06: "[SELECT]",
    0x07: "[HEART]",
    0x08: "[RUPEE]",
}

def generate_initial_mapping():
    mapping = {}
    if MAPPING_PATH.exists():
        try:
            with open(MAPPING_PATH, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            print(f"Loaded {len(mapping)} existing mappings from {MAPPING_PATH}")
        except Exception as e:
            print(f"Notice: starting fresh ({e})")

    if not INDEX_PATH.exists():
        print(f"Error: {INDEX_PATH} not found. Run extract_glyphs.py first.")
        return

    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        index_records = json.load(f)

    updated_count = 0
    for record in index_records:
        bank = record["bank"]
        code = record["code"]
        key = f"G{bank}:{code:02X}"

        # If already mapped and non-empty, keep it
        if key in mapping and mapping[key]:
            continue

        resolved = None
        # Auto-map Bank 1 ASCII
        if bank == 1:
            if code in ASCII_PRINTABLE:
                resolved = ASCII_PRINTABLE[code]
            elif code in BANK1_EXTENDED:
                resolved = BANK1_EXTENDED[code]

        # Auto-map Bank 3 Icons
        elif bank == 3:
            if code in BANK3_ICONS:
                resolved = BANK3_ICONS[code]

        if resolved is not None:
            mapping[key] = resolved
            updated_count += 1

    with open(MAPPING_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    print(f"Updated {MAPPING_PATH} with {updated_count} new mappings. Total mapped keys: {len(mapping)}")

if __name__ == "__main__":
    generate_initial_mapping()
