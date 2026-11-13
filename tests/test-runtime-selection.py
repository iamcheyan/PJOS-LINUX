from pathlib import Path
import subprocess
import tempfile
import unittest


class RuntimeSelectionTest(unittest.TestCase):
    def test_selects_runtime_that_admits_package(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "overlay/usr/share/pocketshell/System/launch_frontend.sh").read_text()
        start = source.index("select_runtime() {")
        end = source.index("\n}\n", start) + 3
        function = source[start:end]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "System/pocketjs/bin"
            launcher = directory / "launcher/pocket-linux-kms"
            legacy = directory / "pocket-linux-kms"
            launcher.parent.mkdir(parents=True)
            for path in (launcher, legacy):
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o755)
            shell = '''
SD=$1
LAUNCHER_RUNTIME="$SD/System/pocketjs/bin/launcher/pocket-linux-kms"
check_package() {
    case "$1:$RUNTIME" in
      new:*/launcher/pocket-linux-kms|old:*/bin/pocket-linux-kms) return 0 ;;
    esac
    return 1
}
''' + function + '''
select_runtime new || exit 1
printf '%s\\n' "$RUNTIME"
select_runtime old || exit 1
printf '%s\\n' "$RUNTIME"
if select_runtime bad; then exit 1; fi
'''
            result = subprocess.check_output(["sh", "-c", shell, "sh", temp], text=True)
            self.assertEqual(result.splitlines(), [str(launcher), str(legacy)])

    def test_system_installs_new_runtime_without_replacing_legacy(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "overlay/usr/sbin/frontend-session").read_text()
        marker = '    && [ -x /usr/share/baseos/pocketjs/launcher/pocket-linux-kms ]'
        position = source.index(marker)
        start = source.rfind('if mountpoint -q "$SD"', 0, position)
        end = source.index("# Refresh the games catalogue", position)
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            card = temp_root / "card"
            binary = card / "System/pocketjs/bin/pocket-linux-kms"
            binary.parent.mkdir(parents=True)
            binary.write_text("legacy runtime")
            (card / "System/launch_frontend.sh").write_text("frontend")
            image_runtime = temp_root / "image-runtime"
            image_runtime.write_text("new launcher runtime")
            image_runtime.chmod(0o755)
            block = source[start:end].replace("/usr/share/baseos/pocketjs/launcher/pocket-linux-kms", str(image_runtime))
            shell = 'SD="$1"\nmountpoint() { return 0; }\nlog() { :; }\n' + block
            subprocess.run(["sh", "-c", shell, "sh", str(card)], check=True)
            self.assertEqual(binary.read_text(), "legacy runtime")
            self.assertEqual((binary.parent / "launcher/pocket-linux-kms").read_text(), "new launcher runtime")


if __name__ == "__main__":
    unittest.main()
