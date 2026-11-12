#!/bin/sh
# Build mpv 0.34.1 (+ a minimal static FFmpeg 5.1.6) for the RG34XX / H700.
#
# Same toolchain image as build-retroarch-h700.sh: its sysroot is old glibc, so
# the result loads on the device's glibc 2.35, and its SDL2 is the mali-fbdev
# build that presents to /dev/fb0 (there is no /dev/dri, so mpv's drm/gpu
# outputs cannot work; the `sdl` video output is the display path).
#
# Output (gitignored): work/mpv-h700/{mpv,lib/*}
# Sources are cached in work/mpv-build/ (ffmpeg.tar.xz, mpv.tar.gz).
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
IMAGE=${H700_TOOLCHAIN_IMAGE:-ghcr.io/loveretro/h700-toolchain@sha256:bf5d8f9f5442cad789aa77176bc059ec823caefa3258bf30780eee681c777119}
SRC="$HERE/work/mpv-build"
OUT="$HERE/work/mpv-h700"
FFMPEG_VER=5.1.6
MPV_VER=0.34.1
mkdir -p "$SRC" "$OUT" "$SRC/stage"
[ -f "$SRC/ffmpeg.tar.xz" ] || curl -fsSL -o "$SRC/ffmpeg.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz"
[ -f "$SRC/mpv.tar.gz" ]    || curl -fsSL -o "$SRC/mpv.tar.gz" "https://github.com/mpv-player/mpv/archive/refs/tags/v$MPV_VER.tar.gz"
[ -f "$SRC/waf" ]           || curl -fsSL -o "$SRC/waf" https://waf.io/waf-2.0.23

cat > "$SRC/inner.sh" <<'BUILD'
set -eu
T=/opt/aarch64-nextui-linux-gnu
S=$T/aarch64-nextui-linux-gnu/libc
export PATH=$T/bin:$PATH
P=aarch64-nextui-linux-gnu
export CC=$P-gcc AR=$P-ar RANLIB=$P-ranlib STRIP=$P-strip PKG_CONFIG=/usr/bin/pkg-config
unset PKG_CONFIG_PATH
export PKG_CONFIG_LIBDIR="/stage/lib/pkgconfig:$S/usr/lib/pkgconfig:$S/usr/share/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR=
mkdir -p /stage /w && cd /w

# SDL2 mali-fbdev: same staging the RetroArch build does.
mkdir -p "$S/usr/include" "$S/usr/lib/pkgconfig"
cp -a /opt/nextui/include/SDL2 "$S/usr/include/"
cp -a /opt/nextui/lib/libSDL2-2.0.so.0 "$S/usr/lib/"
ln -sf libSDL2-2.0.so.0 "$S/usr/lib/libSDL2.so"
sed "s|^prefix=/opt/nextui|prefix=$S/usr|; /-Wl,-rpath/d; /^Libs:/d; /^exec_prefix/d; /^Cflags/d" \
    /opt/nextui/lib/pkgconfig/sdl2.pc > "$S/usr/lib/pkgconfig/sdl2.pc"
echo "Libs: -L$S/usr/lib -lSDL2" >> "$S/usr/lib/pkgconfig/sdl2.pc"
echo "Cflags: -I$S/usr/include/SDL2 -D_REENTRANT" >> "$S/usr/lib/pkgconfig/sdl2.pc"

# --- FFmpeg: static, decode + demux only, native decoders only ---------------
if [ ! -f /stage/lib/libavcodec.a ]; then
tar xf /src/ffmpeg.tar.xz
cd ffmpeg-*
./configure --prefix=/stage --enable-cross-compile --arch=aarch64 --target-os=linux \
  --cross-prefix=$P- --cc=$CC --pkg-config=/usr/bin/pkg-config \
  --enable-static --disable-shared --enable-pic \
  --disable-programs --disable-doc --disable-debug --disable-network \
  --disable-avdevice --disable-postproc --disable-encoders --disable-muxers \
  --disable-bsfs --disable-filters --enable-filter=aresample,scale,format,aformat,null,anull,crop,fps \
  --disable-autodetect --enable-zlib --enable-asm --enable-neon \
  --extra-cflags="-O2" --extra-ldflags="-L$S/usr/lib"
make -j"$(nproc)"
make install
cd /w
fi

# --- libass (mpv 0.34 hard-requires it) + fribidi, static, no HarfBuzz -----------
if [ ! -f /stage/lib/libass.a ]; then
  cd /w; tar xf /src/fribidi.tar.xz; cd fribidi-*
  ./configure --host=$P --prefix=/stage --enable-static --disable-shared --with-pic >/dev/null
  make -C lib -j"$(nproc)" >/dev/null; make -C lib install >/dev/null
  make install-pkgconfigDATA >/dev/null 2>&1 || cp fribidi.pc /stage/lib/pkgconfig/ || true
  cd /w; tar xf /src/libass.tar.xz; cd libass-*
  ./configure --host=$P --prefix=/stage --enable-static --disable-shared --with-pic \
    --disable-harfbuzz --disable-fontconfig --disable-require-system-font-provider \
    --disable-asm --disable-test --disable-profile \
    FREETYPE_CFLAGS="-I$S/usr/include/freetype2" FREETYPE_LIBS="-L$S/usr/lib -lfreetype -lz" \
    FRIBIDI_CFLAGS="-I/stage/include/fribidi" FRIBIDI_LIBS="-L/stage/lib -lfribidi"
  make -j"$(nproc)"; make install
fi
cd /w

# --- mpv ---------------------------------------------------------------------
tar xf /src/mpv.tar.gz
cd mpv-*
cp /src/waf ./waf && chmod +x waf
# Python here has no distutils; mpv 0.34's wscript only needs StrictVersion.
mkdir -p /w/shim/distutils
touch /w/shim/distutils/__init__.py
cat > /w/shim/distutils/version.py <<'PY'
import re
class StrictVersion:
    def __init__(self, v):
        self.v = tuple(int(x) for x in re.findall(r'\d+', v)[:3])
    def _t(o): return o.v if isinstance(o, StrictVersion) else StrictVersion(o).v
    def __lt__(s, o): return s.v < StrictVersion._t(o)
    def __le__(s, o): return s.v <= StrictVersion._t(o)
    def __gt__(s, o): return s.v > StrictVersion._t(o)
    def __ge__(s, o): return s.v >= StrictVersion._t(o)
    def __eq__(s, o): return s.v == StrictVersion._t(o)
PY
export PYTHONPATH=/w/shim
export TARGET=$P
export CFLAGS="-O2 -I/stage/include"
export LDFLAGS="-L/stage/lib -L$S/usr/lib"
python3 ./waf configure --prefix=/stage/mpv --disable-gl --disable-lua --disable-javascript \
  --disable-libarchive --disable-uchardet --disable-vapoursynth --disable-cdda \
  --disable-dvdnav --disable-libbluray --disable-rubberband --disable-lcms2 \
  --disable-x11 --disable-wayland --disable-drm --disable-vaapi --disable-vdpau \
  --disable-pulse --disable-jack --disable-openal --disable-manpage-build \
  --disable-html-build --disable-pdf-build \
  --enable-sdl2 --enable-sdl2-audio --enable-alsa --disable-cplayer-off > /w/configure.log 2>&1 || { tail -40 /w/configure.log; exit 1; }
grep -E "libass|SDL|ALSA|libavcodec|libavformat|libswscale|libswresample|libavfilter|Libav|zlib|iconv|\bsdl\b|Video output|Audio output" /w/configure.log | cut -c1-120
python3 ./waf build -j"$(nproc)" 2>&1 | tail -30
mkdir -p /out/lib
install -m 0755 build/mpv /out/mpv
$STRIP /out/mpv
BUILD
sed -i 's/ --disable-cplayer-off//' "$SRC/inner.sh"
echo "inner script written: $SRC/inner.sh"

docker run --rm --platform linux/amd64 \
  -v "$SRC:/src" -v "$OUT:/out" -v "$SRC/stage:/stage" \
  "$IMAGE" sh /src/inner.sh
