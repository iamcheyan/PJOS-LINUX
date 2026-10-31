#!/usr/bin/env python3
"""Trim the PocketJS workspace down to what the Linux KMS host needs.

Building every device and example crate is pointless for the handheld runtime and,
under qemu, costs tens of minutes. Keep the engine, the Linux and POSIX platform
crates, and the native program shims; move everything else to `exclude` so cargo
neither builds nor resolves it as a workspace member.

Usage: pocketjs-narrow-workspace.py <source-root>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KEEP_PREFIXES = (
    "engine/",
    "platforms/linux/",
    "platforms/posix/",
    "programs/linux-kms",
    "programs/native/",
)


def main() -> int:
    root = Path(sys.argv[1])
    manifest = root / "Cargo.toml"
    text = manifest.read_text()

    match = re.search(r"members\s*=\s*\[(.*?)\]", text, re.S)
    if not match:
        raise SystemExit("workspace.members not found")

    members = [m for m in re.findall(r'"([^"]+)"', match.group(1))]
    keep = [m for m in members if m.startswith(KEEP_PREFIXES)]

    rendered_keep = "\n".join(f'    "{m}",' for m in keep)
    # No `exclude` block: the manifest may already define one, and a directory is
    # only pulled into the workspace when it is listed in `members`.
    block = f"members = [\n{rendered_keep}\n]"
    text = text[: match.start()] + block + text[match.end() :]
    # default-members may name crates we just dropped; build with -p instead.
    text = re.sub(r"\ndefault-members\s*=\s*\[.*?\]\n", "\n", text, flags=re.S)
    manifest.write_text(text)

    print(f"workspace narrowed: kept {len(keep)} of {len(members)} members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
