#!/usr/bin/env python3
"""Extract FE6 Chinese HUD pages aligned to the Japanese A-press pages.

The clean JP ROM is Huffman-compressed. The Chinese ROM keeps the same
message table but stores plain GBK text; it may add page breaks of its own.
The JP text's standalone 0x03 controls are the page boundaries the player
advances with A. When the Chinese message has the same number of 0x03
boundaries those pages are used directly; otherwise adjacent Chinese pages
are merged, or a long page is split, so the pack always has that many pages.
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "gba"
JP_PATH = ROOT / "Fire_Emblem_Fuuin_no_Tsurugi_JA.gba"
CN_PATH = ROOT / "Fire_Emblem_Fuuin_no_Tsurugi_CN.gba"
TABLE = 0xF635C
HUF_TABLE = 0xF300C
HUF_ROOT = 0xF6354
PAGE_WAIT = 0x03
LINE_BREAK = 0x01


def decode_huffman(rom: bytes, offset: int, limit: int = 8192) -> bytes:
    out = bytearray()
    node = HUF_ROOT
    pos = offset
    while pos < len(rom) and len(out) < limit:
        cur = rom[pos]
        pos += 1
        left = 8
        while left:
            child = struct.unpack_from("<H", rom, node + (2 if (cur & 1) else 0))[0]
            node = HUF_TABLE + child * 4
            cur >>= 1
            left -= 1
            value = struct.unpack_from("<I", rom, node)[0]
            if value & 0x80000000:
                low = value & 0xFF
                high = (value >> 8) & 0xFF
                if high:
                    out.append(low)
                    out.append(high)
                elif low:
                    out.append(low)
                else:
                    return bytes(out)
                node = HUF_ROOT
    return bytes(out)


def read_entry(rom: bytes, sid: int, compressed: bool) -> bytes:
    pointer = struct.unpack_from("<I", rom, TABLE + sid * 4)[0]
    if not 0x08000000 <= pointer < 0x08000000 + len(rom):
        return b""
    offset = pointer - 0x08000000
    if compressed:
        return decode_huffman(rom, offset)
    return rom[offset:].split(b"\x00", 1)[0]


def split_jp_widths(text: bytes):
    pages = text.split(bytes([PAGE_WAIT]))
    if pages and not pages[-1]:
        pages = pages[:-1]
    if not pages:
        pages = [b""]
    widths = []
    for page in pages:
        i = 0
        width = 0
        while i < len(page):
            b = page[i]
            if 0x80 <= b <= 0x9F or 0xE0 <= b <= 0xEF:
                i += 2
            else:
                i += 1
            width += 1
        widths.append(max(1, width))
    return pages, widths


def clean_cn(text: bytes) -> str:
    kept = bytearray()
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == LINE_BREAK:
            kept.append(0x0A)
            i += 1
        elif ch == 0x10 or ch == 0x80:
            i += 2  # control plus one-byte operand
        elif ch < 0x20:
            i += 1
        else:
            kept.append(ch)
            i += 1
    return kept.decode("gbk", "replace")


def split_to_pages(full: str, widths) -> list[str]:
    full = "\n".join(line.strip() for line in full.split("\n") if line.strip())
    total = sum(widths)
    if len(widths) == 1:
        return [full] if full else []
    pages = []
    start = 0
    for i in range(len(widths) - 1):
        remaining = len(widths) - i
        target = round(len(full) * sum(widths[: i + 1]) / total)
        lo = start + 1
        hi = len(full) - (remaining - 1)
        target = min(max(target, lo), max(lo, hi))
        window = max(2, len(full) // (len(widths) * 4))
        candidates = [
            j for j in range(max(lo, target - window), min(len(full), target + window + 1))
            if j > start and (full[j - 1] in "\n，。、！？；：,.!?;:" or full[j] == "\n")
        ]
        cut = min(candidates, key=lambda j: abs(j - target)) if candidates else target
        cut = min(max(cut, lo), max(lo, hi))
        pages.append(full[start:cut].strip())
        start = cut
    pages.append(full[start:].strip())
    pages = [p if p else "…" for p in pages]
    while len(pages) < len(widths):
        index = max(range(len(pages)), key=lambda k: len(pages[k]))
        page = pages[index]
        if len(page) < 2:
            pages.insert(index + 1, "…")
            continue
        cut = max(1, len(page) // 2)
        pages[index] = page[:cut]
        pages.insert(index + 1, page[cut:])
    return [p for p in pages if p]


def merge_pages(cn_pages: list[str], widths) -> list[str]:
    total = sum(widths)
    n = len(widths)
    out = []
    start = 0
    for i in range(n):
        if i == n - 1:
            end = len(cn_pages)
        else:
            target = round(len(cn_pages) * sum(widths[: i + 1]) / total)
            end = max(start + 1, min(target, len(cn_pages) - (n - i - 1)))
        out.append("\n".join(cn_pages[start:end]).strip())
        start = end
    return out


def main() -> int:
    jp = JP_PATH.read_bytes()
    cn = CN_PATH.read_bytes()
    entries = []
    ids = 0
    skipped = 0
    used_direct = merged = expanded = 0
    for sid in range(0x10000):
        jtext = read_entry(jp, sid, True)
        ctext = read_entry(cn, sid, False)
        if not ctext or not jtext:
            continue
        ids += 1
        jpages, widths = split_jp_widths(jtext)
        raw_pages = ctext.split(bytes([PAGE_WAIT]))
        if raw_pages and not raw_pages[-1]:
            raw_pages = raw_pages[:-1]
        cn_pages = ["\n".join(line for line in clean_cn(p).strip().split("\n") if line.strip()) for p in raw_pages]
        cn_pages = [p for p in cn_pages if p]
        if not cn_pages:
            skipped += 1
            continue
        need = len(jpages)
        if len(cn_pages) == need:
            pages = cn_pages
            used_direct += 1
        elif len(cn_pages) > need:
            pages = merge_pages(cn_pages, widths)
            merged += 1
        else:
            pages = split_to_pages("\n".join(cn_pages), widths)
            expanded += 1
        for index, txt in enumerate(pages):
            if txt:
                entries.append({"source_id": f"{sid:04X}", "page_index": index, "text": txt})
    out = Path(__file__).resolve().parents[1] / "work" / "fe6_text_zh.json" if len(sys.argv) < 2 else Path(sys.argv[1])
    out.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    report = {
        "ids_with_bilingual_text": ids,
        "skipped_empty_cn": skipped,
        "entries": len(entries),
        "direct_pages": used_direct,
        "merged_cn_pages": merged,
        "split_long_page": expanded,
        "max_page": max((e["page_index"] for e in entries), default=0),
        "glyphs": len({c for e in entries for c in e["text"] if c != "\n"}),
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
