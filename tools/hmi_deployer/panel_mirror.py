"""panel_mirror -- show the panel's own glass in the Display Console.

The console previews a bundle by handing the design to a headless hmi-ui and
drawing the one frame that comes back. That is the right thing before a
deploy -- it shows what the design looks like with nothing behind it -- but
once an application is running on a panel it is the wrong thing entirely: the
values on the glass are moving and the still frame is not, so the console
shows a screen that disagrees with the one on the bench.

The runtime already knows how to hand its screen over: SIGUSR1 makes it write
what it is displaying, live values and all, to /run/hmi/screen.png. This
mirrors that at a frame a second -- signal, copy, show -- so the console shows
the panel rather than a rehearsal of it.

It is deliberately a poll rather than a stream: a frame a second over ssh
costs the panel one snapshot and the host one scp, and it needs nothing
installed on the target that is not there already.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtGui import QImage

from .ssh import CONNECTION_OPTS, _openssh_executable, build_ssh_cmd

logger = logging.getLogger(__name__)

#: One frame a second: enough to read a moving panel, cheap enough to leave on.
DEFAULT_INTERVAL_MS = 1000

#: Where the runtime writes what it is showing (native/hmi-ui/src/main.c).
SCREEN_PATH = "/run/hmi/screen.png"

#: Signal the runtime, give it a moment to paint, and say where it landed.
SNAPSHOT_COMMAND = (
    "P=$(pidof hmi-ui 2>/dev/null) && [ -n \"$P\" ] && "
    "kill -USR1 $P && sleep 0.2 && test -s %s && echo ok" % SCREEN_PATH
)


def _scp_download_cmd(host, user, port, key_path, remote, local):
    """scp the other way round: ssh.build_scp_cmd only uploads."""
    args = [_openssh_executable("scp"), *CONNECTION_OPTS]
    if port != 22:
        args.extend(["-P", str(port)])
    if key_path:
        args.extend(["-i", key_path])
    args.extend(["%s@%s:%s" % (user, host, remote), local])
    return args


class _MirrorWorker(QThread):
    """One round trip: ask for a snapshot, fetch it, decode it."""

    frame = Signal(QImage)
    failed = Signal(str)

    def __init__(self, host, user, port, key_path, parent=None):
        super().__init__(parent)
        self._host, self._user = host, user
        self._port, self._key = port, key_path
        handle, self._local = tempfile.mkstemp(prefix="hmi-mirror-", suffix=".png")
        os.close(handle)

    def run(self):
        try:
            shot = subprocess.run(
                build_ssh_cmd(self._host, self._user, self._port, self._key,
                              SNAPSHOT_COMMAND),
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if shot.returncode != 0 or "ok" not in (shot.stdout or ""):
                detail = (shot.stderr or shot.stdout or "").strip().splitlines()
                self.failed.emit(detail[-1] if detail else "hmi-ui is not running")
                return
            copy = subprocess.run(
                _scp_download_cmd(self._host, self._user, self._port, self._key,
                                  SCREEN_PATH, self._local),
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if copy.returncode != 0:
                self.failed.emit((copy.stderr or "could not copy the screen").strip())
                return
            image = QImage(self._local)
            if image.isNull():
                self.failed.emit("the panel sent a frame that will not decode")
                return
            self.frame.emit(image)
        except subprocess.TimeoutExpired:
            self.failed.emit("the panel did not answer in time")
        except OSError as exc:                      # ssh/scp missing, disk full
            self.failed.emit(str(exc))

    def cleanup(self):
        try:
            os.unlink(self._local)
        except OSError:
            pass


class PanelMirror(QObject):
    """Polls a connected panel for what it is showing.

    Emits `frame` with each picture and `failed` with the first reason it
    could not get one; a failure stops the mirror rather than filling the log
    once a second.
    """

    frame = Signal(QImage)
    failed = Signal(str)
    started = Signal()
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(DEFAULT_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._worker = None
        self._conn = None

    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, host, user, port, key_path, interval_ms=DEFAULT_INTERVAL_MS):
        if not host:
            self.failed.emit("no panel to mirror: connect first")
            return
        self._conn = (host, user or "root", int(port or 22), key_path or "")
        self._timer.setInterval(int(interval_ms))
        self._timer.start()
        self.started.emit()
        self._tick()                     # show something without waiting a second

    def stop(self):
        self._timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        self._drop_worker()
        self.stopped.emit()

    def _tick(self):
        # One in flight at a time: a slow link must not queue snapshots up.
        if self._conn is None or (self._worker is not None and self._worker.isRunning()):
            return
        self._drop_worker()
        self._worker = _MirrorWorker(*self._conn, parent=self)
        self._worker.frame.connect(self.frame)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_failed(self, message):
        logger.info("panel mirror stopped: %s", message)
        self._timer.stop()
        self.failed.emit(message)
        self.stopped.emit()

    def _drop_worker(self):
        if self._worker is not None:
            self._worker.cleanup()
            self._worker.deleteLater()
            self._worker = None
