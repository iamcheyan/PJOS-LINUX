import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path


class FsBridgeTest(unittest.TestCase):
    def test_fs_list_and_read(self):
        project = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(project / "src/apply-pocketjs-fs.py"))["HELPER"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "folder_a").mkdir()
            (root / "folder_b").mkdir()
            (root / "file1.txt").write_text("Hello, PocketJS FS!")
            (root / "file2.bin").write_bytes(b"\x00\x01\x02\x03")
            (root / ".hidden").write_text("hidden")
            (root / ".config").mkdir()

            source = root / "fs_test.rs"
            source.write_text(helper + '''
fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args[1] == "list" {
        print!("{}", fs_list(&args[2]));
    } else if args[1] == "read" {
        print!("{}", fs_read(&args[2]));
    }
}
''')
            executable = root / "fs_test"
            subprocess.run(["rustc", str(source), "-o", str(executable)], check=True)

            def call(*args):
                return subprocess.check_output([str(executable), *args], text=True)

            listing = call("list", str(root))
            lines = listing.splitlines()
            # Directories should be listed first, including .config, excluding .hidden
            self.assertIn(f"dir\t.config\t{Path(root / '.config').stat().st_size}", lines)
            self.assertIn(f"dir\tfolder_a\t{Path(root / 'folder_a').stat().st_size}", lines)
            self.assertIn(f"dir\tfolder_b\t{Path(root / 'folder_b').stat().st_size}", lines)
            self.assertIn("file\tfile1.txt\t19", lines)
            self.assertIn("file\tfile2.bin\t4", lines)
            self.assertFalse(any(".hidden" in line for line in lines))

            # Test read text
            self.assertEqual(call("read", str(root / "file1.txt")), "Hello, PocketJS FS!")

            # Test read binary
            self.assertEqual(call("read", str(root / "file2.bin")), "error:binary_file")

            # Test read non-existent
            self.assertTrue(call("read", str(root / "nonexistent.txt")).startswith("error:"))


if __name__ == "__main__":
    unittest.main()
