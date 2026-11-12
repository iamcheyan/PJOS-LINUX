#!/bin/sh
# Build an existing PocketJS source checkout with the BaseOS bridge patches.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${PJOS_RUNTIME_SOURCE:?Set PJOS_RUNTIME_SOURCE to the existing PocketJS source checkout}"
: "${PJOS_PROFILE_RS:?Set PJOS_PROFILE_RS to the profile exported for the installed package}"
SCRIPTS=${PJOS_BRIDGE_SCRIPTS:-$HOME/development/rocknix/projects/ROCKNIX/packages/apps/pocketjs-runtime/scripts}
BUILD=${PJOS_RUNTIME_BUILD:-$HERE/work/runtime-local}
TOOLCHAIN=${PJOS_RUST_TOOLCHAIN:-1.98.1}
TARGET=aarch64-unknown-linux-gnu
[ -f "$PJOS_RUNTIME_SOURCE/Cargo.toml" ]
[ -f "$PJOS_PROFILE_RS" ]
[ -f "$SCRIPTS/patch-runtime.py" ]
mkdir -p "$BUILD/src" "$HERE/work/pocketjs-runtime"
# Work only on a staging copy; preserve the source checkout and build cache.
rsync -a --exclude target --exclude node_modules --exclude .git \
    "$PJOS_RUNTIME_SOURCE/" "$BUILD/src/"
python3 "$SCRIPTS/patch-runtime.py" "$BUILD/src"
python3 "$HERE/src/apply-pocketjs-input.py" "$BUILD/src"
BRIDGE="$BUILD/src/engine/guest-rquickjs/src/pocketshell_launcher.rs"
for patch in rom-arm battery panel settings system-info network-bridge power-bridge restore kanade; do
    python3 "$HERE/src/apply-pocketjs-$patch.py" "$BRIDGE"
done
# patch-runtime.py adds a libc dependency to the guest crate but leaves the
# copied Cargo.lock untouched, so resolve offline before the locked build.
(cd "$BUILD/src" && cargo "+$TOOLCHAIN" metadata --offline --format-version 1 >/dev/null)

export CC_aarch64_unknown_linux_gnu=${CC_aarch64_unknown_linux_gnu:-aarch64-linux-gnu-gcc}
export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=${CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER:-aarch64-linux-gnu-gcc}
export LIBCLANG_PATH=${LIBCLANG_PATH:-/usr/lib/llvm-19/lib}
export POCKETJS_PROFILE_RS="$PJOS_PROFILE_RS"
export CARGO_TARGET_DIR="$BUILD/target"
export RUSTFLAGS="${RUSTFLAGS:-} -C target-feature=+crt-static"
cargo "+$TOOLCHAIN" build --locked --offline --release --target "$TARGET" \
    --manifest-path "$BUILD/src/Cargo.toml" \
    -p pocket-linux-kms -p rocknix-pocketjs-bindings
install -m 0755 "$BUILD/target/$TARGET/release/pocket-linux-kms" \
    "$HERE/work/pocketjs-runtime/pocket-linux-kms"
sha256sum "$HERE/work/pocketjs-runtime/pocket-linux-kms"
printf '%s\n' 'Device --check admission and hardware verification are required before deployment.'
