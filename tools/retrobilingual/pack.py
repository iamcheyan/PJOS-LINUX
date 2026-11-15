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


def all_mappings(db_path: Path, source_hash: str):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT source_text_id, page_index, source_rom_hash FROM translations"
        " WHERE game_id='zelda_minish_cap' AND japanese_text != '[EMPTY]'"
        "   AND source_rom_hash=? ORDER BY source_text_id, page_index",
        (source_hash,),
    ).fetchall()
    db.close()
    return [(sid, page) for sid, page, _ in rows]


def wrap_line(line: str, max_chars: int = 15) -> list[str]:
    if len(line) <= max_chars:
        return [line]
    for p in ("，", "、", ",", " ", "！", "？", "!", "?", "。"):
        idx = line[:max_chars].rfind(p)
        if idx >= 6:
            head = line[:idx+1].strip()
            tail = line[idx+1:].strip()
            res = [head]
            if tail:
                res.extend(wrap_line(tail, max_chars))
            return res
    head = line[:max_chars].strip()
    tail = line[max_chars:].strip()
    res = [head]
    if tail:
        res.extend(wrap_line(tail, max_chars))
    return res


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
        table += struct.pack("<HBBII", int(sid[:2], 16) << 8 | int(sid[2:4], 16), page, 0, first, len(seq))
    out += table
    for seq in sequences:
        for glyph in seq:
            out += struct.pack("<H", glyph)
    return bytes(out)


def split_dialogue_pages(text: str) -> list[str]:
    import re
    t = text.replace("\\n", "\n").strip()
    if not t or t == "[EMPTY]":
        return []
    raw_blocks = [b.strip() for b in re.split(r"\n\s*\n+", t) if b.strip()]
    pages = []
    # In GBA TMC, a dialogue window comfortably holds up to 2 lines per page.
    # Only explicit bytecode wait/pause markers (+ or @) force an early single-line page break.
    explicit_page_waits = ("+", "@")
    for block in raw_blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        wrapped_lines = []
        for rl in lines:
            wrapped_lines.extend(wrap_line(rl, 15))

        current_page_lines = []
        for i, line in enumerate(wrapped_lines):
            current_page_lines.append(line)
            # If line explicitly ends with bytecode wait marker, it forces page advance
            if any(line.endswith(w) for w in explicit_page_waits) and i < len(wrapped_lines) - 1:
                pages.append("\n".join(current_page_lines))
                current_page_lines = []
            elif len(current_page_lines) >= 2 and i < len(wrapped_lines) - 1:
                # Dialogue window displays 2 lines at once; advance to next page after 2 lines
                pages.append("\n".join(current_page_lines))
                current_page_lines = []
        if current_page_lines:
            pages.append("\n".join(current_page_lines))
    return pages


def sanitize_text(text: str) -> str:
    import re
    # Convert literal escaped '\n' to actual newline
    t = text.replace("\\n", "\n")
    if re.search(r"\[G\d+:[0-9A-Fa-f]{2}\]", t):
        raise ValueError("unmapped glyph marker in approved pack input")
    # Presentation controls are not glyphs.  Unmapped [G..] was rejected
    # above, so this cleanup cannot silently turn a missing character into a
    # hole in an otherwise approved translation.
    t = re.sub(r"\[[^\]]+\]", "", t)
    # Standardize player name
    t = re.sub(r"\{player\}", "林克", t)
    t = t.replace("{1}", "1")
    # +, @ and empty lines come from the ROM script.  Their visible meaning
    # is not established here, and neither may create a new pack page.
    return t.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build retrobilingual.pack")
    parser.add_argument("--database", required=True)
    parser.add_argument("--texts", required=True, help="JSON list of {source_id,page_index,text} (UTF-8 Chinese)")
    parser.add_argument("--source-rom-sha256", required=True)
    parser.add_argument("--font", default=str(Path.home() / "development/pocketshell/app/fonts/SarasaUiSC-Regular.ttf"))
    parser.add_argument("--font-size", type=int, default=12)
    parser.add_argument("--include-all", action="store_true", help="Include all non-empty translations for 100% coverage")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    digest = bytes.fromhex(args.source_rom_sha256)
    if len(digest) != 32:
        raise SystemExit("source-rom-sha256 must be 32 bytes of hex")
    texts = load_texts(Path(args.texts))
    if args.include_all:
        candidates = all_mappings(Path(args.database), args.source_rom_sha256)
    else:
        candidates = approved_mappings(Path(args.database), args.source_rom_sha256)
    selected = []
    seen = set()
    for sid, page in candidates:
        text = texts.get((sid, page))
        if not text or text == "[EMPTY]":
            continue
        cleaned = sanitize_text(text)
        if cleaned and (sid, page) not in seen:
            # A pack page is the game's dialogue page.  HUD line wrapping is
            # intentionally deferred to the renderer and may not invent a
            # new page_index here.
            selected.append((sid, page, cleaned))
            seen.add((sid, page))
    if not selected:
        raise SystemExit("no approved mapping has Unicode text; refusing to build an empty pack")
    notice = "暂无翻译"
    selected.append(("FFFF", 0, notice))
    selected.sort(key=lambda x: (int(x[0], 16), x[1]))
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
