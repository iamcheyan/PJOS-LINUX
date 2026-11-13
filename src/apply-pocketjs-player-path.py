#!/usr/bin/env python3
"""Prefer the card's player shim and expose the existing Kanade handoff."""
from pathlib import Path
import sys


def main(path):
    source = Path(path)
    text = source.read_text()
    old = 'let player = ["/storage/dev/usr/bin/pocketshell-play", "/usr/bin/pocketshell-play"]'
    new = 'let player = ["/storage/System/compat/bin/pocketshell-play", "/storage/dev/usr/bin/pocketshell-play", "/usr/bin/pocketshell-play"]'
    if new not in text:
        if text.count(old) != 1:
            raise SystemExit("player-path: unsupported player anchor")
        text = text.replace(old, new, 1)
    old_launch = '["LAUNCH", app] if ["disk", "xmplayer"].contains(app)'
    new_launch = '["LAUNCH", app] if ["disk", "xmplayer", "kanade"].contains(app)'
    if new_launch not in text:
        if text.count(old_launch) != 1:
            raise SystemExit("player-path: unsupported launch anchor")
        text = text.replace(old_launch, new_launch, 1)
    old_call = 'match run("systemd-run", &["--unit=pocketjs-launcher", "--collect", "--no-block", "/usr/bin/pocketjs-native-launch", app]) {'
    new_call = '''let native_launcher = if std::path::Path::new("/storage/System/compat/bin/pocketjs-native-launch").is_file() {
                "/storage/System/compat/bin/pocketjs-native-launch"
            } else {
                "/usr/bin/pocketjs-native-launch"
            };
            match run("systemd-run", &["--unit=pocketjs-launcher", "--collect", "--no-block", native_launcher, app]) {'''
    if new_call not in text:
        if text.count(old_call) != 1:
            raise SystemExit("player-path: unsupported native launcher anchor")
        text = text.replace(old_call, new_call, 1)
    source.write_text(text)


if __name__ == "__main__":
    main(sys.argv[1])
