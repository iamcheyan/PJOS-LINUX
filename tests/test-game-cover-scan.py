import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class GameCoverScanTest(unittest.TestCase):
    def test_scans_matching_cover_and_preserves_escaped_names(self):
        script = Path(__file__).resolve().parents[1] / "overlay/usr/share/pocketshell/System/compat/bin/pocketshell-games"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "games"
            system = root / "gba"
            images = system / "images"
            images.mkdir(parents=True)
            rom = system / 'Game "One".gba'
            cover = images / 'Game "One".png'
            rom.write_bytes(b"rom")
            cover.write_bytes(b"cover")
            (system / "No Cover.gba").write_bytes(b"rom")
            alternate = system / "Alternate.gba"
            alternate.write_bytes(b"rom")
            (images / "Alternate-image.jpg").write_bytes(b"cover")
            state = Path(temp) / "state"
            env = {**os.environ, "POCKETSHELL_TEST_GAMES_ROOT": str(root), "POCKETSHELL_GAMES_STATE": str(state)}
            self.assertEqual(subprocess.check_output(["sh", str(script), "capabilities"], env=env, text=True).strip(), "cover-v1")
            subprocess.run(["sh", str(script), "scan"], env=env, check=True, capture_output=True)
            library = json.loads((state / "library.json").read_text())
            items = library["sections"]["games"][0]["items"]
            by_path = {item["path"]: item for item in items}
            self.assertEqual(by_path[str(rom)]["cover"], str(cover))
            self.assertEqual(by_path[str(system / "No Cover.gba")]["cover"], "")
            self.assertEqual(by_path[str(alternate)]["cover"], str(images / "Alternate-image.jpg"))

    def test_legacy_card_scanner_does_not_hide_system_cover_support(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "overlay/usr/sbin/frontend-session").read_text()
        start = source.index('scanner="$SD/System/compat/bin/pocketshell-games"')
        end = source.index('if mountpoint -q "$SD"', start)
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            card = temp_root / "System/compat/bin/pocketshell-games"
            system = temp_root / "system-scanner"
            card.parent.mkdir(parents=True)
            card.write_text("#!/bin/sh\nexit 2\n")
            system.write_text("#!/bin/sh\nprintf 'cover-v1\\n'\n")
            card.chmod(0o755)
            system.chmod(0o755)
            selection = source[start:end].replace("/usr/bin/pocketshell-games", str(system))
            output = subprocess.check_output(["sh", "-c", 'SD="$1"\n' + selection + 'printf "%s" "$scanner"', "sh", temp], text=True)
            self.assertEqual(output, str(system))
            card.write_text("#!/bin/sh\nprintf 'cover-v1\\n'\n")
            output = subprocess.check_output(["sh", "-c", 'SD="$1"\n' + selection + 'printf "%s" "$scanner"', "sh", temp], text=True)
            self.assertEqual(output, str(card))

    def test_scans_data_defined_series_as_valid_json(self):
        script = Path(__file__).resolve().parents[1] / "overlay/usr/share/pocketshell/System/compat/bin/pocketshell-games"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "games"
            series = root / "series" / "example-series"
            rom = series / "gba" / "Example.gba"
            cover = series / "cover.png"
            rom.parent.mkdir(parents=True)
            rom.write_bytes(b"rom")
            cover.write_bytes(b"cover")
            (series / "series.json").write_text("""{
  "schema": "pjos.game-series/v1",
  "id": "example-series",
  "title": "Example series",
  "cover": "cover.png",
  "variants": [
    {
      "id": "en",
      "title": "English",
      "rom": "gba/Example.gba",
      "default": true
    }
  ]
}
""")
            state = Path(temp) / "state"
            env = {**os.environ, "POCKETSHELL_TEST_GAMES_ROOT": str(root), "POCKETSHELL_GAMES_STATE": str(state)}
            subprocess.run(["sh", str(script), "scan"], env=env, check=True, capture_output=True)
            library = json.loads((state / "library.json").read_text())
            series_item = next(
                item
                for group in library["sections"]["games"]
                for item in group["items"]
                if item.get("kind") == "series"
            )
            self.assertEqual(series_item["id"], "example-series")
            self.assertEqual(series_item["variants"], [{
                "id": "en", "title": "English", "path": str(rom), "cover": "", "default": True
            }])

    def test_scans_series_with_multilingual_titles(self):
        script = Path(__file__).resolve().parents[1] / "overlay/usr/share/pocketshell/System/compat/bin/pocketshell-games"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "games"
            series = root / "series" / "fe-binding-blade"
            rom_cn = series / "gba" / "FE6_CN.gba"
            rom_ja = series / "gba" / "FE6_JA.gba"
            cover = series / "cover.png"
            rom_cn.parent.mkdir(parents=True)
            rom_cn.write_bytes(b"rom")
            rom_ja.write_bytes(b"rom")
            cover.write_bytes(b"cover")
            (series / "series.json").write_text("""{
  "schema": "pjos.game-series/v1",
  "id": "fe-binding-blade",
  "title": "火焰之纹章：封印之剑",
  "title_zh": "火焰之纹章：封印之剑",
  "title_en": "Fire Emblem: The Binding Blade",
  "title_ja": "ファイアーエムブレム 封印の剣",
  "cover": "cover.png",
  "variants": [
    {
      "id": "zh-Hans",
      "title": "简体中文（CGP汉化版）",
      "title_zh": "简体中文（CGP汉化版）",
      "title_en": "Simplified Chinese (CGP)",
      "title_ja": "簡体字中国語（CGP版）",
      "rom": "gba/FE6_CN.gba",
      "default": true
    },
    {
      "id": "ja",
      "title": "日版",
      "title_zh": "日版",
      "title_en": "Japanese",
      "title_ja": "日本語版",
      "rom": "gba/FE6_JA.gba"
    }
  ]
}
""")
            state = Path(temp) / "state"
            env = {**os.environ, "POCKETSHELL_TEST_GAMES_ROOT": str(root), "POCKETSHELL_GAMES_STATE": str(state)}
            subprocess.run(["sh", str(script), "scan"], env=env, check=True, capture_output=True)
            library = json.loads((state / "library.json").read_text())
            series_item = next(
                item
                for group in library["sections"]["games"]
                for item in group["items"]
                if item.get("kind") == "series"
            )
            self.assertEqual(series_item["title_zh"], "火焰之纹章：封印之剑")
            self.assertEqual(series_item["title_en"], "Fire Emblem: The Binding Blade")
            self.assertEqual(series_item["title_ja"], "ファイアーエムブレム 封印の剣")
            self.assertEqual(series_item["variants"][0]["title_en"], "Simplified Chinese (CGP)")
            self.assertEqual(series_item["variants"][0]["title_ja"], "簡体字中国語（CGP版）")
            self.assertEqual(series_item["variants"][1]["title_en"], "Japanese")
            self.assertEqual(series_item["variants"][1]["title_ja"], "日本語版")


if __name__ == "__main__":
    unittest.main()
