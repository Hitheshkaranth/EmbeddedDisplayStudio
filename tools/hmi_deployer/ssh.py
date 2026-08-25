"""
tools/hmi_deployer/ssh.py
Layer: 3 (Host Deployer)
Purpose: Handles off-thread SSH/SCP operations for deployment without shelling
into bash, to support Windows natively. (CONTRACT section 6).
"""
import os
import posixpath
import shlex
import subprocess
import logging
import threading
from PySide6.QtCore import QObject, Signal, QThread
from typing import Optional, List

logger = logging.getLogger("ssh")


def _openssh_executable(name: str) -> str:
    """Return a trustworthy OpenSSH executable name for this host.

    On Windows, GUI processes can inherit a PATH containing ``ssh.bat`` or
    ``scp.cmd`` wrappers ahead of the operating-system OpenSSH client.  Python's
    process launcher honours PATHEXT, so asking it to run bare ``ssh`` can
    execute one of those wrappers instead of ``ssh.exe``.  Prefer the standard
    Windows OpenSSH location when it exists; retain the bare command on other
    systems and on Windows installations that keep OpenSSH elsewhere.

    Args:
        name: OpenSSH program basename, currently ``ssh`` or ``scp``.

    Returns:
        An absolute ``.exe`` path on a standard Windows installation, otherwise
        the supplied basename for normal PATH resolution.
    """
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = os.path.join(system_root, "System32", "OpenSSH", f"{name}.exe")
        if os.path.isfile(candidate):
            return candidate
    return name


# One job object for the whole process, created on first use. 0 records that
# the mechanism was tried and is unavailable, so it is not retried per command.
_kill_job = None
_kill_job_lock = threading.Lock()


def _kill_job_handle():
    """Return a Windows job object whose members die when this process does.

    Every ssh and scp we launch is a child that outlives us whenever the tool
    ends without running its shutdown path -- Task Manager, a crash, an IDE
    stop button. An orphan holds its SSH session open on the panel, whose
    socket-activated dropbear allows 64 at a time and silently drops every
    connection past that; leaked children therefore accumulate until *every*
    deploy fails at whatever its first step happens to be. A job with
    KILL_ON_JOB_CLOSE hands the cleanup to the kernel: the handle is released
    when this process dies, however it dies, and the children go with it.

    Returns:
        The job handle, or None on non-Windows hosts and wherever the job
        cannot be created -- in which case children behave as they did before.
    """
    global _kill_job
    if os.name != "nt":
        return None
    with _kill_job_lock:
        if _kill_job is not None:
            return _kill_job or None
        try:
            import ctypes
            from ctypes import wintypes

            class _IoCounters(ctypes.Structure):
                _fields_ = [(field, ctypes.c_ulonglong) for field in (
                    "ReadOperationCount", "WriteOperationCount",
                    "OtherOperationCount", "ReadTransferCount",
                    "WriteTransferCount", "OtherTransferCount")]

            class _BasicLimits(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class _ExtendedLimits(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", _BasicLimits),
                    ("IoInfo", _IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.SetInformationJobObject.restype = wintypes.BOOL

            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                _kill_job = 0
                return None
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):
                _kill_job = 0
                return None
            _kill_job = handle
            return handle
        except Exception:
            logger.debug("child-kill job unavailable", exc_info=True)
            _kill_job = 0
            return None


def _reap_child_with_us(proc: subprocess.Popen) -> None:
    """Tie one child's lifetime to this process's.

    Args:
        proc: the freshly started child.

    Never raises: losing this safety net is not a reason to fail a command.
    """
    handle = _kill_job_handle()
    if handle is None:
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject(handle, int(proc._handle))
    except Exception:
        logger.debug("could not put the ssh child in the kill job", exc_info=True)

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
            _reap_child_with_us(self._proc)

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
class UploadWorker(QThread):
    """
    Uploads one file over SSH, reporting how many bytes have been sent.

    scp cannot be used for this: it prints its progress meter only when stdout
    is a terminal, so through a pipe a multi-minute transfer produces no output
    whatsoever until it completes. Streaming the file into `cat > dest` over the
    same ssh transport gives an exact byte count on the sending side, which is
    what a progress bar needs. Integrity is unaffected -- the target verifies
    the SHA-256 sidecar before it will extract anything.

    Signals:
        progress(int, int): bytes sent so far, total bytes.
        outputLine(str): a line of remote stdout/stderr.
        finished(int): exit code; -1 on error, cancellation or timeout.
        error(str): a launch failure, timeout or I/O error.
    """
    progress = Signal(int, int)
    outputLine = Signal(str)
    finished = Signal(int)
    error = Signal(str)

    # Large enough that the per-chunk overhead is irrelevant, small enough that
    # the bar still moves several times a second on a slow link.
    CHUNK = 256 * 1024

    def __init__(
        self,
        command: List[str],
        local_path: str,
        timeout_s: int = 600,
        parent: Optional[QObject] = None,
    ) -> None:
        """
        Args:
            command: argv that reads the file body on stdin (see build_upload_cmd).
            local_path: file to send.
            timeout_s: watchdog for the whole transfer.
            parent: parent QObject.
        """
        super().__init__(parent)
        self.command = command
        self.local_path = local_path
        self.timeout_s = timeout_s
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._timed_out = False
        self._watchdog: Optional[threading.Timer] = None

    def run(self) -> None:
        total = 0
        try:
            total = os.path.getsize(self.local_path)
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            _reap_child_with_us(self._proc)

            if self.timeout_s and self.timeout_s > 0:
                self._watchdog = threading.Timer(self.timeout_s, self._on_timeout)
                self._watchdog.daemon = True
                self._watchdog.start()

            # Drain the child's stdout concurrently with the write loop.
            #
            # stderr is merged into stdout, so anything ssh or the remote shell
            # says lands in this pipe. Writing the whole file before reading a
            # single byte deadlocks once the remote produces more than one pipe
            # buffer (~64 KB): the child blocks writing, stops reading stdin,
            # and the local write blocks behind it until the watchdog kills the
            # transfer minutes later.
            collected: List[str] = []

            def drain() -> None:
                """Reader thread: collect remote output until the pipe closes."""
                proc = self._proc
                if proc is None or proc.stdout is None:
                    return
                try:
                    for raw in iter(proc.stdout.readline, b""):
                        line = raw.decode("utf-8", errors="replace").rstrip("\n")
                        if line:
                            collected.append(line)
                except (OSError, ValueError):
                    # cancel() closed the pipe underneath us; the exit status
                    # already says everything there is to report.
                    pass

            reader = threading.Thread(target=drain, name="upload-drain", daemon=True)
            reader.start()

            sent = 0
            self.progress.emit(0, total)
            with open(self.local_path, "rb") as f:
                while not self._cancelled:
                    chunk = f.read(self.CHUNK)
                    if not chunk:
                        break
                    self._proc.stdin.write(chunk)
                    sent += len(chunk)
                    self.progress.emit(sent, total)
            try:
                self._proc.stdin.close()
            except OSError:
                pass

            # The remote side finishes and closes stdout once stdin is done.
            reader.join(timeout=30)
            for line in collected:
                self.outputLine.emit(line)

            self._proc.wait()
            if self._timed_out:
                self.error.emit(f"Upload timed out after {self.timeout_s}s")
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
        self._timed_out = True
        self.cancel()

    def cancel(self) -> None:
        """Kills the transfer if it is running."""
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

# Options shared by every command we build.
#
# The keepalives bound a session whose link disappears mid-command -- a panel
# unplugged, or the host's route to it withdrawn. Without them the target keeps
# the session, and its dropbear, alive indefinitely: the FIN never arrives, and
# dropbear runs with no keepalive of its own. Stranded sessions count against
# the panel's 64-connection limit, past which it drops every new connection and
# the deployer cannot reach the panel at all. Three unanswered probes at 15 s
# end the session in about 45 s instead.
CONNECTION_OPTS = (
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "BatchMode=yes",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
)
def build_ssh_cmd(host: str, user: str, port: int, key_path: str, cmd: str) -> List[str]:
    """Builds a non-interactive ssh command."""
    args = [_openssh_executable("ssh"), *CONNECTION_OPTS]
    if port != 22:
        args.extend(["-p", str(port)])
    if key_path:
        args.extend(["-i", key_path])
    args.extend([f"{user}@{host}", cmd])
    return args

def build_upload_cmd(host: str, user: str, port: int, key_path: str, dest: str) -> List[str]:
    """
    Builds an ssh command that writes its stdin to `dest` on the target.

    Args:
        host, user, port, key_path: as for build_ssh_cmd.
        dest: absolute path to write on the target.

    Returns:
        The argv list. Used with UploadWorker, which streams the file body and
        counts the bytes so a transfer can report real progress.

    The destination is shell-quoted: it is interpolated into a remote shell
    command, and release names -- while constrained by the manifest rules --
    come from a file on disk rather than from this program.
    """
    parent = posixpath.dirname(dest) or "/"
    # The landing directory is created here rather than by an ssh step of its
    # own. It normally exists already -- systemd-tmpfiles makes it at boot --
    # so the mkdir costs nothing, while a separate step cost a whole extra
    # connection whose every failure mode (unreachable panel, refused key,
    # exhausted connection slots) was reported to the operator as a directory
    # that could not be created.
    return build_ssh_cmd(
        host, user, port, key_path,
        f"mkdir -p {shlex.quote(parent)} && cat > {shlex.quote(dest)}",
    )


def build_scp_cmd(host: str, user: str, port: int, key_path: str, src: str, dest: str) -> List[str]:
    """Builds a non-interactive scp command."""
    args = [_openssh_executable("scp"), *CONNECTION_OPTS]
    if port != 22:
        args.extend(["-P", str(port)])
    if key_path:
        args.extend(["-i", key_path])
    args.extend([src, f"{user}@{host}:{dest}"])
    return args
