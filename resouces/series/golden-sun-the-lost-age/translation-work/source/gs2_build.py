#!/usr/bin/env python3
"""Build Golden Sun: The Lost Age zh-Hans HUD pages from Project Atlantis.

Records are keyed by the verified AGFJ01 rev0 string_id. Control 0x01 is the
A-press page break, 0x03 is a line break, 0x02 ends the message. Target text
uses {01}/{03}/{02} placeholders; pages therefore follow the Japanese game.
"""
import glob
import json
import re
import sys
from pathlib import Path

DEV_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(DEV_ROOT / "retrobilingual" / "tools"))
import importlib.util
spec = importlib.util.spec_from_file_location("pack", str(DEV_ROOT / "retrobilingual" / "tools" / "pack.py"))
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)

ROM_SHA = "19dd48b74726f323cd829e226b60aa1b373c51fb2e840804efe2d2dc2891a890"
FONT = str(DEV_ROOT / "pocketshell" / "app" / "fonts" / "SarasaUiSC-Regular.ttf")
SRC = "/tmp/project-atlantis/games/golden-sun-the-lost-age/translations"


def clean(fragment):
    fragment = fragment.replace("{03}", "\n")
    fragment = re.sub(r"\{[0-9A-Fa-f]{2}\}", "", fragment)
    lines = [line.strip() for line in fragment.split("\n") if line.strip()]
    return "\n".join(lines)


def split_pages(text, need):
    if "{01}" in text:
        parts = [clean(p) for p in text.split("{01}")]
        parts = [p for p in parts if p]
        if len(parts) == need:
            return parts
    body = clean(text)
    lines = [line for line in body.split("\n") if line.strip()]
    if need <= 1:
        return [body] if body else []
    if len(lines) < need:
        # Too few lines: split at sentence punctuation to reach the page count.
        body = "".join(lines)
        pieces = []
        start = 0
        for i in range(1, need):
            target = round(len(body) * i / need)
            lo = start + 1
            hi = len(body) - (need - i)
            target = min(max(target, lo), max(lo, hi))
            window = max(2, len(body) // (need * 3))
            cand = [j for j in range(max(lo, target - window), min(len(body), target + window + 1))
                    if j > start and body[j - 1] in "。！？…，、；：,.!?;:"]
            cut = min(cand, key=lambda j: abs(j - target)) if cand else target
            cut = min(max(cut, lo), max(lo, hi))
            pieces.append(body[start:cut].strip())
            start = cut
        pieces.append(body[start:].strip())
        while len(pieces) < need:
            pieces.append("…")
        return pieces[:need]
    # Group lines into exactly `need` pages, balanced by line count.
    pages = []
    start = 0
    for i in range(need):
        if i == need - 1:
            end = len(lines)
        else:
            end = max(start + 1, round(len(lines) * (i + 1) / need))
        pages.append("\n".join(lines[start:end]))
        start = end
    return [p for p in pages if p]


def main():
    records = {}
    for path in glob.glob(f"{SRC}/*.jsonl"):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            records[r["string_id"]] = r
    entries = []
    bad = []
    for sid in sorted(records):
        r = records[sid]
        text = r.get("targets", {}).get("zh-Hans", {}).get("text", "")
        if not text:
            continue
        controls = r.get("context", {}).get("control_codes", [])
        need = controls.count("0001") + 1
        pages = split_pages(text, need)
        if len(pages) != need:
            bad.append((sid, need, len(pages)))
        for i, page in enumerate(pages):
            if page:
                entries.append({"source_id": f"{sid:04X}", "page_index": i, "text": page})

    out = Path(__file__).resolve().parents[1] / "work" / "gs2_text_zh.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")

    selected = [(e["source_id"], e["page_index"], e["text"]) for e in entries]
    selected.append(("FFFF", 0, "暂无翻译"))
    chars = {c for _, _, t in selected for c in t if c != "\n"}
    atlas, index = pack.build_atlas(chars, Path(FONT), 12)
    blob = pack.build_pack(selected, atlas, index, 12, bytes.fromhex(ROM_SHA))
    pack_path = Path(__file__).resolve().parents[2] / "gba" / "golden-sun-the-lost-age-ja.ja-zh.pack"
    pack_path.write_bytes(blob)
    print(json.dumps({
        "messages": len(records),
        "entries": len(entries),
        "page_count_issues": len(bad),
        "issue_sample": bad[:10],
        "glyphs": len(atlas),
        "pack_bytes": len(blob),
        "pack": str(pack_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
