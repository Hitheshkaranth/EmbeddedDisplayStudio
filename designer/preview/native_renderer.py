"""designer/preview/native_renderer.py -- previews rendered by hmi-ui.

FROZEN CONTRACT (native previews swarm, 2026-09-22). Owner: W2. Public
names, signatures, signals and attributes below are the contract; W2 fills
the bodies and may add private helpers.

The renderer is a drop-in for designer/canvas/qml_previews.QmlPreviewRenderer
(same `image_for` / `ready` / `clear` / `enabled` surface, same
`preview_key` from that module) so the Designer scene and the Code section
can hold either. It runs the headless hmi-ui binary as a child process
(never in-process) per render, a few at a time, and caches by key.

How a render is made (both scopes go through a temporary bundle directory
holding a one-page project.edsui, so containers with children and pages
render exactly as on the panel):
    hmi-ui --apps-dir <tmp> --headless <tmp>/out.png --kit <kit> --theme <theme>
The temporary project's screen is width x height, background `background`,
theme `theme`; a widget render places a copy of the widget at 0,0 with its
bindings and actions stripped (a still of the design, like the QML
renderer) and its properties as they are. The PNG is loaded into a QImage
(ARGB32), scaled by `scale` with smooth transformation when scale != 1.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from dataclasses import asdict

from PySide6.QtCore import QObject, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QImage

from designer.canvas.qml_previews import preview_key
from designer.model import DesignerPage, DesignerProject, DesignerScreen

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_LIMIT = 400
# A headless render takes well under a second; a child that is still going
# after this long is stuck (or the machine is), and its slot is worth more
# than its picture.
RENDER_TIMEOUT_MS = 30000
OUTPUT_TAIL_LINES = 12

log = logging.getLogger("designer.preview")


# Where hmi-ui's headless binary is looked for, in order:
#   $HMI_UI_BIN; a frozen Studio's bundle dir (sys._MEIPASS)/hmi-ui/hmi-ui[.exe];
#   <repo>/native/hmi-ui/out/win64/hmi-ui.exe on Windows,
#   <repo>/native/hmi-ui/out/hmi-ui elsewhere.
def find_hmi_ui() -> str | None:
    """Absolute path of a usable hmi-ui binary (exists and is executable), or None."""
    override = os.environ.get("HMI_UI_BIN")
    if override:
        # An explicit path is an instruction, not a hint: no fallback when
        # it is wrong, so a stale variable is noticed rather than masked.
        return os.path.abspath(override) if _usable(override) else None
    name = "hmi-ui.exe" if sys.platform == "win32" else "hmi-ui"
    bundle = _bundle_dir()
    if bundle:
        candidate = os.path.join(bundle, "hmi-ui", name)
        return os.path.abspath(candidate) if _usable(candidate) else None
    if sys.platform == "win32":
        candidate = os.path.join(REPO_ROOT, "native", "hmi-ui", "out", "win64", name)
    else:
        candidate = os.path.join(REPO_ROOT, "native", "hmi-ui", "out", name)
    return os.path.abspath(candidate) if _usable(candidate) else None


def kit_dir() -> str:
    """The kit directory hmi-ui renders with (ui/qml/Shadcn: fonts/ and icons/),
    in the repository or in a frozen Studio's bundle."""
    return os.path.join(_bundle_dir() or REPO_ROOT, "ui", "qml", "Shadcn")


def _bundle_dir() -> str | None:
    """PyInstaller's unpack directory when the Studio runs as an exe."""
    return getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None


def _usable(path) -> bool:
    if not path or not os.path.isfile(path):
        return False
    # Windows has no execute bit; a file is all that can be asked for.
    return sys.platform == "win32" or os.access(path, os.X_OK)


class _Job:
    """One render in flight: its bundle directory, process and how to finish."""
    __slots__ = ("key", "bundle", "theme", "scale", "generation", "tmp", "process", "done")

    def __init__(self, key, bundle, theme, scale, generation):
        self.key = key
        self.bundle = bundle          # the one-page project as a dict
        self.theme = theme
        self.scale = scale
        self.generation = generation  # clear()/shutdown() bump it: older results are discarded
        self.tmp = None
        self.process = None
        self.done = False


class NativeRenderer(QObject):
    """Renders design sections with hmi-ui, one child process per render.

    Signals:
        ready(str): a render for this key has landed; repaint what uses it.
        failed(str, str): (key, message) when hmi-ui could not render it.

    Attributes:
        enabled: False makes image_for return None without scheduling.
        available: True when a binary was found at construction.
        binary: the path used (or None).
        background: the screen colour behind a widget render ('#rrggbb');
            the workspace sets it to the design's screen background.
        parallel: how many child processes may run at once (default 2).
    """

    ready = Signal(str)
    failed = Signal(str, str)

    def __init__(self, binary: str | None = None, parent=None):
        super().__init__(parent)
        if binary is None:
            binary = find_hmi_ui()
        elif not _usable(binary):
            binary = None
        self.binary = os.path.abspath(binary) if binary else None
        self.available = self.binary is not None
        self.enabled = True
        self.background = DesignerScreen().background
        self.parallel = 2
        self._kit = kit_dir()
        self._cache = OrderedDict()   # key -> QImage (null = failed, do not re-ask)
        self._queue = OrderedDict()   # key -> _Job, front first
        self._running = {}            # key -> _Job
        self._generation = 0
        self._pump_pending = False

    # ----------------------------------------------------------------- API

    def image_for(self, widget, width, height, theme, scale=1.0):
        """The cached render, or None -- in which case one is scheduled and
        `ready` fires with `preview_key(widget, width, height, theme, scale)`
        when it lands. Same contract as QmlPreviewRenderer.image_for."""
        if not self.enabled or not self.available or width < 2 or height < 2:
            return None
        key = preview_key(widget, width, height, theme, scale)
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
            return image
        self._enqueue(key, self._widget_bundle(widget, width, height, theme), theme, scale)
        return None

    def page_image_for(self, project, page, theme, scale=1.0):
        """The cached render of the whole page at the project's screen size,
        or None with a render scheduled; `ready` fires with `page_key(project,
        page, theme, scale)`."""
        if not self.enabled or not self.available:
            return None
        key = page_key(project, page, theme, scale)
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
            return image
        self._enqueue(key, self._page_bundle(project, page, theme), theme, scale)
        return None

    def render_page_sync(self, project, page, theme, timeout_ms: int = 10000):
        """Blocking render of a page (bezel, tests): a QImage, or None on failure."""
        if not self.available:
            return None
        return self._render_sync(self._page_bundle(project, page, theme), theme, timeout_ms)

    def render_widget_sync(self, widget, width, height, theme, timeout_ms: int = 10000):
        """Blocking render of one widget: a QImage, or None on failure."""
        if not self.available or width < 1 or height < 1:
            return None
        return self._render_sync(self._widget_bundle(widget, width, height, theme), theme, timeout_ms)

    def clear(self) -> None:
        """Drops the cache and the queue (running renders finish and are discarded)."""
        self._cache.clear()
        self._queue.clear()
        self._generation += 1

    def shutdown(self) -> None:
        """Kills running child processes; call before the Studio exits."""
        self._queue.clear()
        self._generation += 1
        for job in list(self._running.values()):
            process = job.process
            if process is not None and process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(2000)
            # A process that would not die still gets its bundle removed and
            # its slot freed; the handler is a no-op after this.
            self._discard(job)
        self._running.clear()

    # --------------------------------------------------------------- bundles

    def _widget_bundle(self, widget, width, height, theme):
        """A one-page project holding a still of the widget at 0,0."""
        w, h = max(1, int(round(width))), max(1, int(round(height)))
        # A still of the design, not of the feed: bound properties show the
        # sample values the inspector holds, as the QML renderer does.
        still = copy.copy(widget)
        still.bindings = {}
        still.actions = {}
        still.geometry = {"x": 0, "y": 0, "width": w, "height": h}
        project = DesignerProject(name="preview", screen=DesignerScreen(w, h, self.background, theme),
                                  pages=[DesignerPage("main", "Main", widgets=[still])])
        return project.to_dict()

    @staticmethod
    def _page_bundle(project, page, theme):
        """The page alone, at the project's screen, in the requested theme."""
        screen = DesignerScreen(project.screen.width, project.screen.height, project.screen.background, theme)
        one = DesignerProject(name=project.name or "preview", screen=screen, pages=[page])
        return one.to_dict()

    def _argv(self, tmp, theme):
        # Native paths: the binary is a Windows exe on Windows and does not
        # see forward-slash /mnt paths or the like.
        return [self.binary,
                "--apps-dir", os.path.normpath(tmp),
                "--headless", os.path.normpath(os.path.join(tmp, "out.png")),
                "--kit", os.path.normpath(self._kit),
                "--theme", str(theme)]

    @staticmethod
    def _write_bundle(bundle):
        tmp = tempfile.mkdtemp(prefix="hmi-ui-preview-")
        with open(os.path.join(tmp, "project.edsui"), "w", encoding="utf-8") as handle:
            json.dump(bundle, handle, ensure_ascii=False)
        return tmp

    @staticmethod
    def _load(tmp, scale):
        """The rendered PNG as ARGB32 at the requested scale, or None."""
        path = os.path.join(tmp, "out.png")
        if not os.path.isfile(path):
            return None
        image = QImage(path)
        if image.isNull():
            return None
        image = image.convertToFormat(QImage.Format_ARGB32)
        if scale != 1:
            image = image.scaled(max(1, int(image.width() * scale)), max(1, int(image.height() * scale)),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return image

    @staticmethod
    def _tail(output: bytes) -> str:
        lines = output.decode("utf-8", errors="replace").strip().splitlines()
        return "\n".join(lines[-OUTPUT_TAIL_LINES:])

    # ------------------------------------------------------------ sync path

    def _render_sync(self, bundle, theme, timeout_ms):
        """Independent of the queue and the cache: the bezel wants this
        exact picture now, and an async caller asking later still gets
        its own render and its own `ready`."""
        tmp = self._write_bundle(bundle)
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            try:
                result = subprocess.run(self._argv(tmp, theme), capture_output=True,
                                        timeout=max(0.1, timeout_ms / 1000.0), creationflags=flags, check=False)
            except subprocess.TimeoutExpired:
                log.warning("hmi-ui render timed out after %d ms", timeout_ms)
                return None
            except OSError as exc:
                log.warning("hmi-ui could not be run: %s", exc)
                return None
            tail = self._tail(result.stdout + result.stderr)
            if result.returncode != 0:
                log.warning("hmi-ui render failed (exit %s): %s", result.returncode, tail)
                return None
            image = self._load(tmp, 1.0)
            if image is None:
                log.warning("hmi-ui produced no readable image: %s", tail)
            return image
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _remember(self, key, image):
        self._cache[key] = image
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_LIMIT:
            self._cache.popitem(last=False)

    # ----------------------------------------------------------- async path

    def _enqueue(self, key, bundle, theme, scale):
        if key in self._running:
            return
        if key in self._queue:
            # Asked for again while waiting: whatever is on screen now goes
            # before what was scrolled past.
            self._queue.move_to_end(key, last=False)
            return
        self._queue[key] = _Job(key, bundle, theme, scale, self._generation)
        self._schedule_pump()

    def _schedule_pump(self):
        if not self._pump_pending:
            self._pump_pending = True
            QTimer.singleShot(0, self._pump)

    def _pump(self):
        self._pump_pending = False
        while self._queue and len(self._running) < max(1, int(self.parallel)):
            _key, job = self._queue.popitem(last=False)
            self._start(job)

    def _start(self, job):
        try:
            job.tmp = self._write_bundle(job.bundle)
        except OSError as exc:
            self._settle(job, None, f"could not write the preview bundle: {exc}")
            return
        process = QProcess(self)
        # hmi-ui logs to stdout and errors to stderr; one stream keeps the
        # story in order for the failure message.
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.finished.connect(lambda code, status, job=job: self._on_finished(job, code, status))
        # finished never fires for a process that could not start.
        process.errorOccurred.connect(lambda error, job=job: self._on_error(job, error))
        job.process = process
        self._running[job.key] = job
        argv = self._argv(job.tmp, job.theme)
        process.start(argv[0], argv[1:])
        QTimer.singleShot(RENDER_TIMEOUT_MS, lambda job=job: self._on_timeout(job))

    def _on_timeout(self, job):
        if job.done or job.process is None or job.process.state() == QProcess.NotRunning:
            return
        log.warning("hmi-ui render still running after %d ms: killed", RENDER_TIMEOUT_MS)
        job.process.kill()

    def _on_error(self, job, error):
        if error == QProcess.FailedToStart and not job.done:
            self._on_finished(job, -1, QProcess.CrashExit, "hmi-ui could not be started")

    def _on_finished(self, job, code, status, reason=None):
        if job.done:
            return
        process = job.process
        try:
            output = bytes(process.readAllStandardOutput()) if process is not None else b""
        except RuntimeError:
            # The QProcess went down with its renderer (no shutdown() before
            # the Studio left): nothing is left to report to.
            job.process = None
            self._discard(job)
            return
        tail = self._tail(output)
        image = None
        message = reason or ""
        if status != QProcess.NormalExit:
            message = message or "hmi-ui stopped before it rendered"
        elif code != 0:
            message = f"hmi-ui exited with {code}"
        else:
            image = self._load(job.tmp, job.scale)
            if image is None:
                message = "hmi-ui produced no readable image"
        if tail:
            message = f"{message}\n{tail}" if message else tail
        self._settle(job, image, message)

    def _settle(self, job, image, message):
        """Bank the result (or the failure marker), tell the world, move on."""
        job.done = True
        self._running.pop(job.key, None)
        self._cleanup(job)
        if job.generation == self._generation:
            if image is not None:
                self._remember(job.key, image)
                self.ready.emit(job.key)
            else:
                # Remember the failure so the painter fallback is used
                # without re-queueing on every repaint.
                self._remember(job.key, QImage())
                log.warning("hmi-ui could not render a preview: %s", message)
                self.failed.emit(job.key, message)
        if self._queue:
            self._schedule_pump()

    def _discard(self, job):
        job.done = True
        self._cleanup(job)

    @staticmethod
    def _cleanup(job):
        if job.process is not None:
            job.process.deleteLater()
            job.process = None
        if job.tmp:
            shutil.rmtree(job.tmp, ignore_errors=True)
            job.tmp = None


def page_key(project, page, theme, scale=1.0) -> str:
    """Cache key for a page render: covers the screen geometry/background,
    the theme, the scale and the full content of the page's widgets."""
    payload = {"screen": asdict(project.screen), "theme": theme, "scale": round(float(scale), 2),
               "page": page.to_dict()}
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
