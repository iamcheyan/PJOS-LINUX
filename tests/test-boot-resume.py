#!/usr/bin/env python3
"""Boot resume must be opt-in, target an existing foreground app/ROM, and reject stale markers."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "overlay/usr/share/pocketshell/System/launch_frontend.sh"


def resume_block() -> str:
    match = re.search(
        r"# --- boot resume selection.*?# --- end boot resume selection ---\n",
        SOURCE.read_text(),
        re.S,
    )
    if match is None:
        raise AssertionError("boot resume selection block not found")
    return match.group(0)


class BootResumeTest(unittest.TestCase):
    def run_selection(self, enabled, kind, target, make_rom=False, make_app=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            apps = root / "apps"
            storage.mkdir()
            apps.mkdir()
            if kind == "rom" and make_rom and not target:
                target = str(storage / "game.gba")
            conf = root / "ui-settings.conf"
            conf.write_text("bootResume=" + ("on\n" if enabled else "off\n"))
            marker = root / "resume.state"
            marker.write_text(f"kind={kind}\ntarget={target}\n")
            if make_rom:
                (storage / target.removeprefix(str(storage) + "/")).write_text("rom")
            if make_app:
                (apps / f"{target}.pocket").write_text("app")
            shell = (
                f"SD={root / 'sd'}\n"
                f"SETTINGS_CONF={conf}\n"
                f"APP_DIR={apps}\n"
                f"STORAGE_PREFIX={storage}\n"
                f"RESUME={marker}\n"
                + resume_block()
                + "\nboot_resume_enabled && resume_target\n"
            )
            result = subprocess.run(
                ["sh", "-c", shell],
                env=dict(os.environ),
                text=True,
                capture_output=True,
            )
            return result.returncode, result.stdout.strip()

    def test_default_off_does_not_resume(self):
        code, output = self.run_selection(False, "rom", "/storage/kb.gba")
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")

    def test_missing_setting_defaults_off(self):
        with tempfile.TemporaryDirectory() as directory:
            shell = (
                f"SETTINGS_CONF={Path(directory) / 'missing.conf'}\n"
                + resume_block()
                + "\nboot_resume_enabled\n"
            )
            result = subprocess.run(["sh", "-c", shell], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_existing_rom_resumes(self):
        code, output = self.run_selection(True, "rom", "", make_rom=True)
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith("rom\t"))

    def test_missing_or_removed_rom_falls_back(self):
        code, output = self.run_selection(
            True, "rom", "/storage/game.gba", make_rom=False
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")

    def test_invalid_rom_path_falls_back(self):
        code, output = self.run_selection(
            True, "rom", "/storage/../game.gba", make_rom=False
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")

    def test_existing_app_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            apps = Path(directory) / "apps"
            apps.mkdir()
            (apps / "kanade.pocket").write_text("app")
            code, output = self.run_selection(
                True, "app", "kanade", make_app=True
            )
            self.assertEqual(code, 0)
            self.assertEqual(output, "app\tkanade")

    def test_removed_app_falls_back(self):
        code, output = self.run_selection(True, "app", "kanade", make_app=False)
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
