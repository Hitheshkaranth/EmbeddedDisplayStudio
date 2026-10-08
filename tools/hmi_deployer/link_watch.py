"""
tools/hmi_deployer/link_watch.py
Layer: 3 (Host Deployer)
Purpose: Notice when the link to a panel drops, show it, and recover -- without
polling the deploy thread. LinkWatch is a QObject that emits linkDown/linkUp
only when the state actually changes; a QTimer in the Studio calls check_now()
at a comfortable interval while the chip is visible.

The probe is a TCP connect to the panel, because the daemon listens on SSH and
nothing else on the board answers a plain connect. A probe is a real attempt to
reach the panel, so "up" means the panel is reachable, not merely that a socket
was created.
"""
import socket
import threading

from PySide6.QtCore import QObject, Signal, QTimer


class LinkWatch(QObject):
    """Watch a host:port link, emitting only on a change.

    Signals:
        linkUp(): the link came back (was down, now up).
        linkDown(): the link dropped (was up, now down).

    Usage:
        watch = LinkWatch()
        watch.linkDown.connect(self.on_link_lost)
        watch.linkUp.connect(self.on_link_restored)
        watch.start("192.168.1.50")          # start probing host:port
        QTimer.singleShot(0, watch.check_now)  # or a QTimer calling this
        watch.stop()                          # stop; check_now() is then silent
    """

    linkUp = Signal()
    linkDown = Signal()

    def __init__(self, probe=None, interval_ms=5000, parent=None):
        """
        Args:
            probe: a callable ``(host, port) -> bool`` returning whether the
                link is up, or None for the default TCP connect to host:22
                within 2 seconds.
            interval_ms: how often a calling QTimer should check_now() while
                started; informational, kept so the owner can size its timer.
            parent: parent QObject.
        """
        super().__init__(parent)
        self._probe = probe or self._default_probe
        self.interval_ms = interval_ms
        self._host = None
        self._port = 22
        self._up = None          # most recent probe result; None until first probe
        self._started = False
        self._lock = threading.Lock()

    def _default_probe(self, host, port):
        """Return whether a TCP connect to host:port succeeds within 2 s."""
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            return False

    def start(self, host, port=22):
        """Start watching a host:port. Does not probe on its own; call
        check_now() (or schedule one) to take the first reading.

        Args:
            host: the panel to watch.
            port: the port the daemon's SSH listens on.
        """
        with self._lock:
            self._host = host
            self._port = int(port)
            self._started = True

    def stop(self):
        """Stop watching. check_now() is silent while stopped."""
        with self._lock:
            self._started = False

    def is_up(self):
        """Return the most recent probe result, or None before the first one."""
        with self._lock:
            return self._up

    def check_now(self):
        """Take one reading and emit linkUp/linkDown only on a change.

        Safe to call at any interval while started; emits at most once per
        transition. A stopped watch is a no-op.
        """
        with self._lock:
            if not self._started:
                return
            host = self._host
            port = self._port
            result = self._is_link_up(host, port)
            was_up = self._up

        if was_up is None:
            # First reading sets the baseline without emitting.
            with self._lock:
                self._up = result
            return

        if result and not was_up:
            self.linkUp.emit()
        elif not result and was_up:
            self.linkDown.emit()

        with self._lock:
            self._up = result

    def _is_link_up(self, host, port):
        """Run the probe, never raising: a probe that itself is a problem must
        read as a dropped link, not as an error."""
        try:
            return bool(self._probe(host, port))
        except Exception:
            return False

    def _start_timer(self, callback, interval_ms):
        """Return a QTimer that calls callback every interval_ms.

        The Studio keeps one running while the chip is visible.
        """
        timer = QTimer()
        timer.timeout.connect(callback)
        timer.start(interval_ms)
        return timer