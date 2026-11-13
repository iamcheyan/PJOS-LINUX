import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class HeadlessLaunchTest(unittest.TestCase):
    def run_sequence(self, button, expected):
        root = Path(__file__).resolve().parents[1]
        shell = root.parent / "pocketshell"
        runtime = Path("/tmp/pjos-cached-debug/pocket-linux-kms")
        package = shell / "dist/pocketshell.pocket"
        if not runtime.exists() or not package.exists() or not shutil.which("qemu-aarch64"):
            self.skipTest("debug runtime, launcher package and qemu-aarch64 are required")
        library = json.loads((shell / "tests/fixtures/launcher-library.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "library.json"
            fixture.write_text(json.dumps(library))
            launch_log = Path(temp) / "launch.txt"
            env = {**os.environ, "PJOS_TEST_LIBRARY": str(fixture), "PJOS_TEST_BUTTON": button, "PJOS_TEST_LAUNCH_LOG": str(launch_log)}
            subprocess.run(["qemu-aarch64", str(runtime), "--package", str(package), "--headless", "--frames", "45"], env=env, check=True, capture_output=True, timeout=60)
            self.assertEqual(launch_log.read_text(), expected)

    def test_confirm_requests_the_selected_game(self):
        self.run_sequence("confirm", "/storage/content/games/homebrew/Adventure.gba")

    def test_left_wraps_to_last_game_before_confirm(self):
        self.run_sequence("left-confirm", "/storage/content/games/homebrew/Zelda Minish.gba")


if __name__ == "__main__":
    unittest.main()
