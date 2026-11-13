#!/bin/sh
set -eu
: "${PJOS_MUSL_SYSROOT:?Set PJOS_MUSL_SYSROOT to the staged musl sysroot}"
exec aarch64-linux-gnu-gcc "$@" -specs "$PJOS_MUSL_SYSROOT/lib/musl-gcc.specs"
