"""
tests/native/loader_harness.py

Black-box harness that drives any HMI GUI loader (Python or native binary)
through the probe bundle and collects observable behaviour.

Usage::

    with LoaderHarness(apps_dir="tests/native/fixtures/probe-app") as h:
        h.start()
        h.wait_for(r"PROBE ready", timeout=20)
        h.frame({"ai.pot": 1.5})
        h.wait_command("subscribe")
        commands = h.commands(timeout=1.0)
"""

import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

__all__ = ["LoaderHarness"]


def is_native():
    """Return True when HMI_GUI_CMD is set (testing a native binary)."""
    return bool(os.environ.get("HMI_GUI_CMD"))


class LoaderHarness:
    """Spawns the loader and provides methods to send frames, read commands,
    and collect stdout probe lines.

    Args:
        apps_dir: path to the app bundle directory.
        theme: optional ``--theme`` override (``"light"`` or ``"dark"``).
        log_level: optional ``--log-level`` override.
        exit_after_ms: ``--exit-after`` value in milliseconds.
    """

    def __init__(self, apps_dir, *, theme=None, log_level=None, exit_after_ms=15000):
        self.apps_dir = str(apps_dir)
        self.theme = theme
        self.log_level = log_level
        self.exit_after_ms = exit_after_ms
        self._proc = None
        self._daemon = None
        self._daemon_port = None
        self._rx_port = 0
        self._ready_file = None
        self._reader_thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._lines = []
        self._cursor = 0
        self._seq = 0
        self._received = []
        self.exit_code = None

    # ---- lifecycle ---------------------------------------------------------

    def start(self):
        """Spawn the loader process and start the reader thread."""
        cmd = os.environ.get("HMI_GUI_CMD")
        if cmd is None:
            cmd = [sys.executable, str(REPO_ROOT / "gui" / "hmi_loader" / "main.py")]
        else:
            cmd = shlex.split(cmd)

        # Pick ephemeral ports for the loader's rx port and our fake daemon.
        self._rx_port = self._pick_port()
        self._ready_file = _make_ready_file()

        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONUNBUFFERED"] = "1"

        # Create the fake daemon socket FIRST so we know its actual port.
        self._daemon = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._daemon.bind(("127.0.0.1", 0))
        self._daemon_port = self._daemon.getsockname()[1]

        args = [
            "--apps-dir", self.apps_dir,
            "--rx-port", str(self._rx_port),
            "--daemon-host", "127.0.0.1",
            "--daemon-port", str(self._daemon_port),
            "--ready-file", self._ready_file,
            "--windowed",
            "--exit-after", str(self.exit_after_ms),
        ]
        if self.theme:
            args.extend(["--theme", self.theme])
        if self.log_level:
            args.extend(["--log-level", self.log_level])

        self._proc = subprocess.Popen(
            cmd + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line buffered
            env=env,
        )

        self._lines = []
        self._cursor = 0
        self._seq = 0
        self._received = []
        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._read_lines, daemon=True)
        self._reader_thread.start()

    def stop(self):
        """Terminate the loader if still running, join the reader, close the daemon."""
        self._stop_event.set()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self.exit_code = self._proc.returncode if self._proc else None
        if self._proc:
            if self._proc.stdout:
                self._proc.stdout.close()
            if self._proc.stderr:
                self._proc.stderr.close()
            self._proc = None

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3)
        self._reader_thread = None

        if self._daemon:
            try:
                self._daemon.close()
            except Exception:
                pass
            self._daemon = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def _pick_port(self):
        """Bind an ephemeral UDP socket, read the port, close it."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    # ---- stdout reader -----------------------------------------------------

    def _read_lines(self):
        """Background thread that reads from the loader's stdout."""
        try:
            for line in self._proc.stdout:
                line = line.rstrip("\n").rstrip("\r")
                with self._lock:
                    self._lines.append(line)
                self._stop_event.clear()
        except Exception:
            pass

    # ---- probe line access -------------------------------------------------

    def lines(self):
        """Return all stdout lines read so far."""
        with self._lock:
            return list(self._lines)

    def probe_lines(self):
        """Return the part after ``App Log: PROBE `` for each such line."""
        results = []
        for line in self._lines:
            idx = line.find("App Log: PROBE ")
            if idx != -1:
                results.append(line[idx + len("App Log: PROBE "):])
        return results

    # ---- waiting on stdout -------------------------------------------------

    def wait_for(self, pattern, timeout=5.0):
        """Block until a new stdout line matches *pattern* (a compiled re or
        regex string).  Returns the matching line.  Raises ``AssertionError``
        with the full transcript on timeout.

        Only returns lines that have not been returned by a previous call to
        ``wait_for`` in this harness (monotonic cursor).
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        self._pattern = pattern
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                lines_snapshot = list(self._lines)
            for i in range(self._cursor, len(lines_snapshot)):
                if pattern.search(lines_snapshot[i]):
                    with self._lock:
                        self._cursor = i + 1
                    return lines_snapshot[i]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(0.02)

        with self._lock:
            transcript = "\n".join(self._lines)
        raise AssertionError(
            f"Timed out waiting for pattern '{pattern.pattern}' "
            f"after {timeout}s.  Transcript:\n{transcript}"
        )

    # ---- UDP: frames to the loader -----------------------------------------

    def frame(self, tags):
        """Send one ``{"t":"tags",...}`` datagram to the loader's rx port."""
        self._seq += 1
        payload = json.dumps({
            "t": "tags",
            "seq": self._seq,
            "ts": time.time(),
            "src": "hmi-hwd",
            "tags": tags,
        }).encode("utf-8")
        try:
            self._daemon.sendto(payload, ("127.0.0.1", self._rx_port))
        except ConnectionResetError:
            # Windows: earlier send hit a closed port; just continue.
            pass

    # ---- UDP: commands from the loader -------------------------------------

    def commands(self, timeout=1.0):
        """Drain all datagrams the loader sent to the fake daemon.
        Returns a list of parsed JSON dicts."""
        result = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self._daemon.settimeout(0.1)
                data, _ = self._daemon.recvfrom(8192)
                try:
                    result.append(json.loads(data))
                except (json.JSONDecodeError, ValueError):
                    pass
            except (socket.timeout, OSError, ConnectionResetError):
                pass
        with self._lock:
            self._received.extend(result)
        return list(result)

    def wait_command(self, cmd, timeout=3.0):
        """Block until the first received command has ``cmd`` == *cmd*.
        Returns the dict (earlier commands are kept in ``.received``)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for c in self._received:
                    if c.get("cmd") == cmd:
                        return c
            time.sleep(0.05)
        # Not found in .received — try draining fresh datagrams
        fresh = self.commands(timeout=timeout)
        for c in fresh:
            if c.get("cmd") == cmd:
                with self._lock:
                    self._received.append(c)
                return c
        raise AssertionError(f"Timed out waiting for command '{cmd}'")

    # ---- UDP: ack back to the loader ---------------------------------------

    def ack(self, id, ok=True, err="", tags=None):
        """Send an ack datagram back to the loader."""
        msg = {"t": "ack", "id": str(id), "ok": ok, "err": err}
        if tags is not None:
            msg["tags"] = tags
        payload = json.dumps(msg).encode("utf-8")
        try:
            self._daemon.sendto(payload, ("127.0.0.1", self._rx_port))
        except ConnectionResetError:
            pass

    # ---- cleanup hook (used by addCleanup) ----------------------------------

    def tearDown(self):
        """Idempotent cleanup for use with ``addCleanup``."""
        self.stop()


def _make_ready_file():
    """Create a temp dir and return the path for the ready-file."""
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="hmi_ready_")
    return os.path.join(tmpdir, "gui-ready")