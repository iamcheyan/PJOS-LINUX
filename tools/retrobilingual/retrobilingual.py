#!/usr/bin/env python3
"""Offline ROM metadata, translation import, conservative alignment, and review."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).parent))
from tmc_rom import extract_tmc_rom

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rom_versions (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    rom_sha256 TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('ja', 'zh')),
    title TEXT NOT NULL,
    game_code TEXT NOT NULL,
    header_checksum_valid INTEGER NOT NULL CHECK(header_checksum_valid IN (0, 1)),
    PRIMARY KEY(game_id, rom_sha256)
);
CREATE TABLE IF NOT EXISTS text_entries (
    entry_id INTEGER PRIMARY KEY,
    game_id TEXT NOT NULL,
    rom_sha256 TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('ja', 'zh')),
    source_id TEXT NOT NULL,
    context_id TEXT NOT NULL DEFAULT '',
    page_index INTEGER NOT NULL CHECK(page_index >= 0),
    entry_ordinal INTEGER NOT NULL CHECK(entry_ordinal >= 0),
    rom_offset INTEGER,
    script_reference TEXT,
    text TEXT NOT NULL,
    raw_hex TEXT NOT NULL DEFAULT '',
    text_encoding TEXT NOT NULL DEFAULT 'utf-8',
    decode_status TEXT NOT NULL DEFAULT 'decoded',
    controls TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(game_id, rom_sha256) REFERENCES rom_versions(game_id, rom_sha256),
    UNIQUE(game_id, rom_sha256, language, entry_ordinal)
);
CREATE TABLE IF NOT EXISTS context_mappings (
    mapping_id INTEGER PRIMARY KEY,
    game_id TEXT NOT NULL,
    source_rom_hash TEXT NOT NULL,
    source_entry_id INTEGER NOT NULL REFERENCES text_entries(entry_id),
    target_entry_id INTEGER NOT NULL REFERENCES text_entries(entry_id),
    source_text_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    page_index INTEGER NOT NULL,
    japanese_text TEXT NOT NULL,
    chinese_text TEXT NOT NULL,
    match_method TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    review_status TEXT NOT NULL CHECK(review_status IN ('pending', 'approved', 'rejected')),
    UNIQUE(source_entry_id, target_entry_id)
);
CREATE TABLE IF NOT EXISTS translations (
    mapping_id INTEGER PRIMARY KEY REFERENCES context_mappings(mapping_id) ON DELETE CASCADE,
    game_id TEXT NOT NULL,
    source_rom_hash TEXT NOT NULL,
    source_text_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    page_index INTEGER NOT NULL,
    japanese_text TEXT NOT NULL,
    chinese_text TEXT NOT NULL,
    match_method TEXT NOT NULL,
    confidence REAL NOT NULL,
    review_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mapping_reviews (
    review_id INTEGER PRIMARY KEY,
    mapping_id INTEGER NOT NULL REFERENCES context_mappings(mapping_id) ON DELETE CASCADE,
    review_status TEXT NOT NULL CHECK(review_status IN ('approved', 'rejected')),
    note TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_text_lookup
    ON text_entries(game_id, rom_sha256, language, source_id, context_id, page_index);
CREATE INDEX IF NOT EXISTS idx_translation_lookup
    ON translations(game_id, source_rom_hash, source_text_id, context_id, page_index, review_status);
"""


def inspect_rom(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 0xC0:
        raise ValueError("file is shorter than a GBA header (0xC0 bytes)")
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("ROM exceeds the GBA addressable cartridge size")
    title = data[0xA0:0xAC].decode("ascii", "replace").rstrip("\0 ")
    game_code = data[0xAC:0xB0].decode("ascii", "replace")
    maker_code = data[0xB0:0xB2].decode("ascii", "replace")
    expected = (-sum(data[0xA0:0xBD]) - 0x19) & 0xFF
    return {
        "path_name": path.name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "title": title,
        "game_code": game_code,
        "maker_code": maker_code,
        "unit_code": data[0xB2],
        "software_version": data[0xBC],
        "header_checksum": data[0xBD],
        "expected_header_checksum": expected,
        "header_checksum_valid": data[0xBD] == expected,
    }


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def read_export(path: Path, language: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read UTF-8 JSON export {path}: {exc}") from exc
    if document.get("game") != "zelda_minish_cap":
        raise ValueError("export game must be 'zelda_minish_cap'")
    if document.get("language") != language:
        raise ValueError(f"expected language {language!r}")
    digest = document.get("rom_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("rom_sha256 must contain 64 hexadecimal characters")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError("rom_sha256 must be hexadecimal") from exc
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("entries must be an array")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"entries[{index}] must be an object")
        source_id = entry.get("source_id")
        text = entry.get("text")
        context = entry.get("context_id", "")
        page = entry.get("page_index", 0)
        if not isinstance(source_id, str) or not source_id:
            raise ValueError(f"entries[{index}].source_id must be a non-empty string")
        if not isinstance(text, str):
            raise ValueError(f"entries[{index}].text must be a string")
        if not isinstance(context, str) or not isinstance(page, int) or page < 0:
            raise ValueError(f"entries[{index}] has invalid context_id/page_index")
        raw_hex = entry.get("raw_hex", "")
        if not isinstance(raw_hex, str) or len(raw_hex) % 2:
            raise ValueError(f"entries[{index}].raw_hex must be an even-length hexadecimal string")
        try:
            bytes.fromhex(raw_hex)
        except ValueError as exc:
            raise ValueError(f"entries[{index}].raw_hex must be hexadecimal") from exc
        for field in ("text_encoding", "decode_status"):
            if field in entry and not isinstance(entry[field], str):
                raise ValueError(f"entries[{index}].{field} must be a string")
        offset = entry.get("rom_offset")
        if offset is not None and (not isinstance(offset, int) or offset < 0):
            raise ValueError(f"entries[{index}].rom_offset must be null or non-negative")
        reference = entry.get("script_reference")
        if reference is not None and not isinstance(reference, str):
            raise ValueError(f"entries[{index}].script_reference must be null or a string")
        controls = entry.get("controls", [])
        if not isinstance(controls, list) or any(not isinstance(item, str) for item in controls):
            raise ValueError(f"entries[{index}].controls must be an array of strings")
    return document


def import_export(db: sqlite3.Connection, document: dict[str, Any], language: str) -> int:
    digest = document["rom_sha256"].lower()
    metadata = document.get("rom_metadata", {})
    db.execute(
        "INSERT OR IGNORE INTO games(game_id, title) VALUES (?, ?)",
        ("zelda_minish_cap", "The Legend of Zelda: The Minish Cap"),
    )
    db.execute(
        "INSERT INTO rom_versions VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(game_id, rom_sha256) DO UPDATE SET "
        "language=excluded.language, title=excluded.title, game_code=excluded.game_code, "
        "header_checksum_valid=excluded.header_checksum_valid",
        (
            "zelda_minish_cap", digest, language,
            str(metadata.get("title", document.get("rom_title", "unknown"))),
            str(metadata.get("game_code", "????")),
            int(bool(metadata.get("header_checksum_valid", False))),
        ),
    )
    for ordinal, entry in enumerate(document["entries"]):
        db.execute(
            "INSERT INTO text_entries "
            "(game_id, rom_sha256, language, source_id, context_id, page_index, entry_ordinal, rom_offset, script_reference, text, raw_hex, text_encoding, decode_status, controls) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(game_id, rom_sha256, language, entry_ordinal) DO UPDATE SET "
            "source_id=excluded.source_id, context_id=excluded.context_id, page_index=excluded.page_index, "
            "rom_offset=excluded.rom_offset, script_reference=excluded.script_reference, "
            "text=excluded.text, raw_hex=excluded.raw_hex, text_encoding=excluded.text_encoding, "
            "decode_status=excluded.decode_status, controls=excluded.controls",
            (
                "zelda_minish_cap", digest, language, entry["source_id"],
                entry.get("context_id", ""), entry.get("page_index", 0), ordinal,
                entry.get("rom_offset"), entry.get("script_reference"), entry["text"],
                entry.get("raw_hex", ""), entry.get("text_encoding", "utf-8"),
                entry.get("decode_status", "decoded"),
                json.dumps(entry.get("controls", []), ensure_ascii=False),
            ),
        )
    db.commit()
    return len(document["entries"])


def align_documents(japanese: dict[str, Any], chinese: dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
    ja_hash = japanese["rom_sha256"].lower()
    zh_hash = chinese["rom_sha256"].lower()
    import_export(db, japanese, "ja")
    import_export(db, chinese, "zh")
    ja_keys: dict[tuple[str, str, int], int] = defaultdict(int)
    zh_keys: dict[tuple[str, str, int], int] = defaultdict(int)
    for entry in japanese["entries"]:
        ja_keys[(entry["source_id"], entry.get("context_id", ""), entry.get("page_index", 0))] += 1
    for entry in chinese["entries"]:
        zh_keys[(entry["source_id"], entry.get("context_id", ""), entry.get("page_index", 0))] += 1
    candidates = ambiguous = 0
    db.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _retrobilingual_active_pairs ("
        "source_entry_id INTEGER NOT NULL, target_entry_id INTEGER NOT NULL, "
        "PRIMARY KEY(source_entry_id, target_entry_id))"
    )
    db.execute("BEGIN")
    try:
        db.execute("DELETE FROM _retrobilingual_active_pairs")
        for key, ja_count in ja_keys.items():
            zh_count = zh_keys.get(key, 0)
            if not zh_count:
                continue
            if ja_count != 1 or zh_count != 1:
                ambiguous += ja_count
                continue
            ja_rows = db.execute(
                "SELECT entry_id, text FROM text_entries WHERE game_id=? AND rom_sha256=? AND language='ja' AND source_id=? AND context_id=? AND page_index=?",
                ("zelda_minish_cap", ja_hash, *key),
            ).fetchall()
            zh_rows = db.execute(
                "SELECT entry_id, text FROM text_entries WHERE game_id=? AND rom_sha256=? AND language='zh' AND source_id=? AND context_id=? AND page_index=?",
                ("zelda_minish_cap", zh_hash, *key),
            ).fetchall()
            if len(ja_rows) != 1 or len(zh_rows) != 1:
                ambiguous += ja_count
                continue
            ja_row, zh_row = ja_rows[0], zh_rows[0]
            pair = (ja_row[0], zh_row[0])
            db.execute("INSERT INTO _retrobilingual_active_pairs VALUES (?, ?)", pair)
            db.execute(
                "INSERT INTO context_mappings "
                "(game_id, source_rom_hash, source_entry_id, target_entry_id, source_text_id, context_id, page_index, japanese_text, chinese_text, match_method, confidence, review_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_entry_id, target_entry_id) DO UPDATE SET "
                "source_text_id=excluded.source_text_id, context_id=excluded.context_id, page_index=excluded.page_index, "
                "match_method=excluded.match_method, confidence=excluded.confidence, "
                "review_status=CASE WHEN context_mappings.japanese_text != excluded.japanese_text "
                "OR context_mappings.chinese_text != excluded.chinese_text THEN 'pending' "
                "ELSE context_mappings.review_status END, "
                "japanese_text=excluded.japanese_text, chinese_text=excluded.chinese_text",
                (
                    "zelda_minish_cap", ja_hash, ja_row[0], zh_row[0], key[0], key[1], key[2],
                    ja_row[1], zh_row[1], "shared_source_id_context_page", 0.95, "pending",
                ),
            )
            mapping_id, review_status = db.execute(
                "SELECT mapping_id, review_status FROM context_mappings WHERE source_entry_id=? AND target_entry_id=?",
                pair,
            ).fetchone()
            db.execute(
                "INSERT INTO translations "
                "(mapping_id, game_id, source_rom_hash, source_text_id, context_id, page_index, japanese_text, chinese_text, match_method, confidence, review_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(mapping_id) DO UPDATE SET "
                "game_id=excluded.game_id, source_rom_hash=excluded.source_rom_hash, "
                "source_text_id=excluded.source_text_id, context_id=excluded.context_id, page_index=excluded.page_index, "
                "japanese_text=excluded.japanese_text, chinese_text=excluded.chinese_text, "
                "match_method=excluded.match_method, confidence=excluded.confidence, review_status=excluded.review_status",
                (mapping_id, "zelda_minish_cap", ja_hash, key[0], key[1], key[2], ja_row[1], zh_row[1], "shared_source_id_context_page", 0.95, review_status),
            )
            candidates += 1
        db.execute(
            "DELETE FROM context_mappings WHERE source_rom_hash=? "
            "AND target_entry_id IN (SELECT entry_id FROM text_entries WHERE game_id=? AND rom_sha256=? AND language='zh') "
            "AND NOT EXISTS (SELECT 1 FROM _retrobilingual_active_pairs p "
            "WHERE p.source_entry_id=context_mappings.source_entry_id AND p.target_entry_id=context_mappings.target_entry_id)",
            (ja_hash, "zelda_minish_cap", zh_hash),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    total = len(japanese["entries"])
    approved = db.execute(
        "SELECT COUNT(*) FROM context_mappings m JOIN text_entries t ON t.entry_id=m.target_entry_id "
        "WHERE m.source_rom_hash=? AND t.rom_sha256=? AND m.review_status='approved'",
        (ja_hash, zh_hash),
    ).fetchone()[0]
    return {
        "game": "zelda_minish_cap",
        "source_rom_sha256": ja_hash,
        "target_rom_sha256": zh_hash,
        "japanese_entries": total,
        "chinese_entries": len(chinese["entries"]),
        "suggested_matches": candidates,
        "approved_matches": approved,
        "unmatched_japanese": max(0, total - candidates - ambiguous),
        "ambiguous_japanese": ambiguous,
        "match_methods": {"shared_source_id_context_page": candidates},
        "review_required": True,
    }


def command_inspect(args: argparse.Namespace) -> None:
    report = inspect_rom(Path(args.rom))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


def command_extract(args: argparse.Namespace) -> None:
    document = extract_tmc_rom(Path(args.rom), args.language)
    Path(args.output).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "language": args.language,
        "rom_sha256": document["rom_sha256"],
        "categories": document["category_count"],
        "entries": len(document["entries"]),
        "decode_status": "raw_glyph_codes",
        "output": args.output,
    }, ensure_ascii=False))

def command_import(args: argparse.Namespace) -> None:
    document = read_export(Path(args.input), args.language)
    db = connect(Path(args.database))
    count = import_export(db, document, args.language)
    print(json.dumps({"imported": count, "language": args.language, "database": args.database}, ensure_ascii=False))


def command_align(args: argparse.Namespace) -> None:
    ja = read_export(Path(args.japanese), "ja")
    zh = read_export(Path(args.chinese), "zh")
    db = connect(Path(args.database))
    report = align_documents(ja, zh, db)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        Path(args.report).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


def command_review(args: argparse.Namespace) -> None:
    db = connect(Path(args.database))
    row = db.execute("SELECT review_status FROM context_mappings WHERE mapping_id=?", (args.mapping_id,)).fetchone()
    if row is None:
        raise ValueError(f"mapping {args.mapping_id} was not found")
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE context_mappings SET review_status=? WHERE mapping_id=?", (args.status, args.mapping_id))
    db.execute("UPDATE translations SET review_status=? WHERE mapping_id=?", (args.status, args.mapping_id))
    db.execute(
        "INSERT INTO mapping_reviews(mapping_id, review_status, note, reviewed_at) VALUES (?, ?, ?, ?)",
        (args.mapping_id, args.status, args.note, now),
    )
    db.commit()
    print(json.dumps({"mapping_id": args.mapping_id, "previous_status": row[0], "review_status": args.status}, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retrobilingual", description="Offline Minish Cap ROM and translation tools")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="read GBA identity and calculate ROM hashes")
    inspect.add_argument("--rom", required=True)
    inspect.add_argument("--output")
    inspect.set_defaults(function=command_inspect)
    extract = commands.add_parser("extract", help="extract a verified TMC ROM table as raw glyph-coded JSON")
    extract.add_argument("--rom", required=True)
    extract.add_argument("--language", choices=("ja", "zh"), required=True)
    extract.add_argument("--output", required=True)
    extract.set_defaults(function=command_extract)
    importer = commands.add_parser("import", help="import a structured text export into SQLite")
    importer.add_argument("--input", required=True)
    importer.add_argument("--language", choices=("ja", "zh"), required=True)
    importer.add_argument("--database", required=True)
    importer.set_defaults(function=command_import)
    align = commands.add_parser("align", help="suggest only unique exact-ID/context/page matches")
    align.add_argument("--japanese", required=True)
    align.add_argument("--chinese", required=True)
    align.add_argument("--database", required=True)
    align.add_argument("--report")
    align.set_defaults(function=command_align)
    review = commands.add_parser("review", help="approve or reject one suggested mapping")
    review.add_argument("--database", required=True)
    review.add_argument("--mapping-id", required=True, type=int)
    review.add_argument("--status", required=True, choices=("approved", "rejected"))
    review.add_argument("--note", default="")
    review.set_defaults(function=command_review)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.function(args)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(2, f"retrobilingual: error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
