import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "overlay/usr/share/pocketshell/System/launch_frontend.sh"


class LauncherRuntimePrecedenceTest(unittest.TestCase):
    def test_card_deployed_runtime_precedes_the_system_synchronised_launcher_runtime(self):
        text = SCRIPT.read_text()
        self.assertIn('DEPLOYED_RUNTIME="$SD/System/pocketjs/bin/pocketshell/pocket-linux-kms"', text)
        self.assertIn('for candidate_runtime in "$DEPLOYED_RUNTIME" "$LAUNCHER_RUNTIME"', text)


if __name__ == "__main__":
    unittest.main()
