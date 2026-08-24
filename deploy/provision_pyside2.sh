#!/usr/bin/env bash
# provision_pyside2.sh — install the PySide2/Qt5 application runtime on a panel
#
# CONTRACT reference: sections 4.1 (runtime kinds), 6 (deployment pipeline),
#   7.1 (code standards).
#
# WHY THIS EXISTS
#   The platform runs customer applications, and a large share of existing
#   industrial Qt code is PySide2/Qt5. PySide2 cannot share the PySide6
#   interpreter: it is Qt5-only and was never built for Python past 3.11. So a
#   panel that must host both keeps two runtimes side by side:
#
#     /opt/hmi-python       CPython 3.12 + PySide6   (Qt6 apps, and the loader)
#     /opt/hmi-python-qt5   CPython 3.11 + PySide2   (Qt5 apps)
#
#   hmi-gui-launch picks between them from the bundle manifest's "qt_binding".
#
# WHY IT SHIPS ITS OWN Qt5
#   Toradex's image already carries Qt 5.15, but it is an i.MX build with GLES
#   only. The PySide2 bindings available for aarch64 are compiled against a
#   desktop-GL Qt5 and refuse to load against it:
#
#     ImportError: ... undefined symbol: _ZTI18QOpenGLTimeMonitor, version Qt_5
#
#   So this installs a matching Qt 5.15.8 privately under the runtime and
#   leaves the panel's own Qt5 completely untouched. Qt Widgets renders raster
#   and never issues a GL call, so the glvnd stubs satisfy the link and the
#   ~200 MB Mesa/LLVM stack is deliberately not shipped.
#
# USAGE
#   ./provision_pyside2.sh --host <panel-ip> [--user root] [--key <path>]
#   ./provision_pyside2.sh --build-only [--out <tarball>]
#   ./provision_pyside2.sh --host <ip> --payload <tarball>   # install a prebuilt
#
# REQUIREMENTS
#   Build step: a Linux or WSL host with curl, dpkg-deb, tar and python3.
#     (Windows has no dpkg-deb; run this from WSL.)
#   Install step: ssh/scp access to the panel as root.
#
# EXIT CODES
#   0  success
#   1  build or install failure
#   2  usage error
#   3  missing host-side tool

set -euo pipefail

readonly SCRIPT_NAME="$(basename "$0")"

# Debian bookworm is the source of the aarch64 PySide2 binaries: it is the last
# suite carrying pyside2 against a glibc (2.36) older than the panel's (2.39),
# which is the direction that works. Trixie's are built against glibc 2.41 and
# would not load.
readonly SUITE="bookworm"
readonly MIRROR="https://deb.debian.org/debian"

# CPython 3.11 — the newest interpreter Debian's PySide2 (cp311 ABI) accepts.
readonly PY_TAG="20260814"
readonly PY_VER="3.11.16"

# Where the runtime lands on the panel. hmi-gui-launch hard-codes this path.
readonly REMOTE_ROOT="/opt/hmi-python-qt5"

# Root packages; their dependency closure is resolved from the suite index.
readonly ROOT_PKGS=(
    libshiboken2-py3-5.15
    libpyside2-py3-5.15
    python3-pyside2.qtcore
    python3-pyside2.qtgui
    python3-pyside2.qtwidgets
    python3-pyside2.qtnetwork
    python3-pyside2.qtsvg
    python3-pyside2.qtprintsupport
    python3-pyside2.qtxml
    qtwayland5
)

# Pure-Python packages that industrial PySide2 apps commonly import and that no
# .deb provides in a form this tree can use.
readonly PIP_PKGS=(pyserial prettytable networkscan)

# Provided by the panel, or deliberately omitted. Pruned from the closure along
# with their own dependencies.
readonly SKIP_PKGS=(
    libc6 libgcc-s1 libstdc++6 libc-bin libcrypt1
    python3 python3-minimal libpython3.11 libpython3.11-minimal
    libpython3.11-stdlib dpkg install-info debconf sensible-utils ucf
    adduser passwd libudev1 libsystemd0 systemd udev
    libgl1-mesa-dri libglx-mesa0 libegl-mesa0 libllvm15 libgbm1
    libdrm2 libdrm-common libdrm-amdgpu1 libdrm-nouveau2 libdrm-radeon1
    libelf1 libsensors5 libsensors-config libz3-4 libedit2
)

HOST=""
USER_NAME="root"
PORT=22
KEY=""
BUILD_ONLY=0
PAYLOAD=""
OUT=""

log()  { printf '[%s] %s\n' "$SCRIPT_NAME" "$*" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$SCRIPT_NAME" "$*" >&2; exit "${2:-1}"; }

usage() {
    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

need() {
    command -v "$1" >/dev/null 2>&1 || die "missing required tool: $1" 3
}

# ---------------------------------------------------------------------------
# SECTION 1 — ARGUMENTS
# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --host)       HOST="${2:?}"; shift 2 ;;
        --user)       USER_NAME="${2:?}"; shift 2 ;;
        --port)       PORT="${2:?}"; shift 2 ;;
        --key)        KEY="${2:?}"; shift 2 ;;
        --payload)    PAYLOAD="${2:?}"; shift 2 ;;
        --out)        OUT="${2:?}"; shift 2 ;;
        --build-only) BUILD_ONLY=1; shift ;;
        -h|--help)    usage 0 ;;
        *)            die "unknown argument: $1" 2 ;;
    esac
done

if [ "$BUILD_ONLY" -eq 0 ] && [ -z "$HOST" ]; then
    die "--host is required (or use --build-only)" 2
fi

OUT="${OUT:-/tmp/hmi-python-qt5.tar.gz}"

ssh_opts=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -p "$PORT")
scp_opts=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -P "$PORT")
if [ -n "$KEY" ]; then
    ssh_opts+=(-i "$KEY")
    scp_opts+=(-i "$KEY")
fi

# ---------------------------------------------------------------------------
# SECTION 2 — BUILD THE PAYLOAD
# ---------------------------------------------------------------------------

build_payload() {
    need curl; need dpkg-deb; need tar; need python3

    local stage debroot sp ma index
    stage="$(mktemp -d)"
    debroot="$stage/debroot"
    index="$stage/Packages"
    mkdir -p "$debroot" "$stage/debs"

    log "fetching CPython ${PY_VER} (aarch64)"
    curl -fsSL -o "$stage/cpython.tar.gz" \
        "https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/cpython-${PY_VER}%2B${PY_TAG}-aarch64-unknown-linux-gnu-install_only.tar.gz"
    tar xzf "$stage/cpython.tar.gz" -C "$stage"   # unpacks to $stage/python

    log "fetching ${SUITE}/arm64 package index"
    curl -fsSL "${MIRROR}/dists/${SUITE}/main/binary-arm64/Packages.gz" | gzip -dc > "$index"

    log "resolving dependency closure"
    local -a filenames
    mapfile -t filenames < <(
        SKIP="${SKIP_PKGS[*]}" python3 - "$index" "${ROOT_PKGS[@]}" <<'PY'
import collections, os, re, sys

index, roots = sys.argv[1], sys.argv[2:]
skip = set(os.environ.get("SKIP", "").split())
# Virtual packages that carry no files.
virtual = ("qtbase-abi-", "qtdeclarative-abi-", "qt5-", "fontconfig-config")

pkgs, provides, cur = {}, collections.defaultdict(list), {}
for line in open(index, encoding="utf-8", errors="replace"):
    line = line.rstrip("\n")
    if not line:
        if cur.get("Package"):
            pkgs[cur["Package"]] = cur
            for p in re.split(r",\s*", cur.get("Provides", "")):
                if p.strip():
                    provides[p.split()[0]].append(cur["Package"])
        cur = {}
    elif line[0] not in " \t" and ":" in line:
        k, _, v = line.partition(":")
        cur[k.strip()] = v.strip()

def deps(field):
    out = []
    for group in field.split(","):
        first = group.strip().split("|")[0].strip()
        if first:
            out.append(first.split()[0].split(":")[0])
    return out

seen, order = set(), []
queue = collections.deque(roots)
while queue:
    name = queue.popleft()
    if name in seen or name in skip or name.startswith(virtual):
        continue
    seen.add(name)
    p = pkgs.get(name)
    if p is None:
        if provides.get(name):
            queue.append(provides[name][0])
        continue
    order.append(p)
    queue.extend(deps(p.get("Depends", "")))

for p in order:
    print(p["Filename"])
PY
    )
    log "  ${#filenames[@]} packages"

    log "downloading and unpacking"
    local fn base
    for fn in "${filenames[@]}"; do
        base="$(basename "$fn")"
        curl -fsSL "${MIRROR}/${fn}" -o "$stage/debs/$base"
        dpkg-deb -x "$stage/debs/$base" "$debroot"
    done

    ma="$debroot/usr/lib/aarch64-linux-gnu"
    sp="$stage/python/lib/python3.11/site-packages"

    log "assembling the private Qt5 tree"
    mkdir -p "$stage/python/qt5/lib" "$stage/python/qt5/plugins"
    # bookworm is merged-/usr, but dpkg-deb -x keeps each package's declared
    # path, so libraries land under both /usr/lib and /lib. Sweep both into one
    # directory that a single LD_LIBRARY_PATH entry covers.
    local d
    for d in "$ma" "$debroot/usr/lib" "$debroot/lib/aarch64-linux-gnu" "$debroot/lib"; do
        [ -d "$d" ] || continue
        find "$d" -maxdepth 1 -name "*.so*" -exec cp -a {} "$stage/python/qt5/lib/" \;
    done
    cp -a "$ma/qt5/plugins/." "$stage/python/qt5/plugins/"
    log "  $(ls "$stage/python/qt5/lib" | wc -l) libraries, $(ls "$stage/python/qt5/plugins" | wc -l) plugin groups"

    log "installing the PySide2 bindings"
    cp -a "$debroot/usr/lib/python3/dist-packages/PySide2" "$sp/"
    [ -d "$debroot/usr/lib/python3/dist-packages/shiboken2" ] &&
        cp -a "$debroot/usr/lib/python3/dist-packages/shiboken2" "$sp/"

    # Pure-Python only, so the host's own interpreter can place them into an
    # aarch64 tree without cross-compiling anything.
    log "adding pure-Python dependencies: ${PIP_PKGS[*]}"
    python3 -m pip install --quiet --target "$sp" --upgrade "${PIP_PKGS[@]}"

    log "packing ${OUT}"
    tar czf "$OUT" -C "$stage" python
    log "  $(du -h "$OUT" | cut -f1)"
    rm -rf "$stage"
}

# ---------------------------------------------------------------------------
# SECTION 3 — INSTALL ON THE PANEL
# ---------------------------------------------------------------------------

install_payload() {
    need ssh; need scp
    local payload="$1"

    log "uploading to ${USER_NAME}@${HOST}"
    scp "${scp_opts[@]}" "$payload" "${USER_NAME}@${HOST}:/tmp/hmi-python-qt5.tar.gz"

    log "installing at ${REMOTE_ROOT}"
    ssh "${ssh_opts[@]}" "${USER_NAME}@${HOST}" "
        set -e
        rm -rf ${REMOTE_ROOT} /tmp/python
        tar xzf /tmp/hmi-python-qt5.tar.gz -C /tmp
        mv /tmp/python ${REMOTE_ROOT}
        rm -f /tmp/hmi-python-qt5.tar.gz
    "

    log "verifying"
    ssh "${ssh_opts[@]}" "${USER_NAME}@${HOST}" "
        export LD_LIBRARY_PATH=${REMOTE_ROOT}/qt5/lib
        export QT_PLUGIN_PATH=${REMOTE_ROOT}/qt5/plugins
        QT_QPA_PLATFORM=offscreen ${REMOTE_ROOT}/bin/python3 -c '
import PySide2, PySide2.QtCore as C
from PySide2.QtWidgets import QApplication, QLabel
a = QApplication([]); w = QLabel(\"probe\"); w.resize(320, 200); w.show()
print(\"PySide2\", PySide2.__version__, \"on Qt\", C.qVersion(), \"- widgets OK\")
'
    " || die "the runtime installed but could not create a widget"

    log "done - deploy a bundle whose manifest says \"qt_binding\": \"pyside2\""
}

# ---------------------------------------------------------------------------
# SECTION 4 — MAIN
# ---------------------------------------------------------------------------

if [ -n "$PAYLOAD" ]; then
    [ -f "$PAYLOAD" ] || die "no such payload: $PAYLOAD"
else
    build_payload
    PAYLOAD="$OUT"
fi

if [ "$BUILD_ONLY" -eq 1 ]; then
    log "built ${PAYLOAD}; install it with: $SCRIPT_NAME --host <ip> --payload ${PAYLOAD}"
    exit 0
fi

install_payload "$PAYLOAD"
