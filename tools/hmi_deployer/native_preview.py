"""
tools/hmi_deployer/native_preview.py
Layer: 3 (Host Deployer)
Purpose: live bezel preview for bundles whose runtime is "python"
         (CONTRACT sections 4.1 and 10).

THE PROBLEM
-----------
A QML bundle previews by handing its entry file to the QQuickWidget already
running inside App Studio. A Qt Widgets application cannot be previewed that
way: it constructs its own QApplication and its own top-level window, and there
is no supported means of compositing another QApplication's window into this
one's scene graph. Until now the bezel showed an explanatory card instead, so
the one class of application the platform exists to adopt -- an existing Qt app
that was never written for this panel -- was also the one you could not see
before deploying it.

THE APPROACH
------------
Run the application, unmodified, in a child process, preserve its own window
geometry, and stream it inside a target-resolution panel framebuffer.
QWidget.grab() renders through QPainter rather than through the window system,
so the image is produced without the window ever being mapped. Smaller desktop
applications are centred with letterbox space; oversized applications are
clipped at the panel edge exactly as a physical display would clip them.

The window is kept off the screen with WA_DontShowOnScreen rather than by
selecting Qt's offscreen platform plugin. That plugin carries no font database
-- QFontDatabase.families() is empty under it on Windows -- so every string
would render as an empty box, which defeats the purpose of a preview. See
_preview_platform().

The application's source is never touched. The shim below patches
QApplication.exec before the entry runs, so the frame grabber starts at the
moment the app's own event loop does -- which is exactly when its widgets are
built and shown.

WHY A SOCKET AND NOT stdout
---------------------------
Real applications print. Anything they write to stdout would be interleaved
with the frame stream and corrupt it, and the failure would look like a decode
bug rather than a stray print(). The child therefore connects back to a
loopback port that App Studio is listening on and sends frames there, leaving
stdout and stderr free to be captured and shown in the console panel -- which
is worth having anyway, since a preview that fails to start is usually
explained by a traceback on stderr.

WHY A CHILD PROCESS AND NOT AN IMPORT
-------------------------------------
Two reasons, either sufficient. A PySide2 bundle cannot be imported into this
PySide6 process at all -- that incompatibility is the entire reason the panel
carries two interpreters -- so a same-process preview could never support Qt5
applications. And an application that calls sys.exit(), installs signal
handlers or crashes must not be able to take App Studio down with it.

Inputs:  a bundle directory, its manifest, and the target resolution.
Outputs: frameReady(QImage) signals, and failed(str) when the preview cannot
         run, so the caller can fall back to the explanatory card.
"""

import logging
import os
import shutil
import struct
import subprocess
import sys

from PySide6.QtCore import QByteArray, QObject, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QHostAddress, QTcpServer

logger = logging.getLogger("native-preview")

# Frame wire format: magic, then a 4-byte big-endian length, then that many
# bytes of PNG. The magic lets the reader resynchronise loudly instead of
# silently mis-framing if anything ever writes to the socket that should not.
FRAME_MAGIC = b"HMIF"

# Header size in bytes: len(FRAME_MAGIC) + 4-byte length.
FRAME_HEADER_BYTES = len(FRAME_MAGIC) + 4

# Preview frame rate, in frames per second. Ten is enough for a gauge sweep or
# a blinking alarm to read as motion, and low enough that the child spends most
# of its time idle rather than rendering.
PREVIEW_FPS = 10

# How long to wait for the child to connect back before giving up, in ms.
# Importing a large Qt application is not instant, especially the first time
# when nothing is in the page cache.
CONNECT_TIMEOUT_MS = 20000

# Largest frame accepted, in bytes. A 1920x1080 PNG of a UI compresses to well
# under this; anything larger means the stream has lost sync.
MAX_FRAME_BYTES = 32 * 1024 * 1024


# The bootstrap executed by the child interpreter.
#
# Kept as source text rather than a module so it can run under PySide2 as well
# as PySide6: it must not import anything from this package, and it must not
# assume the Qt version. Both bindings are probed and whichever is present is
# used.
_SHIM = r'''
import os, socket, struct, sys, runpy

_PORT = int(os.environ["HMI_PREVIEW_PORT"])
_W = int(os.environ["HMI_PREVIEW_WIDTH"])
_H = int(os.environ["HMI_PREVIEW_HEIGHT"])
_ENTRY = os.environ["HMI_PREVIEW_ENTRY"]
_FPS = float(os.environ.get("HMI_PREVIEW_FPS", "10"))

try:
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtCore import Qt, QTimer, QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage, QPainter
except ImportError:
    from PySide2.QtWidgets import QApplication, QWidget
    from PySide2.QtCore import Qt, QTimer, QBuffer, QByteArray, QIODevice
    from PySide2.QtGui import QImage, QPainter

# Keep every top-level window off the screen without leaving the windowing
# system.
#
# The obvious approach -- QT_QPA_PLATFORM=offscreen -- renders the layout
# correctly and every string as an empty box, because the offscreen plugin
# carries no font database at all: QFontDatabase.families() returns 0 entries
# on Windows, against 292 under the native plugin. A preview whose whole job is
# showing you your own UI cannot render text as tofu.
#
# WA_DontShowOnScreen puts the widget through the full show, layout and paint
# pipeline without ever mapping it, so it renders with real system fonts and
# nothing appears on the developer's desktop.
_real_show = QWidget.show
_real_show_full = QWidget.showFullScreen
_real_show_max = QWidget.showMaximized
_real_show_normal = QWidget.showNormal


def _hide_from_screen(widget):
    """Mark a top-level widget as never to be mapped."""
    if widget.isWindow():
        widget.setAttribute(Qt.WA_DontShowOnScreen, True)


def _show(self):
    _hide_from_screen(self)
    return _real_show(self)


def _show_full(self):
    _hide_from_screen(self)
    return _real_show_full(self)


def _show_max(self):
    _hide_from_screen(self)
    return _real_show_max(self)


def _show_normal(self):
    _hide_from_screen(self)
    return _real_show_normal(self)


QWidget.show = _show
QWidget.showFullScreen = _show_full
QWidget.showMaximized = _show_max
QWidget.showNormal = _show_normal

_sock = socket.create_connection(("127.0.0.1", _PORT), timeout=10)
_last = [None]


def _pick_window():
    """Return the widget whose contents represent the application.

    An app can own several top-level widgets -- a splash, a hidden helper, a
    tooltip. The largest visible one is the main window in every real case,
    and picking by size avoids depending on creation order.
    """
    tops = [w for w in QApplication.topLevelWidgets()
            if w.isVisible() and w.width() > 1 and w.height() > 1]
    if not tops:
        return None
    return max(tops, key=lambda w: w.width() * w.height())


def _send(payload):
    """Write one length-prefixed frame; return False once the peer is gone."""
    try:
        _sock.sendall(b"HMIF" + struct.pack(">I", len(payload)) + payload)
        return True
    except OSError:
        return False


def _tick():
    """Grab the window and send it if it changed since the last frame."""
    w = _pick_window()
    if w is None:
        return
    # Preserve the application's authored geometry. The physical panel is the
    # framebuffer around it: smaller apps retain their native resolution with
    # letterbox space, while anything larger is naturally clipped by QPainter.
    source = w.grab().toImage()
    image = QImage(_W, _H, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.black)
    painter = QPainter(image)
    painter.drawImage((_W - source.width()) // 2, (_H - source.height()) // 2, source)
    painter.end()

    # The QByteArray must outlive the QBuffer that writes into it. Passing a
    # temporary -- QBuffer(QByteArray()) -- lets Python free it immediately
    # and the buffer then writes into released memory, which segfaults the
    # child with no output at all.
    store = QByteArray()
    buf = QBuffer(store)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    payload = bytes(store)

    # Only send changed frames. A static screen is the common case, and
    # resending an identical PNG ten times a second wastes both processes.
    if payload == _last[0]:
        return
    _last[0] = payload
    if not _send(payload):
        QApplication.quit()


_real_exec = QApplication.exec


def _patched_exec(*args, **kwargs):
    """Start the grabber, then hand control to the app's real event loop.

    QApplication.exec is static in both bindings, so the instance arrives as
    the first positional argument and the real implementation takes none.
    """
    timer = QTimer()
    timer.timeout.connect(_tick)
    timer.start(int(1000.0 / _FPS))
    _patched_exec.timer = timer   # outlive this frame
    return _real_exec()


QApplication.exec = _patched_exec
if hasattr(QApplication, "exec_"):
    QApplication.exec_ = _patched_exec

# Run the application exactly as `python main.py` would, so __name__ checks,
# relative imports and resource paths all behave the way the author expects.
sys.argv = [_ENTRY]
os.chdir(os.path.dirname(os.path.abspath(_ENTRY)) or ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(_ENTRY)) or ".")
try:
    runpy.run_path(_ENTRY, run_name="__main__")
except SystemExit:
    pass
'''


def _preview_platform() -> str:
    """Return the QT_QPA_PLATFORM value for the child, or "" for the default.

    Returns:
        A platform plugin name, or "" to let Qt choose the native one.

    The native plugin is strongly preferred: the offscreen plugin ships no
    font database, so every string in the preview would render as an empty
    box. The shim keeps windows unmapped with WA_DontShowOnScreen, so using
    the native plugin does not put anything on the developer's screen.

    Offscreen is used only where there is genuinely no display to talk to --
    a CI runner, a headless build box -- because there the native plugin
    cannot initialise at all and the child would die before rendering
    anything.
    """
    override = os.environ.get("HMI_PREVIEW_PLATFORM", "")
    if override:
        return override
    if sys.platform in ("win32", "darwin"):
        return ""
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        return ""
    return "offscreen"


def _windows_launcher_interpreters() -> list:
    """Return Python executable paths registered with the Windows launcher.

    Returns:
        Existing interpreter paths listed by ``py -0p``. Returns an empty list
        outside Windows or when the launcher is unavailable.

    A Python installed per-user commonly has no ``python3.10`` command on PATH,
    while the Windows launcher still knows its full executable path. This keeps
    PySide2 preview discovery independent of PATH configuration.
    """
    if os.name != "nt":
        return []
    launcher = shutil.which("py")
    if not launcher:
        return []
    try:
        result = subprocess.run(
            [launcher, "-0p"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []

    paths = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if not fields or not fields[0].startswith("-V:"):
            continue
        path = fields[2] if len(fields) >= 3 and fields[1] == "*" else (
            fields[1] if len(fields) >= 2 else ""
        )
        if path and os.path.isfile(path):
            paths.append(path)
    return paths


def find_interpreter(binding: str) -> str:
    """Locate a host interpreter that can import the requested Qt binding.

    Args:
        binding: "pyside6" or "pyside2".

    Returns:
        Path to a usable interpreter, or "" when none was found.

    Run from source, App Studio is itself a PySide6 process, so its own
    interpreter serves a pyside6 bundle. Packaged as an executable it is not:
    sys.executable is the Studio, and handing that to the preview shim would
    relaunch the Studio instead of the customer's application. A frozen build
    therefore has to go looking for a real interpreter for either binding.

    A pyside2 bundle always needs a second interpreter, because the two
    bindings cannot coexist in one process. $HMI_PREVIEW_PYTHON_QT5 names it
    explicitly; otherwise conventional PATH names and interpreters recorded by
    the Windows ``py`` launcher are probed. Returning "" is a normal outcome,
    not an error: the caller falls back to the explanatory card and says why.
    """
    frozen = getattr(sys, "frozen", False)
    if binding != "pyside2" and not frozen:
        return sys.executable

    module = "PySide2" if binding == "pyside2" else "PySide6"

    explicit = os.environ.get(
        "HMI_PREVIEW_PYTHON_QT5" if binding == "pyside2" else "HMI_PREVIEW_PYTHON_QT6",
        "",
    )
    if explicit and os.path.isfile(explicit):
        return explicit

    candidates = [
        shutil.which(candidate)
        for candidate in ("python3.11", "python3.10", "python3.9", "python3", "python")
    ]
    candidates.extend(_windows_launcher_interpreters())
    seen = set()
    for path in candidates:
        if not path:
            continue
        identity = os.path.normcase(os.path.abspath(path))
        # A frozen Studio is not an interpreter, so it is never a candidate;
        # from source it is already the answer and must not probe itself.
        if identity in seen or identity == os.path.normcase(os.path.abspath(sys.executable)):
            continue
        seen.add(identity)
        try:
            probe = subprocess.run(
                [path, "-c", f"import {module}"],
                capture_output=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return path
    return ""


class NativePreview(QObject):
    """Runs a runtime=python bundle unmapped and streams its frames.

    Signals:
        frameReady(QImage): a newly rendered frame at the target resolution.
        failed(str):        the preview could not start or died; the message
                            is written for the console panel and is the reason
                            the caller should show instead of a blank screen.
        stopped():          the child exited; no more frames are coming.

    Side effects: listens on a loopback port and spawns a child process.
    """

    frameReady = Signal(QImage)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, parent: QObject = None) -> None:
        """Create an idle preview. Nothing is started until start() is called."""
        super().__init__(parent)
        self._server: QTcpServer = None
        self._conn = None
        self._proc: subprocess.Popen = None
        self._buffer = QByteArray()
        self._connect_timer: QTimer = None
        self._reaper: QTimer = None

    # ------------------------------------------------------------------ api

    def start(self, bundle_dir: str, manifest: dict, width: int, height: int) -> bool:
        """Launch the bundle's entry point and begin streaming frames.

        Args:
            bundle_dir: bundle root.
            manifest:   the validated manifest.
            width:      target panel width in pixels, > 0.
            height:     target panel height in pixels, > 0.

        Returns:
            True when the child was launched. False means the preview cannot
            run here; `failed` has already carried the reason.

        Any previous preview is stopped first, so loading one bundle after
        another never leaves an orphan rendering into a socket nobody reads.
        """
        self.stop()

        entry = manifest.get("entry", "")
        entry_path = os.path.join(bundle_dir, entry)
        if not os.path.isfile(entry_path):
            self.failed.emit(f"Preview: entry {entry!r} is missing from the bundle.")
            return False

        binding = manifest.get("qt_binding") or "pyside6"
        interpreter = find_interpreter(binding)
        if not interpreter:
            self.failed.emit(
                "Preview: this bundle imports PySide2, and no PySide2 "
                "interpreter was found on this machine. Set "
                "HMI_PREVIEW_PYTHON_QT5 to one to preview it here; the bundle "
                "still deploys and runs on the panel, which carries its own "
                "Qt5 runtime."
            )
            return False

        self._server = QTcpServer(self)
        if not self._server.listen(QHostAddress("127.0.0.1"), 0):
            self.failed.emit(
                f"Preview: could not open a local port ({self._server.errorString()})."
            )
            self._teardown()
            return False
        self._server.newConnection.connect(self._on_connection)

        env = dict(os.environ)
        env["HMI_PREVIEW_PORT"] = str(self._server.serverPort())
        env["HMI_PREVIEW_WIDTH"] = str(int(width))
        env["HMI_PREVIEW_HEIGHT"] = str(int(height))
        env["HMI_PREVIEW_ENTRY"] = os.path.abspath(entry_path)
        env["HMI_PREVIEW_FPS"] = str(PREVIEW_FPS)
        platform = _preview_platform()
        if platform:
            env["QT_QPA_PLATFORM"] = platform
        else:
            # Let Qt pick the native plugin; the shim keeps the window unmapped.
            env.pop("QT_QPA_PLATFORM", None)
        # Unbuffered, so a traceback reaches the console panel immediately
        # rather than sitting in a pipe until the process dies.
        env["PYTHONUNBUFFERED"] = "1"

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(
                [interpreter, "-c", _SHIM],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                cwd=bundle_dir,
                creationflags=creationflags,
            )
        except OSError as exc:
            self.failed.emit(f"Preview: could not start {interpreter}: {exc}")
            self._teardown()
            return False

        # If the app never shows a window -- or dies during import -- nothing
        # will ever connect. Say so rather than leaving an empty bezel.
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._on_connect_timeout)
        self._connect_timer.start(CONNECT_TIMEOUT_MS)

        # Notice a child that exits on its own (a crash, or an app that closes
        # itself) so the caller can put the explanatory card back.
        self._reaper = QTimer(self)
        self._reaper.setInterval(500)
        self._reaper.timeout.connect(self._check_child)
        self._reaper.start()

        logger.info("Preview started: %s via %s", entry_path, interpreter)
        return True

    def stop(self) -> None:
        """Terminate the child and release the port. Safe to call repeatedly."""
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
            try:
                self._proc.kill()
            except (OSError, subprocess.SubprocessError):
                pass
        self._teardown()

    def is_running(self) -> bool:
        """True while a child process is alive."""
        return self._proc is not None and self._proc.poll() is None

    # -------------------------------------------------------------- internals

    def _teardown(self) -> None:
        """Drop timers, socket and server without touching the child."""
        for timer_attr in ("_connect_timer", "_reaper"):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
                setattr(self, timer_attr, None)
        if self._conn is not None:
            self._conn.abort()
            self._conn.deleteLater()
            self._conn = None
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        if self._proc is not None and self._proc.stdout is not None:
            # Popen does not close the pipe for us when we drop the reference,
            # so the read end leaks a file descriptor per preview.
            try:
                self._proc.stdout.close()
            except OSError:
                pass
        self._proc = None
        self._buffer = QByteArray()

    def _on_connection(self) -> None:
        """Accept the child's connection and start reading frames."""
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        if self._conn is not None:
            # Only one child renders at a time; a second connection means a
            # previous preview outlived its stop(). Refuse it rather than
            # interleaving two frame streams.
            conn.abort()
            conn.deleteLater()
            return
        self._conn = conn
        self._conn.readyRead.connect(self._on_ready_read)
        self._conn.disconnected.connect(self._on_disconnected)
        if self._connect_timer is not None:
            self._connect_timer.stop()

    def _on_ready_read(self) -> None:
        """Drain the socket and emit every complete frame it now holds."""
        self._buffer.append(self._conn.readAll())
        while True:
            if self._buffer.size() < FRAME_HEADER_BYTES:
                return
            raw = bytes(self._buffer)
            if not raw.startswith(FRAME_MAGIC):
                logger.error("Preview stream lost sync; dropping the connection")
                self.failed.emit("Preview: frame stream lost sync.")
                self.stop()
                return
            (length,) = struct.unpack(">I", raw[len(FRAME_MAGIC):FRAME_HEADER_BYTES])
            if length > MAX_FRAME_BYTES:
                self.failed.emit("Preview: frame larger than the accepted maximum.")
                self.stop()
                return
            if self._buffer.size() < FRAME_HEADER_BYTES + length:
                return
            payload = raw[FRAME_HEADER_BYTES:FRAME_HEADER_BYTES + length]
            self._buffer.remove(0, FRAME_HEADER_BYTES + length)

            image = QImage()
            if image.loadFromData(payload, "PNG") and not image.isNull():
                self.frameReady.emit(image)

    def _on_disconnected(self) -> None:
        """The child closed the socket; report that frames have stopped."""
        self.stopped.emit()

    def _on_connect_timeout(self) -> None:
        """No connection within the window: the app never showed a window."""
        if self._conn is not None:
            return
        output = self._drain_child_output()
        detail = f"\n{output}" if output else ""
        self.failed.emit(
            "Preview: the application did not open a window within "
            f"{CONNECT_TIMEOUT_MS // 1000}s.{detail}"
        )
        self.stop()

    def _check_child(self) -> None:
        """Poll for a child that exited by itself."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            return
        output = self._drain_child_output()
        detail = f"\n{output}" if output else ""
        self.failed.emit(f"Preview: the application exited.{detail}")
        self.stop()

    def _drain_child_output(self) -> str:
        """Return whatever the child wrote to stdout/stderr, trimmed.

        Returns:
            Up to the last 40 lines, which is enough for a traceback and
            short enough not to bury the console panel.
        """
        if self._proc is None or self._proc.stdout is None:
            return ""
        try:
            # The child is dead or about to be killed, so this cannot block for
            # long; the pipe is closed either way.
            data = self._proc.stdout.read() or b""
        except (OSError, ValueError):
            return ""
        text = data.decode("utf-8", errors="replace").strip()
        lines = text.splitlines()
        return "\n".join(lines[-40:])
