import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest


class FavoritesBridgeTest(unittest.TestCase):
    def test_favorites_persist_and_toggle(self):
        project = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(project / "src/apply-pocketjs-favorites.py"))["HELPER"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "config/favorites.txt"
            helper = helper.replace('"/storage/.config/pocketjs/favorites.txt"', json.dumps(str(target)))
            source = root / "favorites.rs"
            source.write_text(helper + '''
fn main() {
    let args: Vec<String> = std::env::args().collect();
    print!("{}", launcher_favorites(&args[1], args.get(2).map(String::as_str).unwrap_or("")));
}
''')
            executable = root / "favorites"
            subprocess.run(["rustc", str(source), "-o", str(executable)], check=True)
            def call(*args):
                return subprocess.check_output([str(executable), *args], text=True)
            path = "/storage/content/games/My Game.gba"
            self.assertEqual(call("toggle", path), "added")
            self.assertEqual(call("list"), path + "\n")
            self.assertEqual(call("toggle", "relative.gba"), "error: invalid favorite")
            self.assertEqual(call("toggle", path), "removed")
            self.assertEqual(call("list"), "")


if __name__ == "__main__":
    unittest.main()
