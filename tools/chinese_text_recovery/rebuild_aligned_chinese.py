#!/usr/bin/env python3
"""Refresh only the Chinese-derived fields in the bilingual alignment.

English/Japanese alignment and page identity are authoritative and are copied
unchanged.  Unmatched Chinese records are reported and leave the aligned row
empty instead of being guessed or removed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CHINESE_FIELDS = {
    "chinese",
    "chinese_raw",
    "unmapped_glyphs",
    "lines",
    "line_count",
    "max_line_len",
    "status",
}
TAG_RE = re.compile(r"\[G\d+:[0-9A-Fa-f]{2}\]")


def key(entry: dict) -> tuple[str, int]:
    return str(entry.get("source_id", "")).upper(), int(entry.get("page_index", 0))


def lines_for(text: str) -> list[str]:
    # Keep the source's explicit empty lines.  This is not the packer's visual
    # wrapping step and must not invent page numbers.
    return text.replace("\\n", "\n").split("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aligned", default="data/tmc_bilingual_aligned.json")
    parser.add_argument("--decoded", default="data/chinese_utf8.json")
    parser.add_argument("--output", default="data/tmc_bilingual_aligned.json")
    parser.add_argument("--report", default="/tmp/glyph_rebuild_report.md")
    args = parser.parse_args()

    aligned_path = Path(args.aligned)
    decoded: list[dict] = json.loads(Path(args.decoded).read_text(encoding="utf-8"))
    source_by_key = {key(entry): entry for entry in decoded}
    aligned: list[dict] = json.loads(aligned_path.read_text(encoding="utf-8"))
    unmatched: list[tuple[str, int]] = []
    pending = 0
    approved = 0

    refreshed = []
    for original in aligned:
        entry = source_by_key.get(key(original))
        row = dict(original)
        if entry is None:
            unmatched.append(key(original))
            text = ""
            raw = ""
            missing: list[str] = []
        else:
            text = str(entry.get("text", ""))
            raw = str(entry.get("raw_text", ""))
            missing = list(entry.get("missing_glyphs", []))
        row.update({
            "chinese": text,
            "chinese_raw": raw,
            "unmapped_glyphs": missing,
            "lines": lines_for(text) if text else [],
            "line_count": len(lines_for(text)) if text else 0,
            "max_line_len": max((len(line) for line in lines_for(text)), default=0),
            "status": "approved" if text and "[G" not in text and text != "[EMPTY]" else "pending",
        })
        if row["status"] == "approved":
            approved += 1
        else:
            pending += 1
        refreshed.append(row)

    output = Path(args.output)
    temp = output.with_suffix(output.suffix + ".new")
    temp.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(output)

    report = [
        "# 阶段 1 中文栏重建报告",
        "",
        f"- 对齐行：{len(aligned)}",
        f"- 匹配到中文页：{len(aligned) - len(unmatched)}",
        f"- 未匹配页（保留空白）：{len(unmatched)}",
        f"- approved：{approved}",
        f"- pending：{pending}",
        "",
        "## 未匹配键",
        "",
    ]
    report.extend(f"- `{sid}` page `{page}`" for sid, page in unmatched)
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"updated={len(refreshed)} matched={len(aligned) - len(unmatched)} unmatched={len(unmatched)}")
    print(f"approved={approved} pending={pending} report={args.report}")


if __name__ == "__main__":
    main()
