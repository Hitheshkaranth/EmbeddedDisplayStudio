#!/usr/bin/env bash
# native/hmi-gui/build.sh -- configure, build and (optionally) test the native
# loader. Runs on Linux, including WSL; from Windows use build.ps1, which
# forwards here.
#
#   build.sh            configure + build, copy the binary to native/hmi-gui/out/
#   build.sh --test     ... then run the QTest suite through ctest
#   build.sh --clean    wipe the build directory first
#
# The build directory is kept OFF the source tree (and off /mnt/c under WSL,
# where ninja is an order of magnitude slower): $HOME/.cache/hmi-gui-build/
# <path-derived name>, or $HMI_GUI_BUILD_DIR. One directory per checkout, so
# swarm worktrees never share objects.
#
# Requires: cmake >= 3.22, ninja, g++, Qt 6 dev (qt6-base-dev,
# qt6-declarative-dev, qml6-module-qtquick*), python3 for tests/native.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_TESTS=0
CLEAN=0
for arg in "$@"; do
    case "$arg" in
        --test)  RUN_TESTS=1 ;;
        --clean) CLEAN=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

BUILD="${HMI_GUI_BUILD_DIR:-$HOME/.cache/hmi-gui-build/$(echo "$SRC" | tr '/ ' '__')}"
if [ "$CLEAN" = 1 ]; then
    rm -rf "$BUILD"
fi

cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo >/dev/null
cmake --build "$BUILD" --parallel

mkdir -p "$SRC/out"
cp "$BUILD/hmi-gui" "$SRC/out/hmi-gui"
echo "built: $SRC/out/hmi-gui"

if [ "$RUN_TESTS" = 1 ]; then
    (cd "$BUILD" && QT_QPA_PLATFORM=offscreen ctest --output-on-failure)
fi
