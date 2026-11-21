#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Verify a Golden Sun RetroBilingual pack against its text source.

Checks the ROM hash gate, entry/page identity, glyph coverage, absence of the
no-translation placeholder, and contiguous page indices. No ROM or dialogue
text is written; only a JSON summary is printed.
"""
import argparse
import json
import struct
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--texts", required=True)
    ap.add_argument("--rom-sha256", required=True)
    ap.add_argument("--allow-notice", action="store_true")
    args = ap.parse_args()

    blob = Path(args.pack).read_bytes()
    texts = json.loads(Path(args.texts).read_text(encoding="utf-8"))["entries"]
    expected = {(e["source_id"].upper(), e["page_index"]): e["text"] for e in texts}

    if blob[:4] != b"RBPK":
        raise SystemExit("bad pack magic")
    version, gw, gh, glyph_count, entry_count = struct.unpack_from("<HHHII", blob, 4)
    if version != 1:
        raise SystemExit("unsupported pack version")
    digest = blob[18:50]
    if digest.hex() != args.rom_sha256:
        raise SystemExit("pack ROM gate does not match --rom-sha256")

    glyph_bytes = (gw * gh + 7) // 8
    off = 50
    codepoints = set()
    for _ in range(glyph_count):
        codepoints.add(struct.unpack_from("<I", blob, off)[0])
        off += 4 + glyph_bytes
    entries = {}
    for _ in range(entry_count):
        tid, page, _flags, first, count = struct.unpack_from("<HBBII", blob, off)
        off += 12
        entries[(f"{tid:04X}", page)] = (first, count)
    indices = struct.unpack_from(f"<{(len(blob) - off) // 2}H", blob, off)

    problems = []
    if set(entries) != set(expected):
        problems.append(f"entry set differs: pack={len(entries)} text={len(expected)}")
    if not args.allow_notice and any(tid == "FFFF" for tid, _ in entries):
        problems.append("pack contains the FFFF no-translation entry")

    pages = {}
    for (sid, page), (first, count) in entries.items():
        pages.setdefault(sid, []).append(page)
        if count == 0:
            problems.append(f"{sid}:{page} has zero glyphs")
        seq = indices[first:first + count]
        for idx in seq:
            if idx != 0xFFFF and idx >= glyph_count:
                problems.append(f"{sid}:{page} references missing glyph {idx}")
    for sid, plist in pages.items():
        if sorted(plist) != list(range(len(plist))):
            problems.append(f"{sid}: non-contiguous pages {sorted(plist)}")

    # Every non-newline character in the source text must have a glyph.
    missing = set()
    for text in expected.values():
        for ch in text:
            if ch != "\n" and ord(ch) not in codepoints:
                missing.add(ch)
    if missing:
        problems.append(f"missing glyphs: {len(missing)}")

    print(json.dumps({
        "pack": str(args.pack),
        "entries": entry_count,
        "glyphs": glyph_count,
        "pages": dict(Counter(p for _, p in entries)),
        "problems": problems,
    }, ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
