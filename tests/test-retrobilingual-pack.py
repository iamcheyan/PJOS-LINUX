#!/usr/bin/env python3
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
FONT = Path.home() / "development/pocketshell/app/fonts/SarasaUiSC-Regular.ttf"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retro = load("retrobilingual", ROOT / "tools/retrobilingual/retrobilingual.py")
pack = load("rpack", ROOT / "tools/retrobilingual/pack.py")

JA_HASH = "1" * 64
ZH_HASH = "2" * 64


def export(language, digest, entries):
    return {"game": "zelda_minish_cap", "language": language, "rom_sha256": digest, "entries": entries}


def parse(pack_bytes):
    assert pack_bytes[:4] == b"RBPK"
    version, gw, gh, gcount, ecount = struct.unpack_from("<HHHII", pack_bytes, 4)
    off = 18 + 32
    glyph_bytes = (gw * gh + 7) // 8
    glyphs = []
    for _ in range(gcount):
        cp = struct.unpack_from("<I", pack_bytes, off)[0]
        off += 4
        glyphs.append((cp, pack_bytes[off:off + glyph_bytes]))
        off += glyph_bytes
    entries = []
    for _ in range(ecount):
        text_id, page, _pad, first, count = struct.unpack_from("<HBBHH", pack_bytes, off)
        off += 8
        entries.append((text_id, page, first, count))
    indices = list(struct.unpack_from(f"<{(len(pack_bytes)-off)//2}H", pack_bytes, off))
    return dict(version=version, glyphs=glyphs, entries=entries, indices=indices)


@unittest.skipUnless(FONT.exists(), "Sarasa font not available")
class PackTests(unittest.TestCase):
    def build_db(self, directory):
        db = retro.connect(Path(directory) / "translations.db")
        ja = export("ja", JA_HASH, [
            {"source_id": "0001", "text": "[G4:01]"},
            {"source_id": "0002", "text": "[G4:02]"},
        ])
        zh = export("zh", ZH_HASH, [
            {"source_id": "0001", "text": "[G4:11]"},
            {"source_id": "0002", "text": "[G4:12]"},
        ])
        retro.align_documents(ja, zh, db)
        mapping = db.execute(
            "SELECT mapping_id FROM context_mappings WHERE source_text_id='0001'"
        ).fetchone()[0]
        db.execute("UPDATE context_mappings SET review_status='approved' WHERE mapping_id=?", (mapping,))
        db.execute("UPDATE translations SET review_status='approved' WHERE mapping_id=?", (mapping,))
        db.commit()
        return db

    def test_pack_contains_only_approved_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = self.build_db(temporary)
            texts = Path(temporary) / "zh.json"
            texts.write_text(json.dumps({"entries": [
                {"source_id": "0001", "page_index": 0, "text": "你好"},
                {"source_id": "0002", "page_index": 0, "text": "未审核"},
            ]}, ensure_ascii=False), encoding="utf-8")
            approved = pack.approved_mappings(Path(temporary) / "translations.db", JA_HASH)
            self.assertEqual(approved, [("0001", 0)])
            mapping = dict(approved)
            selected = [("0001", 0, "你好")]
            chars = {c for _, _, t in selected for c in t if c != "\n"}
            atlas, index = pack.build_atlas(chars, FONT, 12)
            blob = pack.build_pack(selected, atlas, index, 12, bytes.fromhex(JA_HASH))
            parsed = parse(blob)
            self.assertEqual(len(parsed["entries"]), 1)
            self.assertEqual(parsed["entries"][0][0], 0x0001)
            self.assertEqual(parsed["entries"][0][1], 0)
            codepoints = {cp for cp, _ in parsed["glyphs"]}
            self.assertEqual(codepoints, {ord("你"), ord("好")})
            for index_value in parsed["indices"]:
                self.assertLess(index_value, len(parsed["glyphs"]))

    def test_pack_builder_refuses_empty_approved_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = self.build_db(temporary)
            texts = {"0002": "未审核"}
            approved = pack.approved_mappings(Path(temporary) / "translations.db", JA_HASH)
            selected = [(sid, page, texts[sid]) for sid, page in approved if sid in texts]
            self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
