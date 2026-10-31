#!/bin/sh
# Build RetroArch for the vendor H700 GLIBC 2.35 runtime using the pinned
# SDL2 mali-fbdev toolchain image (its sysroot ships SDL2, ALSA, EGL and zlib).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=v1.21.0
IMAGE=${H700_TOOLCHAIN_IMAGE:-ghcr.io/loveretro/h700-toolchain:latest}
OUT="$HERE/overlay/usr/share/pocketshell/System/compat"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/pjos-retroarch-$VERSION.XXXXXX")
# The container writes root-owned object files; clean them through the image
# so a failure never leaves a directory the host cannot remove.
trap 'docker run --rm -v "$TMP:/c" alpine:3.20 sh -c "chmod -R u+rwX /c; rm -rf /c/*" >/dev/null 2>&1; rm -rf "$TMP"' EXIT INT TERM

git clone --depth 1 --branch "$VERSION" https://github.com/libretro/RetroArch.git "$TMP/source"
mkdir -p "$OUT/lib" "$OUT/share/retroarch"
# The previously built binary and the ROCKNIX artifacts it replaces are both
# gitignored; drop them so a failed build cannot leave the incompatible one.
rm -f "$OUT/lib/retroarch" "$OUT/lib/libSDL2-2.0.so.0" "$OUT/lib/libsamplerate.so.0"

cat > "$TMP/build.sh" <<'BUILD'
set -eu
S=/opt/aarch64-nextui-linux-gnu/aarch64-nextui-linux-gnu/libc
export PATH=/opt/aarch64-nextui-linux-gnu/bin:$PATH
export CC=aarch64-nextui-linux-gnu-gcc CXX=aarch64-nextui-linux-gnu-g++
export CFLAGS="-O2" CXXFLAGS="-O2"
# SDL2 lives in the toolchain's own prefix; the rewritten .pc below keeps
# pkg-config inside the cross sysroot instead of /opt/nextui.
unset PKG_CONFIG_PATH
export PKG_CONF_PATH=/usr/bin/pkg-config
export PKG_CONFIG_LIBDIR="$S/usr/lib/pkgconfig:$S/usr/share/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR="$S"

mkdir -p "$S/usr/include" "$S/usr/lib/pkgconfig"
cp -a /opt/nextui/include/SDL2 "$S/usr/include/"
cp -a /opt/nextui/lib/libSDL2-2.0.so.0 "$S/usr/lib/"
ln -sf libSDL2-2.0.so.0 "$S/usr/lib/libSDL2.so"
sed "s|^prefix=/opt/nextui|prefix=/usr|; /-Wl,-rpath/d; /^Libs:/d; /^exec_prefix/d" \
    /opt/nextui/lib/pkgconfig/sdl2.pc > "$S/usr/lib/pkgconfig/sdl2.pc"
echo 'Libs: -L/usr/lib -lSDL2' >> "$S/usr/lib/pkgconfig/sdl2.pc"

cd /src/retroarch
rm -rf obj-unix config.mk config.h
# SDL2 (mali-fbdev) is the only available display backend; every desktop
# backend, FFmpeg and systemd are absent on the device.
./configure --host=aarch64-nextui-linux-gnu --prefix=/usr \
    --disable-qt --disable-x11 --disable-wayland --disable-kms --disable-vulkan \
    --disable-ffmpeg --disable-ssl --disable-freetype --disable-pulse \
    --disable-pipewire --disable-update_assets --disable-discord --disable-vg \
    --disable-caca --disable-sixel --disable-odroidgo2 --disable-sunxi \
    --disable-plain_drm --enable-sdl2 --disable-sdl --disable-udev \
    --enable-threads --enable-zlib --enable-alsa --disable-v4l2 \
    --disable-overlay --disable-video_filter --disable-dsp_filter --disable-runahead \
    --disable-neon --disable-patch --disable-core_info_cache
    make -j"$(nproc)"
    install -m 0755 retroarch /out/lib/retroarch
    install -m 0644 /opt/nextui/lib/libSDL2-2.0.so.0 /out/lib/libSDL2-2.0.so.0
    install -m 0644 "$S/usr/lib/libsamplerate.so.0" /out/lib/libsamplerate.so.0
    install -m 0644 "$S/usr/lib/libUMP.so.3.0.0" /out/lib/libUMP.so.3.0.0
    ln -sf libUMP.so.3.0.0 /out/lib/libUMP.so.3
BUILD

docker run --rm --platform linux/amd64 \
    -v "$TMP/source:/src/retroarch" \
    -v "$OUT:/out" \
    -v "$TMP/build.sh:/build.sh:ro" \
    "$IMAGE" sh /build.sh

for artifact in retroarch libSDL2-2.0.so.0 libsamplerate.so.0 libUMP.so.3.0.0 libUMP.so.3; do
    [ -s "$OUT/lib/$artifact" ] || { echo "missing $OUT/lib/$artifact" >&2; exit 1; }
done
strings "$OUT/lib/retroarch" | grep -q '^SDL_CreateWindow$' \
    || { echo "retroarch lacks SDL2 video support (no SDL_CreateWindow)" >&2; exit 1; }
max_glibc=$(readelf -V "$OUT/lib/retroarch" | grep -o 'GLIBC_[0-9.]*' | sort -Vu | tail -1)
echo "built $OUT/lib/retroarch (needs ${max_glibc}); the SYSTEM image requires a flash to install"
