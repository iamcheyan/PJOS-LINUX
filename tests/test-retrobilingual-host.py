#!/usr/bin/env python3
"""Compile and run the host overlay harness against a synthetic approved pack."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
FONT = Path.home() / "development/pocketshell/app/fonts/SarasaUiSC-Regular.ttf"
PACK_PATH = ROOT / "tools/retrobilingual/pack.py"


def load_pack_module():
    spec = importlib.util.spec_from_file_location("rpack", PACK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if not FONT.exists():
        print("skip: Sarasa font not available")
        return 0
    pack = load_pack_module()
    with tempfile.TemporaryDirectory(prefix="rb-host-") as temporary:
        tmp = Path(temporary)
        rom = bytes(16 * 1024 * 1024)
        (tmp / "rom.gba").write_bytes(rom)
        digest = hashlib.sha256(rom).hexdigest()

        db = sqlite3.connect(tmp / "translations.db")
        db.execute(
            "CREATE TABLE translations (mapping_id INTEGER PRIMARY KEY, game_id TEXT,"
            " source_rom_hash TEXT, source_text_id TEXT, context_id TEXT, page_index INTEGER,"
            " japanese_text TEXT, chinese_text TEXT, match_method TEXT, confidence REAL, review_status TEXT)"
        )
        for page, text in ((0, "你好世界"), (1, "第二页")):
            db.execute(
                "INSERT INTO translations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (page + 1, "zelda_minish_cap", digest, "0201", "", page, "raw", "raw", "test", 1.0, "approved"),
            )
        db.commit()
        db.close()

        selected = [("0201", 0, "你好世界"), ("0201", 1, "第二页"), ("FFFF", 0, "暂无翻译")]
        chars = {c for _, _, text in selected for c in text}
        atlas, index = pack.build_atlas(chars, FONT, 12)
        blob = pack.build_pack(selected, atlas, index, 12, bytes.fromhex(digest))
        (tmp / "retrobilingual.pack").write_bytes(blob)

        binary = tmp / "overlay-test"
        subprocess.run(
            [
                "gcc", "-std=c11", "-O1", "-Wall", "-DRB_HOST_TEST",
                "-I", str(ROOT / "tests/host"), "-I", str(ROOT / "src"),
                str(ROOT / "src/retrobilingual.c"),
                str(ROOT / "tests/host/test_overlay.c"),
                "-o", str(binary),
            ],
            check=True,
        )
        env = dict(os.environ, RETROBILINGUAL_DIR=str(tmp))
        result = subprocess.run([str(binary), str(tmp / "rom.gba")], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout.strip())
        if result.returncode != 0:
            print("host overlay test failed")
            return result.returncode
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
