#!/usr/bin/env python3
"""build_review_html.py - Generate a visual inspection HTML for glyph mappings.

Outputs:
  data/review.html: Webpage displaying every glyph image, tag, frequency, sample sentence, and mapped char.
"""

import json
import re
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.retrobilingual.tmc_rom import extract_tmc_rom

ROM_PATH = Path(".orca/drops/塞尔达传说_缩小帽.gba")
INDEX_PATH = Path("data/glyphs/index.json")
MAPPING_PATH = Path("data/glyph_mapping.json")
OUTPUT_HTML = Path("data/review.html")

def build():
    if not INDEX_PATH.exists():
        print("Run extract_glyphs.py first.")
        return

    mapping = {}
    if MAPPING_PATH.exists():
        with open(MAPPING_PATH, "r", encoding="utf-8") as f:
            mapping = json.load(f)

    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        glyphs = json.load(f)

    # Compute frequency and sample sentences from ROM texts
    extracted = extract_tmc_rom(ROM_PATH, "zh")
    entries = extracted["entries"]

    freq = Counter()
    examples = {}

    for entry in entries:
        text = entry["text"]
        tokens = re.findall(r'\[G(\d):([0-9A-Fa-f]{2})\]', text)
        for bank, code in tokens:
            key = f"G{bank}:{code.upper()}"
            freq[key] += 1
            if key not in examples and len(text) > 5:
                examples[key] = text[:60]

    # Sort glyphs: unmapped first (by frequency desc), then mapped
    def sort_key(g):
        tag = f"G{g['bank']}:{g['code_hex']}"
        is_mapped = tag in mapping and mapping[tag]
        return (1 if is_mapped else 0, -freq[tag], g["bank"], g["code"])

    glyphs.sort(key=sort_key)

    html = []
    html.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    html.append("<title>RetroBilingual - BZMJ Glyph Review</title>")
    html.append("<style>")
    html.append("body { font-family: monospace; background: #1a1a1a; color: #e0e0e0; margin: 20px; }")
    html.append("table { border-collapse: collapse; width: 100%; max-width: 1200px; margin: 0 auto; }")
    html.append("th, td { border: 1px solid #444; padding: 6px 10px; text-align: left; }")
    html.append("th { background: #2d2d2d; position: sticky; top: 0; }")
    html.append(".glyph-img { image-rendering: pixelated; width: 32px; height: 32px; vertical-align: middle; background: #000; border: 1px solid #555; }")
    html.append(".mapped { background: #1b3320; }")
    html.append(".unmapped { background: #331b1b; }")
    html.append(".char-preview { font-size: 24px; font-weight: bold; color: #4ade80; }")
    html.append("</style></head><body>")
    html.append("<h1>RetroBilingual - BZMJ Font Glyphs Review</h1>")
    html.append(f"<p>Total Unique Glyphs: {len(glyphs)} | Mapped: {len(mapping)} | Unmapped: {len(glyphs) - len(mapping)}</p>")
    html.append("<table>")
    html.append("<tr><th>Tag</th><th>Glyph (2x)</th><th>Mapped Char</th><th>Freq</th><th>Sample Sentence</th></tr>")

    for g in glyphs:
        tag = f"G{g['bank']}:{g['code_hex']}"
        mapped_char = mapping.get(tag, "")
        count = freq.get(tag, 0)
        ex = examples.get(tag, "-")
        status_class = "mapped" if mapped_char else "unmapped"
        img_src = f"glyphs/G{g['bank']}_{g['code_hex']}.png"

        html.append(f"<tr class='{status_class}'>")
        html.append(f"<td><b>[{tag}]</b></td>")
        html.append(f"<td><img class='glyph-img' src='{img_src}'></td>")
        html.append(f"<td class='char-preview'>{mapped_char}</td>")
        html.append(f"<td>{count}</td>")
        html.append(f"<td><small>{ex}</small></td>")
        html.append("</tr>")

    html.append("</table></body></html>")

    OUTPUT_HTML.write_text("\n".join(html), encoding="utf-8")
    print(f"Review HTML generated at {OUTPUT_HTML}")

if __name__ == "__main__":
    build()
