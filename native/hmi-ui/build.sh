#!/usr/bin/env bash
# native/hmi-ui/build.sh -- headless x86 build of the runtime (WSL / Linux).
#   build.sh            configure + build -> native/hmi-ui/out/
#   build.sh --test     ... then run ctest
#   build.sh --clean    wipe the build directory first
# Build dir: $HOME/.cache/hmi-ui-build/<path-derived> (off /mnt/c for speed).
# Requires: cmake, ninja, gcc, pkg-config, libdrm-dev.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="${HMI_UI_BUILD_DIR:-$HOME/.cache/hmi-ui-build/$(echo "$SRC" | tr '/ ' '__')}"
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
for b in "$BUILD"/hmi-ui*; do
    [ -f "$b" ] && [ -x "$b" ] && cp "$b" "$SRC/out/"
done
echo "built: $(ls "$SRC/out" | tr '\n' ' ')"
if [ "$RUN_TESTS" = 1 ]; then
    (cd "$BUILD" && ctest --output-on-failure)
fi
