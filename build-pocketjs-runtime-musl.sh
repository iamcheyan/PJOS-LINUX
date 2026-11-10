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
# The PocketShell bridge (patch-runtime.py + pocketshell-*.rs) lives in the main
# ROCKNIX checkout; feature worktrees carry only the build scripts. Pointing this
# at a tree without it silently produced a bridge-less runtime (dead battery and
# service status), so the path is asserted below.
BRIDGE_SCRIPTS="${PJOS_BRIDGE_SCRIPTS:-$HOME/development/rocknix/projects/ROCKNIX/packages/apps/pocketjs-runtime/scripts}"
CARGO_CACHE="$ROCKNIX/build.ROCKNIX-H700.aarch64/toolchain/cargo_home"
OUT="$HERE/work/pocketjs-runtime/pocket-linux-kms"

[ -f "$TARBALL" ] || { echo "missing $TARBALL" >&2; exit 1; }
[ -f "$BRIDGE_SCRIPTS/patch-runtime.py" ] || { echo "missing $BRIDGE_SCRIPTS/patch-runtime.py (set PJOS_BRIDGE_SCRIPTS)" >&2; exit 1; }
[ -f "$PROFILE" ] || { echo "missing profile export $PROFILE (run the host build first)" >&2; exit 1; }

mkdir -p "$HERE/work/pocketjs-runtime" "$HERE/work/bridge-scripts"
# Work from a copy: the committed ROCKNIX script has one doubly-escaped char
# literal ("ends_with('\\n')"), which rustc rejects as a two-codepoint char.
# Fixing it in a copy keeps the ROCKNIX checkout untouched.
rm -rf "$HERE/work/bridge-scripts"
cp -R "$BRIDGE_SCRIPTS" "$HERE/work/bridge-scripts"
python3 - "$HERE/work/bridge-scripts/pocketshell-launcher.rs" <<'PYFIX'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text()
fixed = text.replace("ends_with('\\\\n')", "ends_with('\\n')")
if fixed != text:
    p.write_text(fixed)
    print("normalized escaped newline literal in", p.name)
else:
    print("no escaped newline literal to normalize in", p.name)
PYFIX
# The fuel gauge on the RG34XX is axp2202-battery, and the stock bridge only
# looks for BAT0/BAT1/rk817/cw2015: the panel showed neither a percentage nor a
# charging icon. Add the gauge and the charging state the launcher polls.
python3 - "$HERE/work/bridge-scripts/pocketshell-launcher.rs" <<'PYBATT'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text()
if '"axp2202-battery"' not in text:
    text = text.replace(
        'for name in ["battery", "BAT0", "BAT1", "rk817-battery", "cw2015-battery"] {',
        'for name in ["axp2202-battery", "battery", "BAT0", "BAT1", "rk817-battery", "cw2015-battery"] {',
    )
if '"LEVEL", "battery-status"' not in text:
    anchor = '        // First IPv4 address of an interface that is up and not loopback'
    arm = (
        '        // Charging state of the fuel gauge: "charging" | "discharging" | "full" | "unknown".\n'
        '        ["LEVEL", "battery-status"] => {\n'
        '            for name in ["axp2202-battery", "battery", "BAT0", "BAT1", "rk817-battery", "cw2015-battery"] {\n'
        '                let base = std::path::Path::new("/sys/class/power_supply").join(name);\n'
        '                if let Ok(raw) = std::fs::read_to_string(base.join("status")) {\n'
        '                    return match raw.trim().to_ascii_lowercase().as_str() {\n'
        '                        "charging" => "charging".into(),\n'
        '                        "discharging" => "discharging".into(),\n'
        '                        "full" | "not charging" => "full".into(),\n'
        '                        _ => "unknown".into(),\n'
        '                    };\n'
        '                }\n'
        '            }\n'
        '            "unknown".into()\n'
        '        }\n'
    )
    if anchor in text:
        text = text.replace(anchor, arm + anchor, 1)
p.write_text(text)
print("battery arm present:", '"LEVEL", "battery-status"' in text)
PYBATT

docker run --rm --platform linux/arm64 \
  -e DEBIAN_FRONTEND=noninteractive -e PJOS_RUN_TESTS="${PJOS_RUN_TESTS:-0}" \
  -v "$TARBALL:/in/src.tar.gz:ro" \
  -v "$PROFILE:/in/pocket_profile.rs:ro" \
  -v "$HERE/src/apply-pocketjs-input.py:/in/apply-input.py:ro" \
  -v "$HERE/src/apply-pocketjs-rom-arm.py:/in/apply-rom-arm.py:ro" \
  -v "$HERE/src/apply-pocketjs-battery.py:/in/apply-battery.py:ro" \
  -v "$HERE/src/apply-pocketjs-panel.py:/in/apply-panel.py:ro" \
  -v "$HERE/src/apply-pocketjs-power-bridge.py:/in/apply-power-bridge.py:ro" \
  -v "$HERE/src/apply-pocketjs-restore.py:/in/apply-restore.py:ro" \
  -v "$HERE/src/apply-pocketjs-kanade.py:/in/apply-kanade.py:ro" \
  -v "$HERE/work/bridge-scripts:/in/rocknix-scripts:ro" \
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
    # Upstream narrowing + the pinned rquickjs shim crate (rocknix-pocketjs-bindings)
    # live in the ROCKNIX recipe; it also rewrites members/default-members itself.
    python3 /in/rocknix-scripts/prepare-workspace.py /work/src cargo

    python3 /in/apply-input.py /work/src

    # The card launcher talks to the host through the PocketShell bridge
    # (__launcher / __pocketshell: battery, volume, services, library). Building
    # bare upstream drops it, which reads on the panel as a dead battery gauge.
    python3 /in/rocknix-scripts/patch-runtime.py /work/src
    echo "bridge markers in source: $(grep -c __launcher /work/src/engine/guest-rquickjs/src/lib.rs)"
    # One ROM hand-off arm, anchored on the LAUNCH arm every revision carries.
    # The older BaseOS bridge rewrite (apply-pocketjs-bridge.py) is not used: it
    # targets a dispatcher revision that no longer exists in any checkout.
    python3 /in/apply-rom-arm.py /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs
    python3 /in/apply-battery.py /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs
    python3 /in/apply-panel.py /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs
    python3 /in/apply-power-bridge.py /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs
    python3 /in/apply-restore.py /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs
    python3 /in/apply-kanade.py /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs
    grep -q "fn kanade_call" /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs \
      || { echo "FATAL: KANADE bridge arm missing" >&2; exit 1; }
    echo "rom_launch hits: $(grep -c "rom_launch" /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs)"
    echo "power_timeout hits: $(grep -c "power_timeout" /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs)"
    echo "resume_get hits: $(grep -c "resume_get" /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs)"
    grep -q "power_timeout" /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs \
      || { echo "FATAL: auto power-off bridge arm missing" >&2; exit 1; }
    grep -q "rom_launch" /work/src/engine/guest-rquickjs/src/pocketshell_launcher.rs \
      || { echo "FATAL: ROM launch arm missing from the built source" >&2; exit 1; }

    export LIBCLANG_PATH=/usr/lib/llvm-14/lib
    export POCKETJS_PROFILE_RS=/in/pocket_profile.rs
    export CARGO_TARGET_DIR=/work/target
    export CC_aarch64_unknown_linux_musl=musl-gcc
    export AR_aarch64_unknown_linux_musl=ar
    export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc
    export RUSTFLAGS="-C target-feature=+crt-static"
    if [ "${PJOS_RUN_TESTS:-0}" = 1 ]; then
      echo "running pocket-linux-evdev tests"
      # Never pipe cargo into tail: the pipeline would report the status of tail,
      # and a failing test would ship a broken mapping. Capture, print, fail hard.
      if ! cargo test --offline -p pocket-linux-evdev > /tmp/evdev-tests.log 2>&1; then
        tail -30 /tmp/evdev-tests.log
        echo "FATAL: pocket-linux-evdev tests failed" >&2
        exit 1
      fi
      tail -5 /tmp/evdev-tests.log
    fi

    cargo build --release --offline \
      --manifest-path /work/src/Cargo.toml \
      --target aarch64-unknown-linux-musl \
      --package pocket-linux-kms --package rocknix-pocketjs-bindings

    install -m 0755 /work/target/aarch64-unknown-linux-musl/release/pocket-linux-kms /out/pocket-linux-kms
    echo "built binary: $(stat -c %s /out/pocket-linux-kms) bytes; __launcher=$(grep -c __launcher /out/pocket-linux-kms || true)"
    file /out/pocket-linux-kms || true
  '

echo
echo "runtime: $OUT"
sha256sum "$OUT"

# Assert what the card will actually run. A bridge-less build compiles, admits
# packages and draws the UI, so the missing host bridge only shows up later as a
# dead battery gauge; catch it here instead.
for marker in __launcher __pocketshell power_supply; do
    grep -qa "$marker" "$OUT" || { echo "FATAL: runtime is missing the host bridge ($marker)" >&2; exit 1; }
done
if head -c 4 "$OUT" | od -An -tx1 | grep -q "7f 45 4c 46"; then :; else
    echo "FATAL: runtime is not an ELF binary" >&2; exit 1
fi
if grep -qa "/lib/ld-linux" "$OUT" || grep -qa "ld-musl" "$OUT"; then
    echo "FATAL: runtime is dynamically linked; BaseOS glibc is 2.35" >&2; exit 1
fi
echo "runtime checks: bridge present, static aarch64"
