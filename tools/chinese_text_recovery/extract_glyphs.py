#!/usr/bin/env python3
"""extract_glyphs.py - Extract all font glyphs from BZMJ Chinese ROM into PNG images.

Outputs:
  data/glyphs/G{bank}_{code:02X}.png: 16x16 or 8x16 PNG bitmap for each glyph
  data/glyphs/index.json: Full metadata index of all extracted glyphs
"""

import json
import struct
from pathlib import Path
from PIL import Image

ROM_PATH = Path(".orca/drops/塞尔达传说_缩小帽.gba")
OUTPUT_DIR = Path("data/glyphs")

# Verified BZMJ custom font table at 0xDC9F00
FONT_TABLE_ROM_OFFSET = 0xDC9F00

def unpack_block_128(data_64b: bytes) -> list[int]:
    """Replicates UnpackTextNibbles (0x08002724): expands 64 bytes (4bpp) to 128 pixel values."""
    px = []
    for b in data_64b:
        px.append(b & 0xF)
        px.append((b >> 4) & 0xF)
    return px

def extract_all():
    if not ROM_PATH.exists():
        raise FileNotFoundError(f"ROM not found at {ROM_PATH}")

    data = ROM_PATH.read_bytes()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Read font pointers for Banks 0..15
    ptrs = struct.unpack_from("<16I", data, FONT_TABLE_ROM_OFFSET)
    bank_offsets = {i: p - 0x08000000 for i, p in enumerate(ptrs)}

    # Targets across BZMJ font pointer table at 0xDC9F00
    targets = [
        (1, 0, 256, 8, 16, 64),    # Bank 1: 8x16 ASCII / punctuation
        (2, 0, 256, 8, 16, 64),    # Bank 2: 8x16 punctuation / symbols
        (3, 0, 80, 16, 16, 128),   # Bank 3: 16x16 icons
        (4, 0, 256, 16, 16, 128),  # Bank 4: 16x16 Hanzi
        (5, 0, 256, 16, 16, 128),  # Bank 5: 16x16 Hanzi
        (6, 0, 256, 16, 16, 128),  # Bank 6: 16x16 Hanzi
        (7, 0, 256, 16, 16, 128),  # Bank 7: 16x16 Hanzi
        (9, 0, 256, 16, 16, 128),  # Bank 9: 16x16 Extended Hanzi
        (10, 0, 256, 16, 16, 128), # Bank 10: 16x16 Extended Hanzi
        (11, 0, 256, 16, 16, 128), # Bank 11: 16x16 Extended Hanzi
        (12, 0, 256, 16, 16, 128), # Bank 12: 16x16 Extended Hanzi
        (13, 0, 256, 16, 16, 128), # Bank 13: 16x16 Extended Hanzi
        (14, 0, 256, 16, 16, 128), # Bank 14: 16x16 Extended Hanzi
        (15, 0, 256, 16, 16, 128), # Bank 15: 16x16 Extended Hanzi
    ]

    index_records = []
    total_extracted = 0

    for bank, start_code, count, width, height, stride in targets:
        base_off = bank_offsets[bank]
        for code in range(start_code, start_code + count):
            glyph_off = base_off + code * stride
            if glyph_off + stride > len(data):
                continue
            
            raw = data[glyph_off : glyph_off + stride]
            # Check if all zeros
            if not any(raw):
                continue

            # Construct monochrome bitmap
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            pixels = img.load()

            if width == 8 and height == 16:
                unpacked = unpack_block_128(raw[:64])
                for r in range(16):
                    for c in range(8):
                        val = unpacked[r * 8 + c]
                        # 0 and 15 (0xF) are background/margin, 1..14 are stroke
                        if 0 < val < 15:
                            pixels[c, r] = (255, 255, 255, 255)
            else:
                b1 = unpack_block_128(raw[:64])
                b2 = unpack_block_128(raw[64:128])
                for r in range(16):
                    for c in range(8):
                        val1 = b1[r * 8 + c]
                        val2 = b2[r * 8 + c]
                        if 0 < val1 < 15:
                            pixels[c, r] = (255, 255, 255, 255)
                        if 0 < val2 < 15:
                            pixels[c + 8, r] = (255, 255, 255, 255)

            filename = f"G{bank}_{code:02X}.png"
            filepath = OUTPUT_DIR / filename
            img.save(filepath)

            index_records.append({
                "bank": bank,
                "code": code,
                "code_hex": f"{code:02X}",
                "tag": f"[G{bank}:{code:02X}]",
                "width": width,
                "height": height,
                "rom_offset": hex(glyph_off),
                "image_path": str(filepath),
                "unicode": None,
                "confidence": 0.0
            })
            total_extracted += 1

    with open(OUTPUT_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(index_records, f, indent=2, ensure_ascii=False)

    print(f"Extraction complete! Successfully extracted {total_extracted} glyphs into {OUTPUT_DIR}")

if __name__ == "__main__":
    extract_all()
