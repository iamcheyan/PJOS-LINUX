#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/chinese_text_recovery/rebuild_dialogue_pages.py"
SPEC = importlib.util.spec_from_file_location("dialogue_page_rebuild", MODULE_PATH)
pages = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pages)


def japanese(source_id, page, text):
    return {"source_id": source_id, "page_index": page, "text": text}


def chinese(source_id, page, text, raw=None, missing=None):
    return {
        "source_id": source_id,
        "page_index": page,
        "text": text,
        "raw_text": text if raw is None else raw,
        "missing_glyphs": [] if missing is None else missing,
    }


class DialoguePageRebuildTests(unittest.TestCase):
    def test_equal_raw_page_counts_pair_each_page(self):
        rows, mismatches = pages.build_repaginated_alignment(
            [japanese("1002", 0, "日文甲"), japanese("1002", 1, "日文乙")],
            [chinese("1002", 0, "中文甲"), chinese("1002", 1, "中文乙")],
            [{"source_id": "1002", "page_index": 0, "english": "English"}],
        )
        self.assertEqual(mismatches, [])
        self.assertEqual([(row["source_id"], row["page_index"], row["chinese"]) for row in rows], [
            ("1002", 0, "中文甲"),
            ("1002", 1, "中文乙"),
        ])
        self.assertEqual(rows[0]["english"], "English")
        self.assertEqual(rows[1]["english"], "")
        self.assertEqual([row["status"] for row in rows], ["approved", "approved"])

    def test_mismatched_raw_page_counts_keep_full_chinese_on_page_zero(self):
        rows, mismatches = pages.build_repaginated_alignment(
            [japanese("2001", 0, "日文甲"), japanese("2001", 1, "日文乙")],
            [
                chinese("2001", 0, "中文甲\\n"),
                chinese("2001", 1, "中文乙\\n"),
                chinese("2001", 2, "中文丙"),
            ],
            [{"source_id": "2001", "page_index": 0, "english": "English"}],
        )
        self.assertEqual(mismatches, [{"source_id": "2001", "japanese_pages": 2, "chinese_pages": 3}])
        self.assertEqual(rows[0]["chinese"], "中文甲\\n中文乙\\n中文丙")
        self.assertEqual(rows[0]["page_index"], 0)
        self.assertEqual(rows[0]["status"], "approved")
        self.assertEqual(rows[1]["chinese"], "")
        self.assertEqual(rows[1]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
