#!/usr/bin/env python3
"""Rebuild TMC bilingual rows from raw-script dialogue page boundaries.

The TMC renderer waits for A after the second raw 0x0A newline.  This tool
therefore treats page identity from freshly extracted Japanese and Chinese ROM
entries as authoritative.  It never uses visual line wrapping to make pages.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


CHINESE_FIELDS = {
    "chinese", "chinese_raw", "unmapped_glyphs", "lines", "line_count",
    "max_line_len", "status", "is_empty", "issues",
}


def entries(document: list[dict] | dict) -> list[dict]:
    result = document.get("entries") if isinstance(document, dict) else document
    if not isinstance(result, list):
        raise ValueError("document must be an entry list or an object with entries")
    return result


def page_key(entry: dict) -> tuple[str, int]:
    return str(entry.get("source_id", "")).upper(), int(entry.get("page_index", 0))


def grouped(document: list[dict] | dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for entry in entries(document):
        result[page_key(entry)[0]].append(entry)
    for group in result.values():
        group.sort(key=lambda entry: page_key(entry)[1])
    return result


def text_lines(text: str) -> list[str]:
    return text.replace("\\n", "\n").split("\n")


def chinese_fields(text: str, raw: str, missing: list[str]) -> dict:
    lines = text_lines(text) if text and text != "[EMPTY]" else []
    return {
        "chinese": text,
        "chinese_raw": raw,
        "unmapped_glyphs": missing,
        "lines": lines,
        "line_count": len(lines),
        "max_line_len": max((len(line) for line in lines), default=0),
        "status": "approved" if text and text != "[EMPTY]" and "[G" not in text else "pending",
        "is_empty": text in ("", "[EMPTY]"),
        "issues": [],
    }


def base_row(previous: dict[tuple[str, int], dict], source_id: str, page: int) -> dict:
    # English was extracted with the obsolete page interpretation.  Keep an
    # exact prior page where one exists; otherwise carry its source-level
    # metadata only to page 0 rather than pretending its English is paged.
    prior = previous.get((source_id, page))
    if prior is None and page == 0:
        prior = previous.get((source_id, 0))
    row = {key: value for key, value in (prior or {}).items() if key not in CHINESE_FIELDS}
    row.update({
        "source_id": source_id,
        "page_index": page,
        "category": source_id[:2],
        "entry_index": source_id[2:],
        "english": str((prior or {}).get("english", "")) if page == 0 or prior is not None else "",
    })
    return row


def build_repaginated_alignment(
    japanese_document: list[dict] | dict,
    chinese_document: list[dict] | dict,
    previous_document: list[dict] | dict,
) -> tuple[list[dict], list[dict]]:
    japanese = grouped(japanese_document)
    chinese = grouped(chinese_document)
    previous = {page_key(entry): entry for entry in entries(previous_document)}
    rows: list[dict] = []
    mismatches: list[dict] = []

    for source_id in sorted(japanese, key=lambda value: int(value, 16)):
        ja_pages = japanese[source_id]
        zh_pages = chinese.get(source_id, [])
        matching_counts = len(ja_pages) == len(zh_pages)
        if not matching_counts:
            mismatches.append({
                "source_id": source_id,
                "japanese_pages": len(ja_pages),
                "chinese_pages": len(zh_pages),
            })
            full_text = "".join(str(entry.get("text", "")) for entry in zh_pages)
            full_raw = "".join(str(entry.get("raw_text", "")) for entry in zh_pages)
            missing = list(dict.fromkeys(
                glyph for entry in zh_pages for glyph in entry.get("missing_glyphs", [])
            ))

        for index, ja_entry in enumerate(ja_pages):
            page = page_key(ja_entry)[1]
            row = base_row(previous, source_id, page)
            row["japanese"] = str(ja_entry.get("text", ""))
            if matching_counts:
                zh_entry = zh_pages[index]
                row.update(chinese_fields(
                    str(zh_entry.get("text", "")),
                    str(zh_entry.get("raw_text", "")),
                    list(zh_entry.get("missing_glyphs", [])),
                ))
            elif index == 0:
                row.update(chinese_fields(full_text, full_raw, missing))
            else:
                row.update(chinese_fields("", "", []))
            rows.append(row)

    return rows, mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild bilingual rows from TMC raw dialogue pages")
    parser.add_argument("--japanese", default="data/tmc_japanese_entries.json")
    parser.add_argument("--chinese", default="data/chinese_utf8.json")
    parser.add_argument("--previous", default="data/tmc_bilingual_aligned.json")
    parser.add_argument("--output", default="data/tmc_bilingual_aligned.json")
    parser.add_argument("--report", default="/tmp/tmc_dialogue_page_report.json")
    args = parser.parse_args()

    japanese = json.loads(Path(args.japanese).read_text(encoding="utf-8"))
    chinese = json.loads(Path(args.chinese).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8"))
    rows, mismatches = build_repaginated_alignment(japanese, chinese, previous)
    Path(args.output).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "rows": len(rows),
        "approved": sum(row["status"] == "approved" for row in rows),
        "pending": sum(row["status"] == "pending" for row in rows),
        "mismatch_ids": len(mismatches),
        "mismatches": mismatches,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "mismatches"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
