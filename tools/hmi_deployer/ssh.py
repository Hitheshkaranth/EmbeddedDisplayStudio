"""
tools/hmi_deployer/ssh.py
Layer: 3 (Host Deployer)
Purpose: Handles off-thread SSH/SCP operations for deployment without shelling
into bash, to support Windows natively. (CONTRACT section 6).
"""
import subprocess
import logging
import threading
from PySide6.QtCore import QObject, Signal, QThread
from typing import Optional, List

logger = logging.getLogger("ssh")

class SshWorker(QThread):
    """
    Runs an SSH command or SCP off the UI thread.

    Signals:
        outputLine(str): Emitted for every line of stdout/stderr.
        finished(int): Emitted when the process exits, with the exit code.
        error(str): Emitted on a launch failure or timeout.
    """
    outputLine = Signal(str)
    finished = Signal(int)
    error = Signal(str)

    def __init__(
        self,
        command: List[str],
        timeout_s: int = 30,
        parent: Optional[QObject] = None,
    ) -> None:
        """
        Args:
            command: The exact command list to execute (e.g. ['ssh', ...]).
            timeout_s: Max duration in seconds to wait for completion.
            parent: Parent QObject.
        """
        super().__init__(parent)
        self.command = command
        self.timeout_s = timeout_s
        # Popen instance for possible cancellation
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._timed_out = False
        self._watchdog: Optional[threading.Timer] = None

    def run(self) -> None:
        """
        Executes the subprocess, reads output line by line, and waits.

        The timeout is enforced by a watchdog timer rather than by the
        Popen.wait() call below. Draining stdout blocks until the child closes
        the pipe, which for a hung ssh is never -- so by the time wait() is
        reached the process has already exited and a timeout passed to it can
        never fire. That left the deploy button disabled forever whenever a
        panel dropped off the network mid-command. The watchdog kills the child,
        which ends the read loop, which is what actually unblocks this thread.
        """
        try:
            # We use CREATE_NO_WINDOW on Windows to prevent popping up console windows.
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

            self._proc = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags
            )

            if self.timeout_s and self.timeout_s > 0:
                self._watchdog = threading.Timer(self.timeout_s, self._on_timeout)
                self._watchdog.daemon = True
                self._watchdog.start()

            if self._proc.stdout is not None:
                for line in iter(self._proc.stdout.readline, ""):
                    if self._cancelled:
                        break
                    if line:
                        self.outputLine.emit(line.rstrip('\n'))

            self._proc.wait()
            if self._timed_out:
                self.error.emit(f"Command timed out after {self.timeout_s}s")
                self.finished.emit(-1)
            else:
                self.finished.emit(self._proc.returncode if not self._cancelled else -1)
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit(-1)
        finally:
            if self._watchdog is not None:
                self._watchdog.cancel()
                self._watchdog = None
            self._proc = None

    def _on_timeout(self) -> None:
        """Watchdog expiry: mark the run as timed out and kill the child."""
        self._timed_out = True
        self.cancel()

    def cancel(self) -> None:
        """Kills the underlying process if it is running."""
        self._cancelled = True
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1)
            except Exception:
                pass
            try:
                self._proc.kill()
            except Exception:
                pass
"""
Helpers to construct SSH/SCP commands.
"""
def build_ssh_cmd(host: str, user: str, port: int, key_path: str, cmd: str) -> List[str]:
    """Builds a non-interactive ssh command."""
    args = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    if port != 22:
        args.extend(["-p", str(port)])
    if key_path:
        args.extend(["-i", key_path])
    args.extend([f"{user}@{host}", cmd])
    return args

def build_scp_cmd(host: str, user: str, port: int, key_path: str, src: str, dest: str) -> List[str]:
    """Builds a non-interactive scp command."""
    args = ["scp", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    if port != 22:
        args.extend(["-P", str(port)])
    if key_path:
        args.extend(["-i", key_path])
    args.extend([src, f"{user}@{host}:{dest}"])
    return args
