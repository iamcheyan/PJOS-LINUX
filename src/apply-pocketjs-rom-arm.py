#!/usr/bin/env python3
"""Add one bridge arm so a PocketJS app can hand a ROM to the supervisor.

The pinned launcher bridge already knows how to switch to an installed package:
it writes `/storage/System/pocketjs/active` and lets `launch_frontend.sh` restart
with that target. A ROM is the same hand-off with a different payload, so this
adds a single arm rather than a second protocol:

    ROM<TAB>launch<TAB>/storage/content/games/<system>/<title>.<ext>

The supervisor resolves the marker to `apps/<name>.pocket` first and then to a
card ROM, so both targets travel the same path.

Deliberately minimal: one arm plus one helper, anchored on the LAUNCH arm that
every revision of this file contains. It does not touch Wi-Fi, Bluetooth, volume
or brightness, which is where the older BaseOS bridge rewrite diverged.

    python3 src/apply-pocketjs-rom-arm.py <pocketshell-launcher.rs>
"""
from pathlib import Path
import sys

ARM_ANCHOR = '        ["LAUNCH", app] if ["disk", "xmplayer"].contains(app) => {'

ARM = '''        ["ROM", "launch", path] if rom_ready(path) => rom_launch(path),
'''

HELPER = '''
// ── ROM hand-off ────────────────────────────────────────────────────────────
// The supervisor owns /dev/fb0: this only records the target and exits the
// runtime, exactly like the installed-app arm above.
fn rom_ready(path: &str) -> bool {
    if path.is_empty() || path.len() > 4096 || !path.starts_with("/storage/") {
        return false;
    }
    let lower = path.to_ascii_lowercase();
    if !lower.ends_with(".gba") && !lower.ends_with(".gb") && !lower.ends_with(".gbc") {
        return false;
    }
    // No existence check: the guest does not share the supervisor's view of the
    // card, so a missing file here is not the same as a missing ROM. The
    // supervisor validates the target before it plays anything.
    !path.split('/').any(|part| part == "." || part == "..")
}

fn rom_launch(path: &str) -> String {
    let marker = "/storage/System/pocketjs/active";
    let file = std::path::Path::new(path);
    let name = file.file_stem().and_then(|stem| stem.to_str()).unwrap_or("");
    let ext = file.extension().and_then(|value| value.to_str()).unwrap_or("");
    if name.is_empty() || ext.is_empty() || std::fs::write(marker, format!("{}.{}", name, ext)).is_err() {
        return "error:marker".into();
    }
    let pid = std::process::id();
    let _ = Command::new("/bin/sh")
        .args(["-c", &format!("sleep 0.4; kill -9 {}", pid)])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
    format!("launching:{}.{}", name, ext)
}
'''


def main(source_path: str) -> int:
    source = Path(source_path)
    text = source.read_text()

    if "fn rom_launch(" in text and '"ROM", "launch"' in text:
        print("already applied: ROM launch arm")
        return 0
    if text.count(ARM_ANCHOR) != 1:
        raise SystemExit(
            f"anchor for the LAUNCH arm appears {text.count(ARM_ANCHOR)} times"
        )

    text = text.replace(ARM_ANCHOR, ARM + ARM_ANCHOR, 1)
    text = text.rstrip() + "\n" + HELPER
    source.write_text(text)
    print("applied ROM launch arm")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
