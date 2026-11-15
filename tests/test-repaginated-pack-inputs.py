#!/usr/bin/env python3
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/chinese_text_recovery/sync_repaginated_pack_inputs.py"
SPEC = importlib.util.spec_from_file_location("repack_inputs", MODULE_PATH)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class RepaginatedPackInputTests(unittest.TestCase):
    def test_only_approved_complete_rows_become_pack_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "translations.db"
            db = sqlite3.connect(database)
            db.execute(
                "CREATE TABLE translations (game_id TEXT, source_rom_hash TEXT,"
                " source_text_id TEXT, page_index INTEGER, review_status TEXT)"
            )
            for source_id, page in (("1002", 0), ("1002", 1), ("1002", 2)):
                db.execute(
                    "INSERT INTO translations VALUES (?, ?, ?, ?, ?)",
                    ("zelda_minish_cap", "a" * 64, source_id, page, "pending"),
                )
            db.commit()
            db.close()
            output = root / "approved-zh.json"
            report = sync.sync_pack_inputs(
                database,
                [
                    {"source_id": "1002", "page_index": 0, "chinese": "第一页", "status": "approved"},
                    {"source_id": "1002", "page_index": 1, "chinese": "[G9:E4]未完成", "status": "pending"},
                    {"source_id": "1002", "page_index": 2, "chinese": "第三页", "status": "approved"},
                ],
                "a" * 64,
                output,
            )
            self.assertEqual(report["approved_rows"], 2)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["entries"], [
                {"source_id": "1002", "page_index": 0, "text": "第一页"},
                {"source_id": "1002", "page_index": 2, "text": "第三页"},
            ])
            db = sqlite3.connect(database)
            statuses = db.execute(
                "SELECT page_index, review_status FROM translations ORDER BY page_index"
            ).fetchall()
            db.close()
            self.assertEqual(statuses, [(0, "approved"), (1, "pending"), (2, "approved")])


if __name__ == "__main__":
    unittest.main()
