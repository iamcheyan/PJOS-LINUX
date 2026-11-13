#!/usr/bin/env python3
"""Helper cleanup must not kill a debug shell that mentions a helper name."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "overlay/usr/share/pocketshell/System/launch_frontend.sh"


class HelperMatch(unittest.TestCase):
    def test_matches_only_helper_executable_or_script(self):
        script = SOURCE.read_text()
        match = re.search(r"(?ms)^kill_matching\(\) \{\n.*?^\}\n", script)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {
                10001: ["/storage/System/bin/baseos-hotkeys", "--pad-dev", "/dev/input/event1"],
                10002: ["/bin/sh", "/storage/System/baseos-screen-idle"],
                10003: ["/bin/sh", "/tmp/.screen-idle-a1b2"],
                10004: ["ssh", "root@rg34xx", "sh -c 'baseos-hotkeys'"],
                10005: ["/bin/sh", "-c", "echo baseos-screen-idle .screen-idle-"],
            }
            for pid, argv in cases.items():
                process = root / str(pid)
                process.mkdir()
                (process / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in argv) + b"\0")
                (process / "comm").write_text("sh\n" if argv[0] == "/bin/sh" else Path(argv[0]).name + "\n")
            extracted = match.group(0).replace("/proc/[0-9]*", str(root) + "/[0-9]*")
            shell = extracted + "\nkill() { printf '%s\\n' \"$2\"; }\nkill_matching baseos-hotkeys\nkill_matching baseos-screen-idle\nkill_matching .screen-idle-\n"
            result = subprocess.run(["sh", "-c", shell], check=True, text=True, capture_output=True, env=os.environ.copy())
            self.assertEqual(result.stdout.splitlines(), ["10001", "10002", "10003"])


if __name__ == "__main__":
    unittest.main()
