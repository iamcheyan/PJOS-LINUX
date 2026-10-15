#!/usr/bin/env python3
"""Stage a policy-specific sequential slot; release updates bundle both panels."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import boot_payload

ROOT = Path(__file__).resolve().parents[1]


def prepare(root, native, target, panel, output):
    if output.exists():
        raise ValueError("fresh boot-payload output directory required")
    manifest = json.loads((native / "manifest.json").read_text())
    if manifest["target"] != target or panel not in ("old", "boe"):
        raise ValueError("native target or panel policy differs")
    parent = root / "etc/baseos"
    if (root / "etc").is_symlink() or parent.is_symlink():
        raise ValueError("boot policy parent must be a real directory")
    parent.mkdir(exist_ok=True)
    if (parent / "native-generation").exists() or (parent / "native-generation").is_symlink():
        raise ValueError("format2 rootfs must not contain a per-card native-generation")
    abi = boot_payload.native_abi_id(manifest)
    for name, blob in (("native-abi", abi), ("native-panel", (panel + "\n").encode()),
                       ("boot-payload-format", b"baseos-slot/2\n")):
        path = parent / name
        if path.exists() or path.is_symlink():
            raise ValueError("rootfs already contains boot policy: " + name)
        path.write_bytes(blob)
        path.chmod(0o644)
    marker = parent / "boot-payload-id"
    if marker.exists() or marker.is_symlink():
        raise ValueError("rootfs already contains a boot-payload-id")
    output.mkdir(parents=True)
    source = output / "rootfs.tar"
    # Stable ordering and timestamps keep the mutable ID stable for equal input
    # trees. Preserve modes, links and numeric owners from the assembled root.
    with tarfile.open(source, "w", format=tarfile.USTAR_FORMAT) as archive:
        for path in sorted(root.rglob("*")):
            info = archive.gettarinfo(str(path), arcname=str(path.relative_to(root)))
            info.mtime = 0
            info.uname = info.gname = ""
            if info.isreg():
                with path.open("rb") as handle: archive.addfile(info, handle)
            else:
                archive.addfile(info)
    payload = output / "payload"
    subprocess.run([sys.executable, str(ROOT / "experiments/h700-boot-speed/sequential/build-payload.py"),
                    str(native), str(source), str(root / "usr/share/baseos/usr-lib.sqfs"), str(payload)], check=True)
    if (payload / "native-abi").read_bytes() != abi:
        raise ValueError("packer changed the staged native ABI")
    identity = (payload / "root-build-id").read_bytes()
    if len(identity) != 32:
        raise ValueError("packer emitted malformed root build identity")
    marker.write_bytes(identity)
    marker.chmod(0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("prepare")
    stage.add_argument("root", type=Path)
    stage.add_argument("native", type=Path)
    stage.add_argument("target")
    stage.add_argument("panel", choices=("old", "boe"))
    stage.add_argument("output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("slot", type=Path)
    verify.add_argument("target")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.root, args.native, args.target, args.panel, args.output)
    else:
        from mkupdate import native_policy
        policy = native_policy(args.slot, args.target)
        if policy.get("boot-payload-format") != "baseos-slot/2":
            raise ValueError("slot is not the sequential format")
        print(json.dumps(policy, sort_keys=True))


if __name__ == "__main__": main()
