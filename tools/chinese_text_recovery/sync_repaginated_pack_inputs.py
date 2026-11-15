#!/usr/bin/env python3
"""Synchronize repaginated approved rows into a pack database and JSON input."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def approved_entries(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        text = str(row.get("chinese", ""))
        if row.get("status") != "approved" or not text or text == "[EMPTY]" or "[G" in text:
            continue
        result.append({
            "source_id": str(row["source_id"]).upper(),
            "page_index": int(row.get("page_index", 0)),
            "text": text,
        })
    return sorted(result, key=lambda entry: (int(entry["source_id"], 16), entry["page_index"]))


def sync_pack_inputs(database: Path, rows: list[dict], source_hash: str, output: Path) -> dict:
    selected = approved_entries(rows)
    connection = sqlite3.connect(database)
    try:
        with connection:
            connection.execute(
                "UPDATE translations SET review_status='pending'"
                " WHERE game_id='zelda_minish_cap' AND source_rom_hash=?",
                (source_hash,),
            )
            missing = []
            for entry in selected:
                cursor = connection.execute(
                    "UPDATE translations SET review_status='approved'"
                    " WHERE game_id='zelda_minish_cap' AND source_rom_hash=?"
                    " AND source_text_id=? AND page_index=?",
                    (source_hash, entry["source_id"], entry["page_index"]),
                )
                if cursor.rowcount != 1:
                    missing.append(f"{entry['source_id']}:{entry['page_index']}")
            if missing:
                raise ValueError("approved alignment rows missing from database: " + ", ".join(missing[:20]))
    finally:
        connection.close()

    output.write_text(json.dumps({"entries": selected}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"approved_rows": len(selected), "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync repaginated approved translations for pack.py")
    parser.add_argument("--aligned", default="data/tmc_bilingual_aligned.json")
    parser.add_argument("--database", required=True)
    parser.add_argument("--source-rom-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = json.loads(Path(args.aligned).read_text(encoding="utf-8"))
    report = sync_pack_inputs(Path(args.database), rows, args.source_rom_sha256, Path(args.output))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
