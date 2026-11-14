#!/usr/bin/env python3
"""Build a RetroBilingual runtime pack from approved mappings and UTF-8 text.

The pack contains only:
  * the exact Japanese ROM SHA-256 gate,
  * a 1bpp atlas for characters used by approved translations,
  * per-entry glyph sequences.

No ROM, no complete extracted text and no font file is written to the repo.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MAGIC = b"RBPK"
VERSION = 1
LINE_BREAK = 0xFFFF


def load_texts(path: Path) -> dict[tuple[str, int], str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = document.get("entries") if isinstance(document, dict) else document
    if not isinstance(entries, list):
        raise ValueError("texts JSON must be a list or an object with entries")
    texts: dict[tuple[str, int], str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"texts[{index}] must be an object")
        sid, page, text = entry.get("source_id"), entry.get("page_index", 0), entry.get("text")
        if not isinstance(sid, str) or not isinstance(page, int) or not isinstance(text, str):
            raise ValueError(f"texts[{index}] needs source_id, page_index, text")
        key = (sid, page)
        if key in texts and texts[key] != text:
            raise ValueError(f"conflicting text for {key}")
        texts[key] = text
    return texts


def approved_mappings(db_path: Path, source_hash: str):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT source_text_id, page_index, source_rom_hash FROM translations"
        " WHERE game_id='zelda_minish_cap' AND review_status='approved'"
        "   AND source_rom_hash=? ORDER BY source_text_id, page_index",
        (source_hash,),
    ).fetchall()
    db.close()
    return [(sid, page) for sid, page, _ in rows]


def build_atlas(chars: set[str], font_path: Path, size: int) -> tuple[list[tuple[int, bytes]], dict[int, int]]:
    font = ImageFont.truetype(str(font_path), size)
    bitmap_bytes = (size * size + 7) // 8
    atlas: list[tuple[int, bytes]] = []
    index: dict[int, int] = {}
    for char in sorted(chars):
        codepoint = ord(char)
        if codepoint > 0xFFFF:
            continue
        image = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(image)
        bbox = draw.textbbox((0, 0), char, font=font)
        x = (size - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (size - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), char, fill=255, font=font)
        bits = bytearray(bitmap_bytes)
        pixels = image.load()
        for gy in range(size):
            for gx in range(size):
                if pixels[gx, gy] >= 96:
                    bit = gy * size + gx
                    bits[bit >> 3] |= 0x80 >> (bit & 7)
        index[codepoint] = len(atlas)
        atlas.append((codepoint, bytes(bits)))
    return atlas, index


def build_pack(entries, atlas, index, glyph_size, rom_sha256: bytes) -> bytes:
    out = bytearray()
    out += MAGIC
    out += struct.pack("<HHHII", VERSION, glyph_size, glyph_size, len(atlas), len(entries))
    out += rom_sha256
    for codepoint, bits in atlas:
        out += struct.pack("<I", codepoint) + bits
    sequences: list[list[int]] = []
    table = bytearray()
    for sid, page, text in entries:
        seq: list[int] = []
        for char in text:
            if char == "\n":
                seq.append(LINE_BREAK)
            elif ord(char) in index:
                seq.append(index[ord(char)])
        first = sum(len(s) for s in sequences)
        sequences.append(seq)
        table += struct.pack("<HBBHH", int(sid[:2], 16) << 8 | int(sid[2:4], 16), page, 0, first, len(seq))
    out += table
    for seq in sequences:
        for glyph in seq:
            out += struct.pack("<H", glyph)
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build retrobilingual.pack")
    parser.add_argument("--database", required=True)
    parser.add_argument("--texts", required=True, help="JSON list of {source_id,page_index,text} (UTF-8 Chinese)")
    parser.add_argument("--source-rom-sha256", required=True)
    parser.add_argument("--font", default=str(Path.home() / "development/pocketshell/app/fonts/SarasaUiSC-Regular.ttf"))
    parser.add_argument("--font-size", type=int, default=12)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    digest = bytes.fromhex(args.source_rom_sha256)
    if len(digest) != 32:
        raise SystemExit("source-rom-sha256 must be 32 bytes of hex")
    texts = load_texts(Path(args.texts))
    approved = approved_mappings(Path(args.database), args.source_rom_sha256)
    selected = []
    for sid, page in approved:
        text = texts.get((sid, page))
        if text:
            selected.append((sid, page, text))
    if not selected:
        raise SystemExit("no approved mapping has Unicode text; refusing to build an empty pack")
    notice = "暂无翻译"
    selected.append(("FFFF", 0, notice))
    chars = {c for _, _, text in selected for c in text if c not in "\n"}
    atlas, index = build_atlas(chars, Path(args.font), args.font_size)
    pack = build_pack(selected, atlas, index, args.font_size, digest)
    Path(args.output).write_bytes(pack)
    print(json.dumps({
        "output": args.output,
        "entries": len(selected),
        "glyphs": len(atlas),
        "font": args.font,
        "rom_sha256": args.source_rom_sha256,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
