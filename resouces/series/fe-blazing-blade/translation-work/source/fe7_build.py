#!/usr/bin/env python3
"""Build FE7 zh-Hans HUD pages aligned to the Japanese A-press pages.

Japanese page boundaries come from the FE7J decompilation's texts/texts.txt
([A] is the in-game wait-for-input page break). Chinese dialogue comes from
the public arceus-jia/fe7-cn-script HTML (spark x wolf fan translation).
Each game message gets exactly the Japanese number of pack pages.
"""
import argparse
import glob
import html
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

ROM_SHA = "7ec691a7411864ab51765028156c5b8a3c23a317d23c95fbf07ac201212e25c0"
FONT = str(DEV_ROOT / "pocketshell" / "app" / "fonts" / "SarasaUiSC-Regular.ttf")


def jp_messages(path):
    out = {}
    cur = None
    buf = []
    for line in open(path, encoding="utf-8"):
        s = line.rstrip("\n")
        m = re.match(r"##\s*MSG_([0-9A-Fa-f]+)", s)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur = int(m.group(1), 16)
            buf = []
            continue
        if cur is not None:
            buf.append(s)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def jp_pages(text):
    pages = [p for p in re.split(r"\[A\]", text) if p.strip()]
    widths = []
    for page in pages:
        # Display cells: one per SJIS glyph / ASCII, line breaks cost one cell.
        page = re.sub(r"\[(?:CR|LF|NL)\]", "\n", page)
        width = 0
        for ch in page:
            if ch == "\n":
                width += 1
            else:
                width += 1
        widths.append(max(1, width))
    return pages, widths


def article_texts(paths):
    arts = {}
    for path in paths:
        s = Path(path).read_text(encoding="utf-8")
        for m in re.finditer(r'<article id="t([0-9A-Fa-f]{4})"(.*?)</article>', s, re.S):
            sid = int(m.group(1), 16)
            paras = []
            for p in re.findall(r"<p>(.*?)</p>", m.group(2), re.S):
                p = re.sub(r"<img[^>]*>", "", p)
                p = re.sub(r"<b[^>]*>.*?</b>：?", "", p, flags=re.S)
                p = re.sub(r"<[^>]+>", "", p)
                p = html.unescape(p).strip()
                if p:
                    paras.append(p)
            if paras:
                arts[sid] = paras
    return arts


def split_long(text, n):
    """Split text into n pieces at sentence punctuation, then characters."""
    text = text.strip()
    if n <= 1:
        return [text]
    cuts = []
    start = 0
    for i in range(1, n):
        target = round(len(text) * i / n)
        lo = start + 1
        hi = len(text) - (n - i)
        target = min(max(target, lo), max(lo, hi))
        window = max(2, len(text) // (n * 3))
        cand = [j for j in range(max(lo, target - window), min(len(text), target + window + 1))
                if j > start and text[j - 1] in "。！？…，、；：,.!?;:"]
        cut = min(cand, key=lambda j: abs(j - target)) if cand else target
        cut = min(max(cut, lo), max(lo, hi))
        cuts.append(cut)
        start = cut
    pieces = []
    start = 0
    for cut in cuts:
        pieces.append(text[start:cut].strip())
        start = cut
    pieces.append(text[start:].strip())
    return pieces


def align(paras, widths):
    need = len(widths)
    if len(paras) == need:
        return paras
    if len(paras) > need:
        # Merge adjacent HTML paragraphs into the needed number of pages.
        total = sum(widths)
        out = []
        start = 0
        for i in range(need):
            if i == need - 1:
                end = len(paras)
            else:
                target = round(len(paras) * sum(widths[:i + 1]) / total)
                end = max(start + 1, min(target, len(paras) - (need - i - 1)))
            out.append("\n".join(paras[start:end]).strip())
            start = end
        return out
    # Too few paragraphs: join and split to the Japanese page count.
    return split_long("\n".join(paras), need)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jp-texts", default="/tmp/fe7j-inspect/texts/texts.txt")
    ap.add_argument("--cn-docs", default="/tmp/fe7-cn-script/docs")
    ap.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "work" / "fe7_text_zh.json"))
    ap.add_argument("--pack", default=str(Path(__file__).resolve().parents[2] / "gba" / "Fire_Emblem_Rekka_no_Ken_JA.ja-zh.pack"))
    args = ap.parse_args()

    jp = jp_messages(Path(args.jp_texts))
    paths = []
    for d in ("story", "support", "other"):
        paths += glob.glob(f"{args.cn_docs}/{d}/*.html")
    cn = article_texts(paths)

    entries = []
    direct = merged = split = 0
    for sid in sorted(cn):
        if sid not in jp or not jp[sid].strip():
            continue
        pages, widths = jp_pages(jp[sid])
        paras = cn[sid]
        if len(paras) == len(widths):
            direct += 1
        elif len(paras) > len(widths):
            merged += 1
        else:
            split += 1
        aligned = align(paras, widths)
        for i, text in enumerate(aligned):
            text = text.strip()
            if text:
                entries.append({"source_id": f"{sid:04X}", "page_index": i, "text": text})
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")

    selected = [(e["source_id"], e["page_index"], e["text"]) for e in entries]
    selected.append(("FFFF", 0, "暂无翻译"))
    chars = {c for _, _, t in selected for c in t if c != "\n"}
    atlas, index = pack.build_atlas(chars, Path(FONT), 12)
    blob = pack.build_pack(selected, atlas, index, 12, bytes.fromhex(ROM_SHA))
    Path(args.pack).write_bytes(blob)
    print(json.dumps({
        "messages": len({e["source_id"] for e in entries}),
        "entries": len(entries),
        "direct_pages": direct,
        "merged_paragraphs": merged,
        "split_paragraph": split,
        "glyphs": len(atlas),
        "pack_bytes": len(blob),
        "pack": args.pack,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
