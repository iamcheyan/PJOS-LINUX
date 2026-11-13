from pathlib import Path
import subprocess
import tempfile
import unittest


class PlayerPathBridgeTest(unittest.TestCase):
    def test_card_shims_and_kanade_handoff_are_idempotent(self):
        root = Path(__file__).resolve().parents[1]
        patch = root / "src/apply-pocketjs-player-path.py"
        fixture = '''
let player = ["/storage/dev/usr/bin/pocketshell-play", "/usr/bin/pocketshell-play"];
match fields {
    ["LAUNCH", app] if ["disk", "xmplayer"].contains(app) => {
        match run("systemd-run", &["--unit=pocketjs-launcher", "--collect", "--no-block", "/usr/bin/pocketjs-native-launch", app]) {
        }
    }
}
'''
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "bridge.rs"
            source.write_text(fixture)
            subprocess.run(["python3", str(patch), str(source)], check=True)
            once = source.read_text()
            subprocess.run(["python3", str(patch), str(source)], check=True)
            self.assertEqual(source.read_text(), once)
            self.assertIn('["disk", "xmplayer", "kanade"]', once)
            self.assertIn('"/storage/System/compat/bin/pocketshell-play"', once)
            self.assertIn('"/storage/System/compat/bin/pocketjs-native-launch"', once)


if __name__ == "__main__":
    unittest.main()
