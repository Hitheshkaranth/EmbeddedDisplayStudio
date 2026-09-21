#!/usr/bin/env bash
# tests/native/run_wsl.sh -- run the loader conformance suite in WSL from an
# ext4 copy of the checkout.
#
# WHY THE COPY
#   A checkout under /mnt/c is served by WSL's drvfs bridge, and the QML type
#   loader reads a module's files concurrently from a worker thread. On drvfs
#   one of those reads fails at random, and a bundle that instantiates several
#   Shadcn widgets dies with "<ShWidget> is not a type" -- a different widget
#   each run. Both loaders (native and PySide6) show it, no filesystem on the
#   panel does, and the same files from ext4 load every time. So the suite is
#   run from a copy under $HOME/.cache, refreshed with rsync on each call.
#
# USAGE (inside WSL, from the repo root or any worktree)
#   bash tests/native/run_wsl.sh                 # native binary (out/hmi-gui)
#   bash tests/native/run_wsl.sh --python        # the PySide6 loader
#   bash tests/native/run_wsl.sh [-- unittest args]   e.g. -- tests.native.test_conformance_faces -v
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COPY="$HOME/.cache/hmi-conformance/$(echo "$REPO" | tr '/ ' '__')"
PYTHON_LOADER=0
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --python) PYTHON_LOADER=1; shift ;;
        --) shift; ARGS=("$@"); break ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ ${#ARGS[@]} -gt 0 ] || ARGS=(discover -s tests/native -t .)

mkdir -p "$COPY"
rsync -a --delete \
    --include='/gui/***' --include='/ui/***' --include='/schema/***' --include='/tests/***' \
    --include='/native/' --include='/native/hmi-gui/' --include='/native/hmi-gui/out/***' \
    --exclude='*' --exclude='__pycache__' \
    "$REPO/" "$COPY/"

cd "$COPY"
export QT_QPA_PLATFORM=offscreen
if [ "$PYTHON_LOADER" = 1 ]; then
    unset HMI_GUI_CMD
else
    [ -x native/hmi-gui/out/hmi-gui ] || { echo "no native binary; run native/hmi-gui/build.sh" >&2; exit 1; }
    export HMI_GUI_CMD=native/hmi-gui/out/hmi-gui
fi
echo "conformance from $COPY (${HMI_GUI_CMD:-python loader})"
exec python3 -m unittest "${ARGS[@]}"
