#!/bin/sh
# Build an existing PocketJS source checkout with the BaseOS bridge patches.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${PJOS_RUNTIME_SOURCE:?Set PJOS_RUNTIME_SOURCE to the existing PocketJS source checkout}"
: "${PJOS_PROFILE_RS:?Set PJOS_PROFILE_RS to the profile exported for the installed package}"
SCRIPTS=${PJOS_BRIDGE_SCRIPTS:-$HOME/development/rocknix/projects/ROCKNIX/packages/apps/pocketjs-runtime/scripts}
BUILD=${PJOS_RUNTIME_BUILD:-$HERE/work/runtime-local}
TOOLCHAIN=${PJOS_RUST_TOOLCHAIN:-1.98.1}
TARGET=${PJOS_RUST_TARGET:-aarch64-unknown-linux-gnu}
OUTPUT=${PJOS_RUNTIME_OUTPUT:-$HERE/work/pocketjs-runtime/pocket-linux-kms}
if [ "${PJOS_RUNTIME_DEBUG:-0}" = 1 ] && [ -z "${PJOS_RUNTIME_OUTPUT:-}" ]; then
    echo "PJOS_RUNTIME_OUTPUT is required for a debug runtime" >&2
    exit 1
fi
[ -f "$PJOS_RUNTIME_SOURCE/Cargo.toml" ]
[ -f "$PJOS_PROFILE_RS" ]
[ -f "$SCRIPTS/patch-runtime.py" ]
mkdir -p "$BUILD/src" "$HERE/work/pocketjs-runtime"
# Work only on a staging copy; preserve the source checkout and build cache.
rsync -a --exclude target --exclude node_modules --exclude .git \
    "$PJOS_RUNTIME_SOURCE/" "$BUILD/src/"
python3 "$SCRIPTS/patch-runtime.py" "$BUILD/src"
python3 "$HERE/src/apply-pocketjs-gba3x-package-budget.py" "$BUILD/src/programs/linux-kms/src/main.rs"
python3 "$HERE/src/apply-pocketjs-input.py" "$BUILD/src"
python3 "$HERE/src/apply-pocketjs-fractional-display.py" "$BUILD/src"
BRIDGE="$BUILD/src/engine/guest-rquickjs/src/pocketshell_launcher.rs"
for patch in rom-arm battery panel settings system-info network-bridge power-bridge forcequit favorites cover player-path restore kanade; do
    python3 "$HERE/src/apply-pocketjs-$patch.py" "$BRIDGE"
done
if [ "${PJOS_RUNTIME_DEBUG:-0}" = 1 ]; then
    python3 "$HERE/src/apply-pocketjs-headless-debug.py" "$BUILD/src"
fi
# patch-runtime.py adds a libc dependency to the guest crate but leaves the
# copied Cargo.lock untouched, so resolve offline before the locked build.
(cd "$BUILD/src" && cargo "+$TOOLCHAIN" metadata --offline --format-version 1 >/dev/null)

case "$TARGET" in
    aarch64-unknown-linux-gnu)
        export CC_aarch64_unknown_linux_gnu=${CC_aarch64_unknown_linux_gnu:-aarch64-linux-gnu-gcc}
        export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=${CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER:-aarch64-linux-gnu-gcc}
        ;;
    aarch64-unknown-linux-musl)
        : "${PJOS_MUSL_SYSROOT:?Set PJOS_MUSL_SYSROOT to the prepared AArch64 musl sysroot}"
        export PJOS_MUSL_SYSROOT
        export CC_aarch64_unknown_linux_musl=${CC_aarch64_unknown_linux_musl:-$HERE/tools/aarch64-musl-cross.sh}
        export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=${CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER:-$HERE/tools/aarch64-musl-cross.sh}
        ;;
    *) echo "unsupported target: $TARGET" >&2; exit 1 ;;
esac
export LIBCLANG_PATH=${LIBCLANG_PATH:-/usr/lib/llvm-19/lib}
export POCKETJS_PROFILE_RS="$PJOS_PROFILE_RS"
export CARGO_TARGET_DIR="$BUILD/target"
export RUSTFLAGS="${RUSTFLAGS:-} -C target-feature=+crt-static"
cargo "+$TOOLCHAIN" build --locked --offline --release --target "$TARGET" \
    --manifest-path "$BUILD/src/Cargo.toml" \
    -p pocket-linux-kms -p rocknix-pocketjs-bindings
mkdir -p "${OUTPUT%/*}"
install -m 0755 "$BUILD/target/$TARGET/release/pocket-linux-kms" "$OUTPUT"
sha256sum "$OUTPUT"
printf '%s\n' 'Device --check admission and hardware verification are required before deployment.'
