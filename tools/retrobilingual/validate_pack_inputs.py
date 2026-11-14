#!/usr/bin/env python3
"""Validate that an approved translation JSON can feed retrobilingual.pack."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def approved_rows(db_path: Path, source_hash: str):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT source_text_id, page_index FROM translations"
        " WHERE game_id='zelda_minish_cap' AND review_status='approved'"
        "   AND source_rom_hash=? ORDER BY source_text_id, page_index",
        (source_hash,),
    ).fetchall()
    pending = db.execute(
        "SELECT COUNT(*) FROM translations"
        " WHERE game_id='zelda_minish_cap' AND review_status!='approved'"
        "   AND source_rom_hash=?",
        (source_hash,),
    ).fetchone()[0]
    db.close()
    return rows, pending


def read_texts(path: Path):
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = document.get("entries") if isinstance(document, dict) else document
    if not isinstance(entries, list):
        raise ValueError("texts JSON must be a list or an object with entries")
    result = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"entries[{index}] must be an object")
        sid, page, text = entry.get("source_id"), entry.get("page_index", 0), entry.get("text")
        if not isinstance(sid, str) or not isinstance(page, int) or not isinstance(text, str):
            raise ValueError(f"entries[{index}] needs source_id, page_index, text")
        result[(sid, page)] = text
    return result


def font_coverage(chars, font_path: Path, size: int):
    font = ImageFont.truetype(str(font_path), size)
    missing = []
    for char in sorted(chars):
        image = Image.new("L", (size, size), 0)
        ImageDraw.Draw(image).text((0, 0), char, fill=255, font=font)
        if max(image.getdata()) == 0:
            missing.append(char)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate pack inputs")
    parser.add_argument("--database", required=True)
    parser.add_argument("--texts", required=True)
    parser.add_argument("--source-rom-sha256", required=True)
    parser.add_argument("--font", default=str(Path.home() / "development/pocketshell/app/fonts/SarasaUiSC-Regular.ttf"))
    parser.add_argument("--font-size", type=int, default=12)
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args()

    approved, pending = approved_rows(Path(args.database), args.source_rom_sha256)
    texts = read_texts(Path(args.texts))
    approved_keys = set(approved)
    text_keys = set(texts)
    covered = approved_keys & text_keys
    missing = sorted(approved_keys - text_keys)
    extra = sorted(text_keys - approved_keys)
    chars = {c for key in covered for c in texts[key] if c != "\n"}
    unavailable = font_coverage(chars, Path(args.font), args.font_size) if covered else []

    report = {
        "approved_rows": len(approved),
        "pending_rows": pending,
        "texts_entries": len(texts),
        "covered_approved_rows": len(covered),
        "missing_text_for_approved": [f"{sid}:{page}" for sid, page in missing[:50]],
        "text_without_approval": [f"{sid}:{page}" for sid, page in extra[:50]],
        "unique_characters": len(chars),
        "characters_missing_in_font": unavailable[:50],
        "pack_possible": bool(covered) and not unavailable,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"approved rows: {report['approved_rows']} (pending {pending})")
        print(f"texts entries: {report['texts_entries']}, covered {len(covered)}")
        if missing:
            print(f"missing text for approved: {len(missing)} e.g. {report['missing_text_for_approved'][:5]}")
        if extra:
            print(f"text without approval (ignored): {len(extra)} e.g. {report['text_without_approval'][:5]}")
        if unavailable:
            print(f"characters missing in font: {len(unavailable)} e.g. {''.join(unavailable[:20])}")
        print("pack possible:", report["pack_possible"])
    return 0 if report["pack_possible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
