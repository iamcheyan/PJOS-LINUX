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


if __name__ == "__main__":
    unittest.main()
