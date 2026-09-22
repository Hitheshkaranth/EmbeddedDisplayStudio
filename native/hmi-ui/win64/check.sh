#!/usr/bin/env bash
# native/hmi-ui/win64/check.sh -- the gate for the Windows preview binary.
#
# FROZEN (native previews swarm, 2026-09-22): W1 must make this pass; do not
# edit it. Run from WSL Ubuntu as root, from the repository root:
#
#   bash native/hmi-ui/win64/check.sh
#
# 1. The Linux build (native/hmi-ui/build.sh --test) must still pass its unit
#    tests: the port changes nothing on the panel.
# 2. win64/build.sh must produce out/win64/hmi-ui.exe.
# 3. The exe must run under Windows (WSL interop) and render three things
#    into PNGs: one widget by type, one widget with props, and the
#    engine-dashboard fixture page; each must be pixel-close to the Linux
#    render of the same thing (mean absolute difference < 1.0 over RGB).
# 4. `--display` must fail fast with a message naming the headless build.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
ROOT="$PWD"
OUT="$ROOT/native/hmi-ui/out"
WIN_ROOT="$(wslpath -w "$ROOT")"
QC="$ROOT/native/hmi-ui/out/win64-check"
mkdir -p "$QC"

echo "== 1. Linux build + unit tests"
bash native/hmi-ui/build.sh --test 2>&1 | grep -E "tests passed|error" | tail -2
[ -x "$OUT/hmi-ui" ] || { echo "FAIL: no Linux binary"; exit 1; }

echo "== 2. Windows build"
bash native/hmi-ui/win64/build.sh 2>&1 | tail -3
[ -f "$OUT/win64/hmi-ui.exe" ] || { echo "FAIL: no out/win64/hmi-ui.exe"; exit 1; }

echo "== 3. renders"
KIT="$ROOT/ui/qml/Shadcn"
WKIT="$(wslpath -w "$KIT")"
FIX="$ROOT/tests/ui/fixtures/engine-dashboard"
WFIX="$(wslpath -w "$FIX")"
WQC="$(wslpath -w "$QC")"
PROPS='{"label":"RPM","value":137,"unit":"x100"}'
"$OUT/hmi-ui" --render-widget ShGauge --headless "$QC/lin-gauge.png" --kit "$KIT" >/dev/null 2>&1
"$OUT/hmi-ui" --render-widget ShValueTile --props "$PROPS" --headless "$QC/lin-tile.png" --kit "$KIT" >/dev/null 2>&1
"$OUT/hmi-ui" --apps-dir "$FIX" --headless "$QC/lin-page.png" --kit "$KIT" >/dev/null 2>&1
"$OUT/win64/hmi-ui.exe" --render-widget ShGauge --headless "$WQC\\win-gauge.png" --kit "$WKIT" >/dev/null 2>&1 || true
"$OUT/win64/hmi-ui.exe" --render-widget ShValueTile --props "$PROPS" --headless "$WQC\\win-tile.png" --kit "$WKIT" >/dev/null 2>&1 || true
"$OUT/win64/hmi-ui.exe" --apps-dir "$WFIX" --headless "$WQC\\win-page.png" --kit "$WKIT" >/dev/null 2>&1 || true
for n in gauge tile page; do
    [ -f "$QC/win-$n.png" ] || { echo "FAIL: win-$n.png was not written"; exit 1; }
done
python3 - "$QC" <<'PY'
import sys
from PIL import Image, ImageChops, ImageStat
qc = sys.argv[1]
ok = True
for n in ("gauge", "tile", "page"):
    a = Image.open(f"{qc}/lin-{n}.png").convert("RGB")
    b = Image.open(f"{qc}/win-{n}.png").convert("RGB")
    if a.size != b.size:
        print(f"FAIL {n}: size {a.size} vs {b.size}"); ok = False; continue
    mean = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
    print(f"{n:6} {a.size[0]}x{a.size[1]}  mean diff {mean:.3f}  {'ok' if mean < 1.0 else 'FAIL'}")
    ok = ok and mean < 1.0
sys.exit(0 if ok else 1)
PY

echo "== 4. --display refused"
if "$OUT/win64/hmi-ui.exe" --apps-dir "$WFIX" --display /dev/dri/card1 2>&1 | grep -qi "headless"; then
    echo "ok: --display refused"
else
    echo "FAIL: --display did not fail with a headless message"; exit 1
fi
echo "win64 check: PASS"
