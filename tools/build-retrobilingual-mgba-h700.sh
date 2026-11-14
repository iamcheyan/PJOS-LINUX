#!/bin/sh
# Build a side-by-side mGBA core with a JP-ROM-gated dialogue trace hook.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=0.10.5
IMAGE=${H700_TOOLCHAIN_IMAGE:-ghcr.io/loveretro/h700-toolchain:latest}
OUT="$HERE/overlay/usr/share/pocketshell/System/compat/lib/libretro"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/pjos-retrobilingual-mgba-$VERSION.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM

git clone --depth 1 --branch "$VERSION" https://github.com/mgba-emu/mgba.git "$TMP/source"
python3 "$HERE/src/apply-retrobilingual-mgba.py" "$TMP/source" "$HERE/src"
mkdir -p "$OUT"

cat > "$TMP/build.sh" <<'BUILD'
set -eu
S=/opt/aarch64-nextui-linux-gnu/aarch64-nextui-linux-gnu/libc
export PATH=/opt/aarch64-nextui-linux-gnu/bin:$PATH
export CC=aarch64-nextui-linux-gnu-gcc
export CXX=aarch64-nextui-linux-gnu-g++
export CFLAGS="-O2"
export CXXFLAGS="-O2"

cmake -S /src/mgba -B /tmp/mgba-build \
    -DCMAKE_SYSTEM_NAME=Linux \
    -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
    -DCMAKE_C_COMPILER="$CC" \
    -DCMAKE_CXX_COMPILER="$CXX" \
    -DCMAKE_SYSROOT="$S" \
    -DCMAKE_FIND_ROOT_PATH="$S" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_LIBRETRO=ON \
    -DBUILD_SDL=OFF \
    -DBUILD_QT=OFF \
    -DBUILD_PERF=OFF \
    -DBUILD_TEST=OFF \
    -DBUILD_SUITE=OFF \
    -DUSE_EGL=OFF \
    -DUSE_GLES=OFF
cmake --build /tmp/mgba-build --target mgba_libretro --parallel "$(nproc)"
install -m 0644 /tmp/mgba-build/mgba_libretro.so /out/mgba-retrobilingual_libretro.so
BUILD

docker run --rm --platform linux/amd64 \
    -v "$TMP/source:/src/mgba" \
    -v "$OUT:/out" \
    -v "$TMP/build.sh:/build.sh:ro" \
    "$IMAGE" sh /build.sh

core="$OUT/mgba-retrobilingual_libretro.so"
[ -s "$core" ] || { echo "missing overlay core: $core" >&2; exit 1; }
readelf -h "$core" | rg -q 'Machine:.*AArch64' \
    || { echo "overlay core is not AArch64" >&2; exit 1; }
nm -D "$core" | rg -q 'retrobilingual_process_input' \
    || { echo "pack format marker is missing" >&2; exit 1; }
strings "$core" | rg -q 'QUICK SAVE' \
    || { echo "menu strings are missing" >&2; exit 1; }
echo "built $core; existing mgba_libretro.so was not replaced"
