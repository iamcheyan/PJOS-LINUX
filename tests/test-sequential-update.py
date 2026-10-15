#!/usr/bin/env python3
"""Run real format2 packing, ext4 inspection and updater CLI on disposable files."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import boot_payload as bp
import mkupdate
import slot_image


def run(argv, **kwargs):
    return subprocess.run([str(value) for value in argv], capture_output=True, text=True, **kwargs)


def digest(path, offset=0, size=None):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        stream.seek(offset)
        remaining = size if size is not None else Path(path).stat().st_size - offset
        while remaining:
            part = stream.read(min(4 * 1024 * 1024, remaining))
            if not part: raise AssertionError("short digest input")
            value.update(part); remaining -= len(part)
    return value.hexdigest()


def executable(path, content):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + content + "\n"); path.chmod(0o755)


class SequentialUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("BASEOS_DISPOSABLE_TEST_CONTAINER") != "1" or not Path("/.dockerenv").is_file():
            raise RuntimeError("run through test-sequential-update.sh in its disposable container")
        for tool in ("debugfs", "mke2fs", "mksquashfs"):
            if shutil.which(tool) is None: raise RuntimeError("required host test tool: " + tool)
        cls.temp = tempfile.TemporaryDirectory(prefix="sequential-update-")
        cls.directory = Path(cls.temp.name)
        cls.native = Path(os.environ["BASEOS_NATIVE_FIXTURE"])
        cls.target = json.loads((cls.native / "manifest.json").read_text())["target"]
        with tarfile.open(os.environ["BASEOS_ROOTFS_FIXTURE"]) as archive:
            busybox = next(member for member in archive.getmembers() if member.name.removeprefix("./") == "usr/bin/busybox")
            cls.busybox = archive.extractfile(busybox).read()
        cls.slots = {}; cls.images = {}; cls.policies = {}
        library = cls.directory / "library"; library.mkdir(); (library / "fixture").write_text("host-only library fixture\n")
        sqfs = cls.directory / "usr-lib.sqfs"
        made = run(["mksquashfs", library, sqfs, "-comp", "lz4", "-noappend", "-no-xattrs", "-no-progress", "-processors", "1", "-mkfs-time", "0"])
        if made.returncode: raise RuntimeError(made.stderr)
        for panel in ("old", "boe"):
            root = cls.directory / ("root-" + panel)
            for name in ("etc", "usr/bin", "usr/sbin", "usr/lib", "usr/share/baseos"):
                (root / name).mkdir(parents=True, exist_ok=True)
            (root / "usr/bin/busybox").write_bytes(cls.busybox); (root / "usr/bin/busybox").chmod(0o755)
            executable(root / "usr/sbin/native-health", "exit 0")
            (root / "etc/baseos-release").write_text(f"BASEOS_TARGET={cls.target}\nBASEOS_VERSION=9.1.2\nBASEOS_BUILD=fixture\n")
            shutil.copyfile(sqfs, root / "usr/share/baseos/usr-lib.sqfs")
            output = cls.directory / ("payload-" + panel)
            slot_image.prepare(root, cls.native, cls.target, panel, output)
            slot = cls.directory / ("slot-" + panel + ".img")
            with slot.open("wb") as stream: stream.truncate(bp.SLOT_BYTES)
            made = run(["mke2fs", "-q", "-F", "-t", "ext4", "-O", "^metadata_csum,^metadata_csum_seed,^64bit,^orphan_file", "-b", "4096", "-d", root, slot, str(bp.ROOTFS_BYTES // 4096)])
            if made.returncode: raise RuntimeError(made.stderr)
            with slot.open("r+b") as stream:
                stream.seek(bp.TAIL_OFFSET); stream.write((output / "payload/boot-blob.bin").read_bytes())
            cls.slots[panel] = slot
            cls.policies[panel] = mkupdate.native_policy(slot, cls.target)
            # A sparse card prefix plus the actual complete slot is enough for
            # the real packager's GPT extent reader; no device is involved.
            image = cls.directory / ("card-" + panel + ".img")
            header = bytearray(2048 * 512); header[512:520] = b"EFI PART"
            struct.pack_into("<QII", header, 512 + 72, 2, 8, 128)
            entry = 1024 + 4 * 128
            struct.pack_into("<QQ", header, entry + 32, 2048, 2048 + bp.SLOT_BYTES // 512 - 1)
            header[entry + 56:entry + 68] = "rootfs".encode("utf-16-le")
            with image.open("wb") as destination, slot.open("rb") as source:
                destination.write(header)
                while part := source.read(4 * 1024 * 1024):
                    if part.strip(b"\0"): destination.write(part)
                    else: destination.seek(len(part), 1)
                destination.truncate()
            cls.images[panel] = image
        cls.bundle = cls.directory / "system.bosupd"
        result = cls.package(cls.images["old"], cls.bundle, cls.images["boe"])
        if result.returncode: raise RuntimeError(result.stderr)
        with tarfile.open(cls.bundle) as archive:
            cls.members = {member.name: archive.extractfile(member).read() for member in archive.getmembers()}
        cls.install_cli()

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    @classmethod
    def package(cls, image, output, other=None):
        command = [sys.executable, ROOT / "tools/mkupdate.py", image, cls.target, "9.1.2", "fixture", output]
        if other: command += ["--panel-image", other]
        return run(command)

    @classmethod
    def install_cli(cls):
        # This test runs only in a disposable container. All block-device paths
        # are replaced by a private regular file; only the FDT prefix changes.
        cls.disk = cls.directory / "disk.img"
        cls.fdt = cls.directory / "fdt"; cls.fdt.mkdir()
        cls.flip = cls.directory / "flip.log"
        source = (ROOT / "overlay/usr/sbin/baseos-update").read_text()
        source = source.replace("DISK=/dev/mmcblk0", "DISK=" + str(cls.disk))
        source = source.replace("/sys/firmware/devicetree/base/chosen/", str(cls.fdt) + "/")
        cls.cli = cls.directory / "baseos-update"; cls.cli.write_text(source); cls.cli.chmod(0o755)
        Path("/usr/share/baseos").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "overlay/usr/share/baseos/boot-log.sh", "/usr/share/baseos/boot-log.sh")
        executable("/usr/sbin/gptslot", f'''case "$2" in
geometry) printf '%s\\n' SLOT_ACTIVE=A SLOT_BASE=2048 SLOT_SECTORS=1048576 SLOT_ACTIVE_START=2048 SLOT_INACTIVE_START=1050624 ;;
flip) echo flip >> {cls.flip} ;;
*) exit 2 ;;
esac''')
        executable("/usr/sbin/native-health", "exit 0")
        executable("/usr/bin/baseos-splash", "exit 0")
        executable("/usr/local/bin/reboot", "exit 0")
        executable("/usr/local/bin/sleep", "exit 0")
        for name in ("/mnt/sdcard", "/data", "/run"):
            Path(name).mkdir(parents=True, exist_ok=True)

    def reset_runtime(self, panel):
        shutil.rmtree("/etc/baseos", ignore_errors=True); Path("/etc/baseos").mkdir()
        shutil.rmtree("/data/update", ignore_errors=True)
        self.flip.unlink(missing_ok=True)
        for item in Path("/mnt/sdcard").glob("*.bosupd"): item.unlink()
        shutil.copyfile(self.bundle, "/mnt/sdcard/system.bosupd")
        Path("/etc/baseos-release").write_text(f"BASEOS_TARGET={self.target}\nBASEOS_VERSION=9.1.1\nBASEOS_BUILD=before\n")
        Path("/etc/baseos/boot-payload-format").write_bytes(b"baseos-slot/2\n")
        Path("/etc/baseos/native-panel").write_bytes((panel + "\n").encode())
        abi = bytes.fromhex(self.policies[panel]["native-abi"])
        for name, blob in (("native-abi", abi), ("boot-payload-id", b"\x55" * 32)):
            Path("/etc/baseos", name).write_bytes(blob)
            (self.fdt / ("baseos," + name)).write_bytes(blob)
        with self.disk.open("wb") as stream: stream.truncate((1025 * 1024 * 1024))

    def rewrite_bundle(self, changes):
        with tarfile.open("/mnt/sdcard/system.bosupd", "w") as archive:
            for name, blob in dict(self.members, **changes).items():
                info = tarfile.TarInfo(name); info.size = len(blob)
                archive.addfile(info, io.BytesIO(blob))

    def test_bundle_contains_two_verified_full_slots(self):
        self.assertEqual(set(self.members), {"manifest", "manifest-old", "manifest-boe", "rootfs-old.img.gz", "rootfs-boe.img.gz"})
        for panel in ("old", "boe"):
            metadata = dict(line.split("=", 1) for line in self.members["manifest-" + panel].decode().splitlines())
            self.assertEqual(metadata["native-panel"], panel)
            self.assertEqual(metadata["image-sha256"], digest(self.slots[panel]))
            self.assertEqual(metadata["image-size"], str(bp.SLOT_BYTES))
            self.assertNotIn("native-generation", metadata)
        self.assertNotEqual(self.policies["old"]["boot-payload-id"], self.policies["boe"]["boot-payload-id"])
        self.assertEqual(self.policies["old"]["native-abi"], self.policies["boe"]["native-abi"])

    def test_single_panel_release_is_refused(self):
        output = self.directory / "incomplete.bosupd"
        result = self.package(self.images["old"], output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require both old and boe", result.stderr)
        self.assertFalse(output.exists())

    def test_actual_cli_automatically_applies_correct_panel_then_flips(self):
        for panel in ("old", "boe"):
            with self.subTest(panel=panel):
                self.reset_runtime(panel)
                result = run([self.cli, "apply"])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.flip.read_text(), "flip\n")
                self.assertEqual(digest(self.disk, 513 * 1024 * 1024, bp.SLOT_BYTES), digest(self.slots[panel]))
                self.assertFalse(Path("/mnt/sdcard/system.bosupd").exists())

    def test_actual_cli_refuses_bad_running_or_panel_policy_before_write(self):
        for case in ("abi", "payload", "missing-panel", "panel-no-newline", "panel-symlink", "missing-format"):
            with self.subTest(case=case):
                self.reset_runtime("old")
                if case in ("abi", "payload"):
                    (self.fdt / ("baseos," + ("native-abi" if case == "abi" else "boot-payload-id"))).write_bytes(b"\x66" * 32)
                elif case == "missing-panel": Path("/etc/baseos/native-panel").unlink()
                elif case == "panel-no-newline": Path("/etc/baseos/native-panel").write_bytes(b"old")
                elif case == "panel-symlink":
                    Path("/etc/baseos/native-panel").rename("/etc/baseos/real-panel")
                    Path("/etc/baseos/native-panel").symlink_to("real-panel")
                else: Path("/etc/baseos/boot-payload-format").unlink()
                result = run([self.cli, "apply"])
                self.assertNotEqual(result.returncode, 0, case)
                self.assertFalse(self.flip.exists())
                with self.disk.open("rb") as stream:
                    stream.seek(513 * 1024 * 1024); self.assertEqual(stream.read(4096), bytes(4096))

    def test_actual_cli_refuses_cross_panel_candidate_and_legacy(self):
        for case in ("candidate-panel", "legacy", "missing-variant"):
            with self.subTest(case=case):
                self.reset_runtime("old")
                if case == "candidate-panel":
                    self.rewrite_bundle({"manifest-old": self.members["manifest-old"].replace(b"native-panel=old\n", b"native-panel=boe\n")})
                elif case == "legacy": self.rewrite_bundle({"manifest": self.members["manifest-old"].replace(b"format=baseos-update/2", b"format=baseos-update/1")})
                else: self.rewrite_bundle({"manifest": b"format=baseos-update/2\nvariants=old\n"})
                result = run([self.cli, "apply"])
                self.assertNotEqual(result.returncode, 0, case)
                self.assertFalse(self.flip.exists())

    def test_full_size_ext4_cannot_overlap_tail(self):
        slot = self.slots["old"]
        with slot.open("r+b") as stream:
            stream.seek(1028); original = stream.read(4)
            stream.seek(1028); stream.write(struct.pack("<I", bp.SLOT_BYTES // 4096))
        try:
            with self.assertRaisesRegex(SystemExit, "exactly472MiB"):
                mkupdate.native_policy(slot, self.target)
        finally:
            with slot.open("r+b") as stream: stream.seek(1028); stream.write(original)


if __name__ == "__main__":
    if not os.environ.get("BASEOS_NATIVE_FIXTURE") or not os.environ.get("BASEOS_ROOTFS_FIXTURE"):
        raise SystemExit("set BASEOS_NATIVE_FIXTURE and BASEOS_ROOTFS_FIXTURE to actual host artifact inputs")
    unittest.main(verbosity=2)
