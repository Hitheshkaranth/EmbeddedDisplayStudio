#!/usr/bin/env bash
# native/hmi-hwd/build.sh -- x86 build of the hardware daemon (WSL / Linux).
#   build.sh            configure + build -> native/hmi-hwd/out/hmi-hwd
#   build.sh --test     ... then run ctest (the C unit tests)
#   build.sh --clean    wipe the build directory first
# Build dir: $HOME/.cache/hmi-hwd-build/<path-derived> (off /mnt/c for speed).
# Requires: cmake, ninja, gcc, pkg-config, libsqlite3-dev.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="${HMI_HWD_BUILD_DIR:-$HOME/.cache/hmi-hwd-build/$(echo "$SRC" | tr '/ ' '__')}"
RUN_TESTS=0
for arg in "$@"; do
    case "$arg" in
        --test) RUN_TESTS=1 ;;
        --clean) rm -rf "$BUILD" ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done
cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo >/dev/null
cmake --build "$BUILD" --parallel
mkdir -p "$SRC/out"
cp "$BUILD/hmi-hwd" "$SRC/out/"
echo "built: $SRC/out/hmi-hwd"
if [ "$RUN_TESTS" = 1 ]; then
    (cd "$BUILD" && ctest --output-on-failure)
fi
