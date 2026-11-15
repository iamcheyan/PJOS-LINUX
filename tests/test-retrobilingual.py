#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/retrobilingual/retrobilingual.py"
SPEC = importlib.util.spec_from_file_location("retrobilingual", MODULE_PATH)
retro = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retro)
import tmc_rom


def export(language, digest, entries):
    return {"game": "zelda_minish_cap", "language": language, "rom_sha256": digest, "entries": entries}


class RetroBilingualTests(unittest.TestCase):
    def test_inspect_reports_gba_identity_and_checksum(self):
        header = bytearray(0xC0)
        header[0xA0:0xAC] = b"TEST GAME   "
        header[0xAC:0xB0] = b"ABCD"
        header[0xB0:0xB2] = b"01"
        header[0xBD] = (-sum(header[0xA0:0xBD]) - 0x19) & 0xFF
        with tempfile.TemporaryDirectory() as temporary:
            rom_path = Path(temporary) / "probe.gba"
            rom_path.write_bytes(header)
            result = retro.inspect_rom(rom_path)
        self.assertEqual(result["title"], "TEST GAME")
        self.assertEqual(result["game_code"], "ABCD")
        self.assertTrue(result["header_checksum_valid"])
        self.assertEqual(result["sha256"], hashlib.sha256(header).hexdigest())

    def test_short_rom_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            rom_path = Path(temporary) / "short.gba"
            rom_path.write_bytes(b"too short")
            with self.assertRaisesRegex(ValueError, "shorter than a GBA header"):
                retro.inspect_rom(rom_path)

    def test_read_export_accepts_decoder_entry_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "decoded.json"
            path.write_text(json.dumps([
                {"source_id": "1002", "page_index": 0, "text": "中文"},
            ], ensure_ascii=False), encoding="utf-8")
            document = retro.read_export(path, "zh")
        self.assertEqual(document["game"], "zelda_minish_cap")
        self.assertEqual(document["language"], "zh")
        self.assertEqual(document["rom_sha256"], "f51c6c2f90e18ee91203dd767307271e06901b5bff35c3a567d52f61a39d166d")

    def test_alignment_is_pending_and_repeatable(self):
        ja = export("ja", "1" * 64, [
            {"source_id": "0201", "context_id": "field:npc-1", "page_index": 0, "text": "日本語の台詞"},
            {"source_id": "0201", "context_id": "field:npc-1", "page_index": 1, "text": "続き"},
            {"source_id": "0202", "text": "別の台詞"},
        ])
        zh = export("zh", "2" * 64, [
            {"source_id": "0201", "context_id": "field:npc-1", "page_index": 0, "text": "中文对话"},
            {"source_id": "0201", "context_id": "field:npc-1", "page_index": 1, "text": "续句"},
        ])
        with tempfile.TemporaryDirectory() as temporary:
            db = retro.connect(Path(temporary) / "translations.db")
            first = retro.align_documents(ja, zh, db)
            second = retro.align_documents(ja, zh, db)
            count = db.execute("SELECT COUNT(*) FROM context_mappings").fetchone()[0]
            statuses = db.execute("SELECT DISTINCT review_status FROM translations").fetchall()
        self.assertEqual(first["suggested_matches"], 2)
        self.assertEqual(second["suggested_matches"], 2)
        self.assertEqual(first["unmatched_japanese"], 1)
        self.assertEqual(count, 2)
        self.assertEqual(statuses, [("pending",)])

    def test_repeated_exact_keys_are_ambiguous(self):
        ja = export("ja", "3" * 64, [
            {"source_id": "0101", "text": "同一キー一"},
            {"source_id": "0101", "text": "同一キー二"},
        ])
        zh = export("zh", "4" * 64, [
            {"source_id": "0101", "text": "相同编号一"},
            {"source_id": "0101", "text": "相同编号二"},
        ])
        with tempfile.TemporaryDirectory() as temporary:
            db = retro.connect(Path(temporary) / "translations.db")
            report = retro.align_documents(ja, zh, db)
            mappings = db.execute("SELECT COUNT(*) FROM context_mappings").fetchone()[0]
        self.assertEqual(report["suggested_matches"], 0)
        self.assertEqual(report["ambiguous_japanese"], 2)
        self.assertEqual(mappings, 0)

    def test_glyph_decoder_uses_second_newline_as_tmc_page_boundary(self):
        # TMC text.c:GetCharacter maps raw 0x0A to command 1.  message.c
        # enters RENDER_WAIT only when command 1 arrives on line two.
        raw = bytes((0x01, 0x00, ord("A"), 0x0A, ord("B"), 0x0A, ord("C")))
        pages = tmc_rom._glyph_string(raw)
        self.assertEqual([page["page_index"] for page in pages], [0, 1])
        self.assertEqual(pages[0]["text"], "[C01:00]A\\nB\\n")
        self.assertEqual(pages[1]["text"], "C")
        self.assertEqual(pages[0]["raw_hex"], "0100410a420a")

    def test_encoded_string_allows_zero_inside_control_parameters(self):
        rom = bytes((0x02, 0x00, ord("A"), 0x00))
        raw, end = tmc_rom._read_encoded_string(rom, 0, len(rom))
        self.assertEqual(raw, bytes((0x02, 0x00, ord("A"))))
        self.assertEqual(end, len(rom))

    def test_encoded_string_allows_zero_inside_01_control_parameter(self):
        rom = bytes((0x01, 0x00, ord("A"), 0x00))
        raw, end = tmc_rom._read_encoded_string(rom, 0, len(rom))
        self.assertEqual(raw, bytes((0x01, 0x00, ord("A"))))
        self.assertEqual(end, len(rom))

    def test_review_updates_runtime_translation_status(self):
        ja = export("ja", "5" * 64, [{"source_id": "1001", "text": "原文"}])
        zh = export("zh", "6" * 64, [{"source_id": "1001", "text": "译文"}])
        with tempfile.TemporaryDirectory() as temporary:
            db = retro.connect(Path(temporary) / "translations.db")
            retro.align_documents(ja, zh, db)
            mapping_id = db.execute("SELECT mapping_id FROM context_mappings").fetchone()[0]
            db.execute("UPDATE context_mappings SET review_status='approved' WHERE mapping_id=?", (mapping_id,))
            db.execute("UPDATE translations SET review_status='approved' WHERE mapping_id=?", (mapping_id,))
            db.commit()
            report = retro.align_documents(ja, zh, db)
            row = db.execute("SELECT japanese_text, chinese_text, review_status FROM translations").fetchone()
        self.assertEqual(report["approved_matches"], 1)
        self.assertEqual(row, ("原文", "译文", "approved"))


if __name__ == "__main__":
    unittest.main()
