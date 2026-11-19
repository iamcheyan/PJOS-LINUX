import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path


class SavesBridgeTest(unittest.TestCase):
    def test_saves_list_and_export(self):
        project = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(project / "src/apply-pocketjs-saves.py"))["HELPER"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Fake saves tree
            states_dir = root / "storage/pocketshell/states/mGBA"
            states_dir.mkdir(parents=True)
            (states_dir / "golden-sun.state.auto").write_text("dummy golden sun state")
            zelda_state = states_dir / "zelda.state"
            zelda_state.write_bytes(b"\x00" * 0x62000)

            # Test rust code
            test_rs = helper.replace("/storage", str(root / "storage")) + '''
fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args[1] == "list" {
        print!("{}", saves_list());
    } else if args[1] == "export" {
        print!("{}", saves_export(&args[2]));
    } else if args[1] == "export_all" {
        print!("{}", saves_export_all());
    }
}
'''
            source = root / "saves_test.rs"
            source.write_text(test_rs)
            executable = root / "saves_test"
            subprocess.run(["rustc", str(source), "-o", str(executable)], check=True)

            def call(*args):
                return subprocess.check_output([str(executable), *args], text=True)

            listing = call("list")
            self.assertIn("黄金太阳：开启的封印", listing)
            self.assertIn("塞尔达传说：缩小帽", listing)
            self.assertIn("golden-sun.state.auto", listing)

            # Test export single
            export_res = call("export", str(states_dir / "golden-sun.state.auto"))
            self.assertTrue(export_res.startswith("ok\t"))
            exported_file = Path(export_res.split("\t")[1])
            self.assertTrue(exported_file.exists())
            self.assertEqual(exported_file.read_text(), "dummy golden sun state")

            # Test export all
            export_all_res = call("export_all")
            self.assertTrue(export_all_res.startswith("ok\t2\t"))


if __name__ == "__main__":
    unittest.main()
