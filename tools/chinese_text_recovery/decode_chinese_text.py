#!/usr/bin/env python3
"""decode_chinese_text.py - Batch decode BZMJ raw bytecode into clean UTF-8 Chinese text.

Inputs:
  .orca/drops/塞尔达传说_缩小帽.gba
  data/glyph_mapping.json

Outputs:
  data/chinese_utf8.json
"""

import json
import re
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.retrobilingual.tmc_rom import extract_tmc_rom

ROM_PATH = Path(".orca/drops/塞尔达传说_缩小帽.gba")
MAPPING_PATH = Path("data/glyph_mapping.json")
OUTPUT_PATH = Path("data/chinese_utf8.json")

def decode_text(raw_text: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """Decodes raw bytecode string into UTF-8 using glyph_mapping.
    Returns (decoded_string, missing_glyph_tags).
    """
    missing = []

    def replace_token(match):
        bank = match.group(1)
        code = match.group(2).upper()
        tag = f"G{bank}:{code}"
        if tag in mapping and mapping[tag] is not None:
            return mapping[tag]
        missing.append(tag)
        return f"[{tag}]"

    # Replace [G{bank}:{code}] tokens
    decoded = re.sub(r'\[G(\d+):([0-9A-Fa-f]{2})\]', replace_token, raw_text)

    # Standardize player name and control codes
    decoded = re.sub(r'\[C06:00\]|\[Player\]', '{player}', decoded)
    decoded = re.sub(r'\[C[0-9A-Fa-f:]+\]', '', decoded) # all control codes
    decoded = re.sub(r'\[WAIT\]', '', decoded)

    return decoded, missing

def run_decode():
    if not ROM_PATH.exists():
        raise FileNotFoundError(f"ROM not found at {ROM_PATH}")

    mapping = {}
    if MAPPING_PATH.exists():
        with open(MAPPING_PATH, "r", encoding="utf-8") as f:
            mapping = json.load(f)

    print(f"Loaded {len(mapping)} glyph mappings from {MAPPING_PATH}")

    extracted = extract_tmc_rom(ROM_PATH, "zh")
    entries = extracted["entries"]

    results = []
    total_entries = len(entries)
    fully_decoded_count = 0
    all_missing_glyphs = set()

    for entry in entries:
        raw_text = entry["text"]
        decoded_text, missing = decode_text(raw_text, mapping)
        if not missing and decoded_text != "[EMPTY]":
            fully_decoded_count += 1
        all_missing_glyphs.update(missing)

        results.append({
            "source_id": entry["source_id"],
            "page_index": entry["page_index"],
            "rom_offset": entry["rom_offset"],
            "raw_text": raw_text,
            "text": decoded_text,
            "chinese_utf8": decoded_text,
            "status": "decoded" if not missing else "partial",
            "missing_glyphs": missing
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Also save structured TMC export for retrobilingual alignment and DB import
    export_doc = dict(extracted)
    export_entries = []
    for r, orig in zip(results, entries):
        entry_copy = dict(orig)
        entry_copy["text"] = r["text"]
        entry_copy["decode_status"] = r["status"]
        export_entries.append(entry_copy)
    export_doc["entries"] = export_entries
    export_path = Path("data/tmc_chinese_export.json")
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(export_doc, f, indent=2, ensure_ascii=False)

    non_empty_count = sum(1 for e in entries if e["text"] != "[EMPTY]")
    print(f"\nDecoding Results:")
    print(f"  Total text entries: {total_entries}")
    print(f"  Non-empty entries:  {non_empty_count}")
    print(f"  Fully decoded (non-empty): {fully_decoded_count} / {non_empty_count} ({fully_decoded_count/non_empty_count*100:.2f}%)")
    print(f"  Total handled (decoded + empty): {fully_decoded_count + (total_entries - non_empty_count)} / {total_entries} ({(fully_decoded_count + total_entries - non_empty_count)/total_entries*100:.2f}%)")
    print(f"  Remaining unmapped glyphs: {len(all_missing_glyphs)}")
    if all_missing_glyphs:
        sample = sorted(list(all_missing_glyphs))[:15]
        print(f"  Sample unmapped glyph tags: {sample}")
    print(f"\nSaved decoded dataset to {OUTPUT_PATH}")

if __name__ == "__main__":
    run_decode()
