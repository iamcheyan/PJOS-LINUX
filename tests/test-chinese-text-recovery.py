#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.chinese_text_recovery.decode_chinese_text import decode_text


class ChineseTextRecoveryTest(unittest.TestCase):
    def test_known_variables_are_preserved_and_unknown_controls_are_not_deleted(self):
        decoded, missing = decode_text(
            "[C06:00][C06:01][C02:03][C03:00:C2][C07:49:02][G4:01]",
            {"G4:01": "的"},
        )
        self.assertEqual(decoded, "{player}{1}[C07:49:02]的")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
