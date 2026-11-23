# M1: content baseline and offline build handoff

**Reference:** local `main` at `2423f9c134598a11e561ff124efd939528125033`. Its checkout was dirty (34 modified, 17 deleted, 19 untracked status entries); the exact local snapshot is `work/m1/main-status.txt`. No checkout files were reset or included in the source baseline. No builds, downloads, device probes or flashes were performed.

| Evidence | Entries | SHA-256 of content manifest |
|---|---:|---|
| Pristine `main:overlay` (source baseline for all H700 boards) | 107 | `8b99f1b8445b124af2a3de36d4bd84cd3f7543f36e95d1c2e6421aa4cc6fadaa` |
| Cached RG34XX `rootfs.tar` (historical output, **not** a demonstrated build of this commit) | 3144 | `b9a85f734d6c699d67d6445e73c4178131dbcc9efd9649dfa06c4fc90a1589dd` |

For a pristine-main comparison the M1 baseline is **overlay only**, as allowed in [07-migration](07-migration.md). There was no attributable full rootfs for RG40XXV or RG34XX. A difference from the historical RG34XX output alone cannot be attributed to the feature. The manifest records paths, type, mode, numeric ownership, regular-file content, symlink targets and device numbers; not timestamps, ACLs, xattrs or hardlink topology. Read the tar directly to retain numeric ownership.

```sh
set -eu
rev=2423f9c134598a11e561ff124efd939528125033
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
mkdir -p work/m1
git -c tar.umask=0022 archive --format=tar "$rev:overlay" > "$t/overlay.tar"
python3 tools/content_manifest.py "$t/overlay.tar" > work/m1/main-overlay.manifest
# Before rebuilding: rootfs.tar is an output and will be overwritten.
python3 tools/content_manifest.py work/rg34xx/rootfs.tar > work/m1/rg34xx-rootfs.manifest
sha256sum work/m1/*.manifest
```

## Inputs staged in ignored `work/`

The three prepared inputs are present for **all 11 H700 targets**, including RG40XXV and RG34XX. The local `baseos-prepared-20260914.tar.zst` matched `manifest/prepared/bundle.sha256` (`86a0186b5ac8ab907dc1d5c24220c9fcd94f38dd9dc3fddb7fb5cf59d4c7719f`). Its 22 members are boot prefixes and stock harvests; each extracted file was hashed against its board's committed `manifest/prepared/<target>.json`, copied as `work/<target>/source.json`. This establishes input identity, not bootability. For manual offline restoration GNU `zstd -dc --long=31` is needed for this bundle's window size.

| Canonical RG34XX copy | File SHA-256 |
|---|---|
| `source.json` | `c48607389fc7cf940e8db0445331c2c48cb5acd18ff478ae93fef56d18d0ad06` |
| `boot-prefix.img` | `fb75bc4c835fa74ff41c0a1fdbe79b8871a960fc249716847fb7be529835c3c3` |
| `stock-harvest.tar` | `d1c837671fafb599862b4906c90e96b317d3c9b7caf643398cdef987473b8d79` |
| `rootfs.tar` | `2e99d947b5de87c30f207cfae450e507d9e59d1fcb635d865f98d0b0302bfc29` |

`work/m1/input.sha256` (SHA-256 `b5976d9588669e10f33653a95693be28d8f93722301c91062c6188af7fe632bb`) covers those four copies and all 17 shared tool files, including `.stamp`. All matched with `(cd work && sha256sum -c m1/input.sha256)` before rebuilding. The local PocketJS runtime copy also matched its source (`3532f2c9e483d83ad9e0608bc5fffefe9813e5b251827e8396e4b7244d12b416`); package compatibility remains a build gate.

## Production commands (feature worktree, not run)

**Rootfs comparison:** the copied tool stamp differs from `tools/tools-stamp.sh`; rebuild tools rather than replacing the stamp. Ensure the tool build's dependencies are available before attempting an offline build.

```sh
set -eu
./build-tools.sh
./build-rootfs.sh rg34xx
python3 tools/content_manifest.py work/rg34xx/rootfs.tar > work/m1/rg34xx-feature.manifest
diff -u work/m1/rg34xx-rootfs.manifest work/m1/rg34xx-feature.manifest
```

**Production release:** run `./build-all.sh rg34xx rg40xxv` for the representatives (or pass all 11 H700 IDs explicitly). It refreshes stale tools, builds rootfs, runs QEMU smoke, builds the native loader, then packages the image zip and `.bosupd` under each target. Requires ARM64-capable Docker, `zip`, `clang`, rustup `ld.lld`, Python with capstone/unicorn (`BASEOS_NATIVE_PYTHON` can select it), and a running `baseos-h700-mainline` container. At collection time `clang` was not on PATH and that named container was not running. Neither release production nor device boot is asserted.

**TG5040:** the local TrimUI SD base 1.1.0 cache contains card-side software, including RetroArch assets, not a verified standalone firmware input set. The prepared bundle has no TG5040 members. No matching board-specific stock partition map/boot prefix, kernel/DTB, or module/library harvest with trusted source manifest was identified in the local caches inspected. Keep TG5040 card-only; do not substitute H700 inputs or extract firmware from a live device. No private device identifiers or vendor payloads belong in Git.
