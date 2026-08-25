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
        except OSError:
            pass

    def _step(self) -> None:
        """Timer tick: advance values then send."""
        self._advance()
        self._send_frame()

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass


def build_remote_relay_script() -> str:
    """Return the Python 3 bridge executed on the target panel."""
    return (
        "import sys, socket, json, time, threading, os\n"
        # Nothing signals this process when the ssh transport dies: it is run
        # without a TTY, so killing the local ssh leaves the remote interpreter
        # running. Every deploy restarts the relay, which stopped the previous
        # one locally and left its python on the panel, subscribed, for the
        # rest of the session. Watching stdin fixes that -- ssh closes it on
        # the way out, the read returns EOF, and the relay exits.
        "def _die_with_parent():\n"
        "    try:\n"
        "        sys.stdin.read()\n"
        "    except Exception:\n"
        "        pass\n"
        "    os._exit(0)\n"
        "threading.Thread(target=_die_with_parent, daemon=True).start()\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "sock.bind(('127.0.0.1', 0))\n"
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


class TelemetryRelay(QObject):
    """
    Spawns an SSH process running a small Python script on the target.
    The script subscribes to the daemon at 127.0.0.1:5000, reads frames,
    and prints them to stdout.  We read stdout here and inject frames to
    local UDP so TagEngine receives them.

    The remote script is valid Python 3 (sys is imported; the subscription
    renewal loop uses a proper while-True structure with exception handling).
    """

    def __init__(
        self,
        host: str,
        user: str,
        port: int,
        key_path: str,
        parent: Optional[QObject] = None,
        udp_port: int = 5001,
    ) -> None:
        super().__init__(parent)

        cmd = build_ssh_cmd(host, user, port, key_path, build_remote_relay_command())
        self.worker = SshWorker(cmd, timeout_s=3600, parent=self)
        self.worker.outputLine.connect(self._on_line)

        self._udp_port = udp_port
        self._closed: bool = False
        self.local_sock: Optional[socket.socket] = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM
        )

    def start(self) -> None:
        if self._closed:
            return
        self.worker.start()

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
            return
        self._closed = True
        self.worker.cancel()
        if self.worker.isRunning():
            self.worker.wait(2000)
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
        try:
            self.local_sock.sendto(
                line.encode("utf-8"), ("127.0.0.1", self._udp_port)
            )
        except OSError:
            pass

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
