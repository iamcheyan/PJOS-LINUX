#!/bin/sh
# Build pocket-linux-kms as an aarch64-unknown-linux-musl static binary.
#
# BaseOS ships glibc 2.35, so the ROCKNIX cross toolchain's output (GLIBC_2.44)
# cannot load there. The runtime that BaseOS actually runs is a musl static
# build, so this script rebuilds the same ABI inside an arm64 Alpine container.
#
# Inputs:  the pinned PocketJS source tarball from the ROCKNIX package tree
#          (sources/pocketjs-runtime/) and src/apply-pocketjs-input.py.
# Output:  work/pocketjs-runtime/pocket-linux-kms
#
# Usage: ./build-pocketjs-runtime-musl.sh
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
ROCKNIX="${PJOS_ROCKNIX_TREE:-$HOME/development/.worktrees/rocknix-h700-pocketjs-kms-build}"
VERSION=e6770376626a4de5c93eaa6fb048e7e9ffb81f9f
TARBALL="$ROCKNIX/sources/pocketjs-runtime/pocketjs-runtime-$VERSION.tar.gz"
BUILD="$ROCKNIX/build.ROCKNIX-H700.aarch64/build/pocketjs-runtime-$VERSION"
# The profile must be the one the card's boot.pocket was built against, or the
# runtime rejects it with Admission(ProfileHashMismatch). BaseOS's launcher uses
# the 360x240@2 profile exported from the main ROCKNIX checkout; some feature
# worktrees carry a 720x480@1 variant that does not match it.
PROFILE="${PJOS_PROFILE_RS:-$HOME/development/rocknix/build.ROCKNIX-H700.aarch64/build/pocketjs-runtime-e6770376626a4de5c93eaa6fb048e7e9ffb81f9f/generated/pocket_profile.rs}"
CARGO_CACHE="$ROCKNIX/build.ROCKNIX-H700.aarch64/toolchain/cargo_home"
OUT="$HERE/work/pocketjs-runtime/pocket-linux-kms"

[ -f "$TARBALL" ] || { echo "missing $TARBALL" >&2; exit 1; }
[ -f "$PROFILE" ] || { echo "missing profile export $PROFILE (run the host build first)" >&2; exit 1; }

mkdir -p "$HERE/work/pocketjs-runtime"

docker run --rm --platform linux/arm64 \
  -e DEBIAN_FRONTEND=noninteractive \
  -v "$TARBALL:/in/src.tar.gz:ro" \
  -v "$PROFILE:/in/pocket_profile.rs:ro" \
  -v "$HERE/src/apply-pocketjs-input.py:/in/apply-input.py:ro" \
  -v "$CARGO_CACHE:/cargo-cache" \
  -v "$HERE/work/pocketjs-runtime:/out" \
  debian:bookworm sh -euc '
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends \
      build-essential musl-tools clang libclang-dev pkg-config \
      curl ca-certificates python3 xz-utils >/dev/null

    # Host toolchain is gnu: bindgen (rquickjs-sys) dlopen()s libclang, which a
    # static-musl host cannot do. Only the target is musl.
    export RUSTUP_HOME=/tmp/rustup CARGO_HOME=/cargo-cache
    curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
      --default-toolchain 1.98.1 --default-host aarch64-unknown-linux-gnu >/dev/null
    export PATH=/tmp/rustup/toolchains/1.98.1-aarch64-unknown-linux-gnu/bin:/cargo-cache/bin:$PATH
    rustup target add aarch64-unknown-linux-musl >/dev/null
    rustc -V

    mkdir -p /work/src && tar -xzf /in/src.tar.gz -C /work/src --strip-components=1
    cd /work/src

    # Same workspace narrowing the ROCKNIX recipe performs: the Linux KMS host
    # plus the bindings shim that pulls rquickjs in.
    python3 - <<PY
import re, tomllib
from pathlib import Path
root = Path("/work/src")
lock = tomllib.loads((root / "Cargo.lock").read_text())
quickjs = [p for p in lock["package"] if p["name"] == "rquickjs" and p.get("source", "").startswith("registry+")]
assert len(quickjs) == 1, "expected one pinned rquickjs"
shim = root / "programs/rocknix-bindings"
(shim / "src").mkdir(parents=True, exist_ok=True)
(shim / "src/lib.rs").write_text("")
(shim / "Cargo.toml").write_text(
    "[package]\nname = \"rocknix-pocketjs-bindings\"\nversion = \"0.0.0\"\nedition = \"2021\"\n"
    "[dependencies]\n"
    "rquickjs = { version = \"=" + quickjs[0]["version"] + "\", features = [\"bindgen\"] }\n")
text = (root / "Cargo.toml").read_text()
for key in ["members", "default-members"]:
    text, n = re.subn(r"(?ms)^" + key + r" = \[.*?^\]",
                      key + " = [\"programs/linux-kms\", \"programs/rocknix-bindings\"]", text, count=1)
    assert n == 1, key
(root / "Cargo.toml").write_text(text)
print("workspace narrowed")
PY

    python3 /in/apply-input.py /work/src

    export LIBCLANG_PATH=/usr/lib/llvm-14/lib
    export POCKETJS_PROFILE_RS=/in/pocket_profile.rs
    export CARGO_TARGET_DIR=/work/target
    export CC_aarch64_unknown_linux_musl=musl-gcc
    export AR_aarch64_unknown_linux_musl=ar
    export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc
    export RUSTFLAGS="-C target-feature=+crt-static"
    cargo build --release --offline \
      --manifest-path /work/src/Cargo.toml \
      --target aarch64-unknown-linux-musl \
      --package pocket-linux-kms --package rocknix-pocketjs-bindings

    install -m 0755 /work/target/aarch64-unknown-linux-musl/release/pocket-linux-kms /out/pocket-linux-kms
    file /out/pocket-linux-kms || true
  '

echo
echo "runtime: $OUT"
sha256sum "$OUT"
