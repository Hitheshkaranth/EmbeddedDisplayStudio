"""
tools/hmi_deployer/telemetry.py
Layer: 3 (Host Deployer)
Purpose: Provides offline simulation and online SSH relay for telemetry tags
to feed into TagEngine.
"""
import base64
import json
import random
import socket
import time
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QUdpSocket
from .ssh import SshWorker, build_ssh_cmd
from typing import Optional, List


class TelemetrySimulator(QObject):
    """
    Generates plausible, smoothly varying values for expected tags offline.

    The value-advancement logic (_advance) is separated from the send logic
    (_send_frame) so each half can be tested independently.  A single UDP
    socket is created at construction and reused for every frame (no per-tick
    socket allocation).
    """

    #: Reported once when frames stop reaching the tag engine.
    #:
    #: A send that fails silently is the same fault as a bind that fails
    #: silently: the preview keeps drawing a panel whose values never change,
    #: and nothing says why. Latched, because this fires per frame and a
    #: message per frame is its own kind of silence.
    error = Signal(str)


    def __init__(
        self,
        expected_tags: List[str],
        parent: Optional[QObject] = None,
        udp_port: int = 5001,
    ) -> None:
        """
        Args:
            expected_tags: Tags the bundle declared in tags_required.
            parent:        Parent QObject.
            udp_port:      Destination port for outgoing frames (default 5001).
        """
        super().__init__(parent)
        self.expected_tags = expected_tags
        self._udp_port = udp_port
        self._timer = QTimer(self)
        self._timer.setInterval(100)  # 100 ms like the daemon
        self._timer.timeout.connect(self._step)
        self._seq: int = 0

        self.tags_state = {}
        # Initialize some plausible values
        for t in self.expected_tags:
            if t.startswith("ai."):
                self.tags_state[t] = 1.0 + random.uniform(-0.1, 0.1)
            elif t.startswith("di.") or t.startswith("do."):
                self.tags_state[t] = False
            elif t.startswith("sys.uptime"):
                self.tags_state[t] = 0.0
            elif t.startswith("sys.errors"):
                self.tags_state[t] = 0
            else:
                self.tags_state[t] = 0

        # Pooled UDP socket – created once, reused every tick.
        self._sock: Optional[socket.socket] = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM
        )
        self._closed: bool = False

    def start(self) -> None:
        if self._closed:
            return
        self._timer.start()

    def stop(self) -> None:
        """Idempotent stop: safe to call multiple times."""
        self._timer.stop()
        if not self._closed:
            self._closed = True
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    # ------------------------------------------------------------------
    # Split: value advancement vs sending
    # ------------------------------------------------------------------

    def _advance(self) -> None:
        """
        Advance tag values by one step.

        Isolated so tests can call this without needing a real UDP socket.
        """
        for t in self.expected_tags:
            if t.startswith("ai."):
                # random walk
                self.tags_state[t] += random.uniform(-0.05, 0.05)
                self.tags_state[t] = max(0.0, min(3.3, self.tags_state[t]))
            elif t.startswith("sys.uptime"):
                self.tags_state[t] += 0.1

    def _send_frame(self) -> None:
        """
        Emit a telemetry frame over UDP loopback so TagEngine receives it.

        Guard against use-after-close: if the socket was already closed by
        stop(), skip silently rather than crashing.
        """
        if self._closed or self._sock is None:
            return
        msg = {
            "t": "tags",
            "seq": self._seq,
            "ts": time.time(),
            "src": "hmi-hwd-sim",
            "tags": self.tags_state,
        }
        self._seq += 1
        try:
            self._sock.sendto(
                json.dumps(msg).encode("utf-8"), ("127.0.0.1", self._udp_port)
            )
        except OSError as exc:
            self._report_send_failure(exc)

    def _step(self) -> None:
        """Timer tick: advance values then send."""
        self._advance()
        self._send_frame()


    def _report_send_failure(self, exc: OSError) -> None:
        """Say once that telemetry is no longer arriving.

        Frames are sent many times a second, so this latches: the operator
        needs to know the feed died, not to watch it die repeatedly.
        """
        if getattr(self, "_send_failed", False):
            return
        self._send_failed = True
        self.error.emit(
            f"Tags: telemetry is not reaching the preview on port "
            f"{self._udp_port} ({exc})."
        )

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass


# Correlation id of the `list` the relay sends on start; the ack carrying it
# is routed to catalogueReceived instead of the tag engine.
CATALOGUE_REQUEST_ID = "studio-catalogue"


def build_remote_relay_script() -> str:
    """Return the Python 3 bridge executed on the target panel."""
    return (
        "import sys, socket, json, time, threading, os\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "sock.bind(('127.0.0.1', 0))\n"
        # Nothing signals this process when the ssh transport dies: it is run
        # without a TTY, so killing the local ssh leaves the remote interpreter
        # running. Every deploy restarts the relay, which stopped the previous
        # one locally and left its python on the panel, subscribed, for the
        # rest of the session. Watching stdin fixes that -- ssh closes it on
        # the way out, the read returns EOF, and the relay exits.
        #
        # The same stdin carries commands downstream: one CONTRACT 2.2 JSON
        # object per line, sent to the daemon from the relay's own socket so
        # the ack comes back through it and up stdout with the telemetry.
        # That is what lets a button in the Studio's preview flip a relay on
        # the panel. A blank line is ignored.
        "def _stdin_loop():\n"
        "    try:\n"
        "        for line in sys.stdin:\n"
        "            line = line.strip()\n"
        "            if line:\n"
        "                try:\n"
        "                    sock.sendto(line.encode('utf-8'), ('127.0.0.1', 5000))\n"
        "                except Exception:\n"
        "                    pass\n"
        "    except Exception:\n"
        "        pass\n"
        "    os._exit(0)\n"
        "threading.Thread(target=_stdin_loop, daemon=True).start()\n"
        "sub = json.dumps({'cmd': 'subscribe', 'ttl': 300}).encode()\n"
        "sock.sendto(sub, ('127.0.0.1', 5000))\n"
        "last_renew = time.monotonic()\n"
        "sock.settimeout(1.0)\n"
        "while True:\n"
        "    try:\n"
        "        data = sock.recv(8192)\n"
        "        sys.stdout.write(data.decode('utf-8', errors='replace') + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    except socket.timeout:\n"
        "        pass\n"
        "    except Exception:\n"
        "        break\n"
        "    if time.monotonic() - last_renew > 270:\n"
        "        sock.sendto(sub, ('127.0.0.1', 5000))\n"
        "        last_renew = time.monotonic()\n"
    )


def build_remote_relay_command() -> str:
    """Build a remote-shell-safe command without nesting user-data quotes.

    Returns:
        A single shell command line to run on the panel.

    The interpreter is resolved in shell rather than hard-coded. A bare
    `python3` on a Yocto image can be python3-core alone, with no json and no
    socket, so the relay died on its first import while the rest of the
    platform ran happily on the provisioned interpreter. The order matches
    hmi-install, hmi-gui-launch and hmi-hwd-launch: $HMI_PYTHON, then
    /opt/hmi-python, then whatever is on PATH.

    `exec` replaces the login shell so the process tree stays flat and there is
    no orphaned shell left holding the relay when ssh goes away.
    """
    encoded = base64.b64encode(build_remote_relay_script().encode("utf-8")).decode("ascii")
    resolve = (
        'P="${HMI_PYTHON:-}"; '
        '[ -x "$P" ] || P=/opt/hmi-python/bin/python3; '
        '[ -x "$P" ] || P="$(command -v python3)"; '
    )
    return resolve + f'exec "$P" -c "import base64;exec(base64.b64decode(\'{encoded}\'))"'


# Workers whose thread has outlived the relay that owned them.
#
# Qt aborts the process when a running QThread is destroyed, and the relay is
# dropped at exactly the moment that is most likely: _stop_all_senders() calls
# stop() and then rebinds self.relay to None, which releases the last Python
# reference. stop() cancels the ssh child first, but that wait is bounded and
# a wedged ssh can outlast it -- so the worker is parked here instead of dying
# with its owner, and released once its thread has really returned.
#
# A worker that never finishes leaks one object. That is the right trade
# against terminating the process.
_RETIRED_WORKERS = set()


def _retire_worker(worker) -> None:
    """Keep a still-running worker alive independently of its owner.

    Args:
        worker: the SshWorker to guard. A worker that is not running needs no
            protection and is ignored.
    """
    if worker is None or not worker.isRunning() or worker in _RETIRED_WORKERS:
        return
    _RETIRED_WORKERS.add(worker)

    def _release(*_args) -> None:
        # SshWorker shadows QThread.finished with its own int signal, so this
        # is the only completion notice available. It is emitted as run()'s
        # last act, which makes the join here microseconds long.
        worker.wait(2000)
        _RETIRED_WORKERS.discard(worker)

    worker.finished.connect(_release)
    worker.error.connect(_release)


class TelemetryRelay(QObject):
    """
    Spawns an SSH process running a small Python script on the target.
    The script subscribes to the daemon at 127.0.0.1:5000, reads frames,
    and prints them to stdout.  We read stdout here and inject frames to
    local UDP so TagEngine receives them.

    The remote script is valid Python 3 (sys is imported; the subscription
    renewal loop uses a proper while-True structure with exception handling).
    """

    #: The daemon's tag catalogue, answered to the `list` sent on start.
    catalogueReceived = Signal(list)
    #: Reported once when frames stop reaching the tag engine.
    #:
    #: A send that fails silently is the same fault as a bind that fails
    #: silently: the preview keeps drawing a panel whose values never change,
    #: and nothing says why. Latched, because this fires per frame and a
    #: message per frame is its own kind of silence.
    error = Signal(str)


    def __init__(
        self,
        host: str,
        user: str,
        port: int,
        key_path: str,
        parent: Optional[QObject] = None,
        udp_port: int = 5001,
        command_port: int = 5000,
    ) -> None:
        super().__init__(parent)

        cmd = build_ssh_cmd(host, user, port, key_path, build_remote_relay_command())
        # Deliberately unparented. As a QObject child the worker would be
        # destroyed with the relay, and Qt aborts the process when the QThread
        # being destroyed is still running. Its lifetime is managed by the
        # reference held here plus _RETIRED_WORKERS during shutdown.
        self.worker = SshWorker(cmd, timeout_s=3600)
        self.worker.outputLine.connect(self._on_line)

        self._udp_port = udp_port
        # The command side. The preview's TagEngine sends CONTRACT 2.2
        # commands to 127.0.0.1:5000 exactly as it would on the panel; while
        # the relay is up, this socket is what answers that address and
        # each datagram goes up the ssh channel as one line. Acks come back
        # down with the telemetry and _on_line delivers them to the engine's
        # port like any other frame, so Bus.write() sees its ack.
        self._command_port = command_port
        self._command_sock: Optional[QUdpSocket] = None
        self._closed: bool = False
        self.local_sock: Optional[socket.socket] = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM
        )

    def _open_command_port(self) -> None:
        """Bind the command port; a taken port is reported, not fatal."""
        sock = QUdpSocket(self)
        if not sock.bind(QHostAddress("127.0.0.1"), self._command_port):
            self.error.emit(
                f"Relay: port {self._command_port} is held by another process; "
                "commands from the preview will not reach the panel."
            )
            sock.deleteLater()
            return
        sock.readyRead.connect(self._forward_commands)
        self._command_sock = sock

    def _forward_commands(self) -> None:
        """Send every pending command datagram up the ssh channel."""
        sock = self._command_sock
        if sock is None or self.worker is None:
            return
        while sock.hasPendingDatagrams():
            datagram = sock.receiveDatagram()
            text = bytes(datagram.data()).decode("utf-8", errors="replace").strip()
            # One object per line is the wire format; a command with a
            # newline inside would split, and the engine never emits one.
            if text and "\n" not in text:
                self.worker.inject(text)

    def request_catalogue(self) -> None:
        """Ask the daemon for its tag list; catalogueReceived carries the answer."""
        if self.worker is not None and not self._closed:
            self.worker.inject(json.dumps({"id": CATALOGUE_REQUEST_ID, "cmd": "list"}))

    def start(self) -> None:
        if self._closed:
            return
        self._open_command_port()
        self.worker.start()
        _retire_worker(self.worker)
        # The catalogue request goes up once the remote's stdin thread is
        # certainly running, which is well before the first frame comes back.
        QTimer.singleShot(1500, self.request_catalogue)

    def stop(self) -> None:
        """
        Idempotent stop: safe to call multiple times.

        cancel() only kills the ssh process; the QThread is still unwinding
        when it returns. Joining it here is what makes the stop safe: a
        QThread destroyed while it is still running takes the whole process
        down with it, and the relay is torn down at exactly the moments where
        that is most visible -- every deploy calls start_relay(), which stops
        the previous relay first. The wait is bounded so a wedged ssh cannot
        hang the UI thread; cancel() has already killed the process, so in
        practice it returns immediately.
        """
        if self._closed:
            # An earlier stop may have timed out; the thread still needs a
            # guardian if this relay is now on its way to being destroyed.
            _retire_worker(self.worker)
            return
        self._closed = True
        if self._command_sock is not None:
            self._command_sock.close()
            self._command_sock.deleteLater()
            self._command_sock = None
        self.worker.cancel()
        if self.worker.isRunning():
            self.worker.wait(2000)
        # The wait above is bounded and may have returned with the thread
        # still in its read loop.
        _retire_worker(self.worker)
        if self.local_sock is not None:
            try:
                self.local_sock.close()
            except OSError:
                pass
            self.local_sock = None

    def _on_line(self, line: str) -> None:
        """Guard against use-after-close before writing to the local socket."""
        if self._closed or self.local_sock is None:
            return
        # The catalogue answer is for the Studio, not the engine.
        if CATALOGUE_REQUEST_ID in line:
            try:
                msg = json.loads(line)
            except ValueError:
                msg = None
            if isinstance(msg, dict) and msg.get("id") == CATALOGUE_REQUEST_ID:
                tags = msg.get("tags")
                if isinstance(tags, list):
                    self.catalogueReceived.emit([t for t in tags if isinstance(t, str)])
                return
        try:
            self.local_sock.sendto(
                line.encode("utf-8"), ("127.0.0.1", self._udp_port)
            )
        except OSError as exc:
            self._report_send_failure(exc)


    def _report_send_failure(self, exc: OSError) -> None:
        """Say once that telemetry is no longer arriving.

        Frames are sent many times a second, so this latches: the operator
        needs to know the feed died, not to watch it die repeatedly.
        """
        if getattr(self, "_send_failed", False):
            return
        self._send_failed = True
        self.error.emit(
            f"Tags: telemetry is not reaching the preview on port "
            f"{self._udp_port} ({exc})."
        )

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
