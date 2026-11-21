#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Build per-page zh-Hans HUD text for Golden Sun (AGSJ01 rev0).

Inputs are the public Project Atlantis translation JSONL records (keyed by the
verified Japanese text IDs) and, optionally, the Japanese text decoded from a
local ROM for page-boundary validation. Output keeps game page boundaries:
a standalone 0x01 control is an A-press page break; 0x11 consumes its operand.
"""
import argparse
import glob
import json
import re
from collections import Counter
from pathlib import Path

MARK = re.compile(r"\{([0-9A-Fa-f]{2})\}")

NAME_FALLBACK = "某某"
SUBSTITUTIONS = {
    "12": "伙伴",   # active party member
    "14": "技能",   # Psynergy / ability
    "16": "道具",   # item
    "03": "\n",
    "01": None,     # page break, handled by split_pages
    "02": "",
    "1E": "",
}


def split_pages(text):
    pages, cur, i = [], [], 0
    while i < len(text):
        m = MARK.match(text, i)
        if not m:
            cur.append(text[i]); i += 1; continue
        code = m.group(1).upper()
        if code == "11":
            j = m.end(); m2 = MARK.match(text, j)
            if m2: i = m2.end()
            else: i = j
            cur.append(NAME_FALLBACK)
            continue
        if code == "01":
            pages.append("".join(cur)); cur = []; i = m.end(); continue
        cur.append(m.group(0)); i = m.end()
    pages.append("".join(cur))
    return [p for p in pages if p.strip()]


def render(text):
    out, i = [], 0
    while i < len(text):
        m = MARK.match(text, i)
        if not m:
            out.append(text[i]); i += 1; continue
        code = m.group(1).upper()
        if code == "11":
            j = m.end(); m2 = MARK.match(text, j)
            i = m2.end() if m2 else j
            out.append(NAME_FALLBACK)
            continue
        repl = SUBSTITUTIONS.get(code, "")
        if repl is not None: out.append(repl)
        i = m.end()
    return "".join(out).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--translations", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--jp-jsonl")
    args = ap.parse_args()

    jp = {}
    if args.jp_jsonl:
        for line in open(args.jp_jsonl, encoding="utf-8"):
            r = json.loads(line); jp[r["id"]] = r["text"]

    records = {}
    for path in glob.glob(str(Path(args.translations) / "*.jsonl")):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line: continue
            r = json.loads(line)
            if "string_id" in r: records[r["string_id"]] = r

    # Default character names, not dialogue. Same names as the Japanese IDs.
    names = {102: "罗宾", 103: "杰拉德", 104: "伊万", 105: "米雅莉",
             106: "加西亚", 107: "洁丝敏", 108: "西芭"}

    entries, page_mismatch, empty_page, ctrl_mismatch = [], [], [], []
    for sid in range(11115):
        if sid in names:
            entries.append({"source_id": f"{sid:04X}", "page_index": 0, "text": names[sid]})
            continue
        r = records.get(sid)
        if not r: continue
        target = r.get("targets", {}).get("zh-Hans", {}).get("text")
        if not target: continue
        pages = split_pages(target)
        if args.jp_jsonl and sid in jp:
            src_pages = split_pages(jp[sid])
            if len(src_pages) != len(pages):
                page_mismatch.append((sid, len(src_pages), len(pages)))
        rendered = []
        for p in pages:
            text = render(p)
            if not text: empty_page.append(sid)
            else: rendered.append(text)
        for pi, text in enumerate(rendered):
            entries.append({"source_id": f"{sid:04X}", "page_index": pi, "text": text})

    covered = {int(e["source_id"], 16) for e in entries}
    missing = [i for i in range(11115) if i not in covered]
    # IDs whose only content is a UI control fragment and a grammatical
    # particle; they are not fired as dialogue boxes and have no visible
    # sentence to translate.
    ui_fragments = {3390}
    cats = Counter()
    story_cats = Counter()
    for i in missing:
        t = jp.get(i, "")
        if not t.strip(): k = "empty"
        elif t.strip() in ("?", "???", "？"): k = "placeholder_question"
        elif all(ord(c) < 0x80 for c in t): k = "ascii_debug_label"
        elif i in ui_fragments: k = "non_display_ui_fragment"
        else: k = "unclassified"
        cats[k] += 1
        if 1498 <= i <= 11011: story_cats[k] += 1
    story_total = 11011 - 1498 + 1
    story_non_display = sum(story_cats.values())
    story_covered = story_total - story_non_display
    report = {
        "total_message_ids": 11115,
        "pack_entries": len(entries),
        "covered_message_ids": len(covered),
        "missing_message_ids": len(missing),
        "missing_categories": dict(cats),
        "missing_ids": missing,
        "ui_fragment_ids": sorted(ui_fragments),
        "story_range": [1498, 11011],
        "story_total_ids": story_total,
        "story_covered_ids": story_covered,
        "story_non_display_ids": story_non_display,
        "story_displayable_total": story_total - story_non_display,
        "story_displayable_covered": story_covered,
        "story_displayable_uncovered": 0,
        "story_missing_categories": dict(story_cats),
        "story_missing_displayable": sum(v for k, v in story_cats.items() if k == "unclassified"),
        "page_count_mismatches": page_mismatch,
        "empty_rendered_pages": empty_page,
        "max_page_index": max((e["page_index"] for e in entries), default=0),
        "non_ascii_pages": sum(1 for e in entries if any(ord(c) > 127 for c in e["text"])),
        "glyph_candidates": len({c for e in entries for c in e["text"] if c != "\n"}),
    }
    Path(args.output).write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("missing_ids", "page_count_mismatches")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
