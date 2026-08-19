"""
tools/hmi_deployer/telemetry.py
Layer: 3 (Host Deployer)
Purpose: Provides offline simulation and online SSH relay for telemetry tags
to feed into TagEngine.
"""
import sys
import json
import random
from PySide6.QtCore import QObject, QTimer, Signal
from .ssh import SshWorker, build_ssh_cmd
from typing import Optional, List

class TelemetrySimulator(QObject):
    """
    Generates plausible, smoothly varying values for expected tags offline.
    """
    def __init__(self, expected_tags: List[str], parent: Optional[QObject] = None):
        super().__init__(parent)
        self.expected_tags = expected_tags
        self._timer = QTimer(self)
        self._timer.setInterval(100) # 100ms like the daemon
        self._timer.timeout.connect(self._step)
        
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

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()
        
    def _step(self):
        for t in self.expected_tags:
            if t.startswith("ai."):
                # random walk
                self.tags_state[t] += random.uniform(-0.05, 0.05)
                self.tags_state[t] = max(0.0, min(3.3, self.tags_state[t]))
            elif t.startswith("sys.uptime"):
                self.tags_state[t] += 0.1
                
        import socket
        try:
            # We emit a fake telemetry frame over UDP loopback 5001 so TagEngine receives it
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            msg = {
                "t": "tags",
                "seq": 0,
                "ts": 0.0,
                "src": "hmi-hwd-sim",
                "tags": self.tags_state
            }
            sock.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", 5001))
            sock.close()
        except Exception:
            pass

class TelemetryRelay(QObject):
    """
    Spawns an SSH process running a small python script on the target.
    The script subscribes to the daemon at 127.0.0.1:5000 and forwards frames to stdout.
    We read them here and inject them to UDP 5001 locally.
    """
    def __init__(self, host: str, user: str, port: int, key_path: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        # Small remote script to bridge UDP to stdout
        # It creates a UDP socket, binds an ephemeral port, sends 'subscribe' to :5000,
        # then loops reading from its port and printing to stdout.
        # Ensure we flush stdout so it streams.
        remote_script = (
            "import socket, json, time; "
            "sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); "
            "sock.bind(('127.0.0.1', 0)); "
            "sock.sendto(json.dumps({'cmd':'subscribe','ttl':300}).encode(), ('127.0.0.1', 5000)); "
            "sock.settimeout(1.0); "
            "[[sys.stdout.write(sock.recv(8192).decode() + '\\n'), sys.stdout.flush()] "
            "for _ in iter(int, 1) if sock] "
            "except Exception: pass"
        )
        
        # We wrap in python3 -c '...'
        cmd = build_ssh_cmd(host, user, port, key_path, f"python3 -c \"{remote_script}\"")
        self.worker = SshWorker(cmd, timeout_s=3600, parent=self)
        self.worker.outputLine.connect(self._on_line)
        import socket
        self.local_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start(self):
        self.worker.start()

    def stop(self):
        self.worker.cancel()
        self.local_sock.close()

    def _on_line(self, line: str):
        try:
            # We just relay it verbatim to local UDP 5001 where TagEngine is listening
            self.local_sock.sendto(line.encode("utf-8"), ("127.0.0.1", 5001))
        except Exception:
            pass
