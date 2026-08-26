"""
tools/hmi_deployer/ssh.py
Layer: 3 (Host Deployer)
Purpose: Handles off-thread SSH/SCP operations for deployment without shelling
into bash, to support Windows natively. (CONTRACT section 6).
"""
import os
import posixpath
import re
import shlex
import subprocess
import logging
import threading
from PySide6.QtCore import QObject, Signal, QThread
from typing import NamedTuple, Optional, List, Sequence

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


def _signed_exit_code(code: Optional[int]) -> int:
    """Return a process exit code that fits the ``finished(int)`` signal.

    Windows reports exit codes as an unsigned DWORD, so a process that exits
    with -1 arrives as 4294967295. Qt's ``int`` argument is signed 32-bit, and
    Shiboken drops the value with an overflow warning rather than converting
    it, leaving the receiver with a code that never matches the real failure.
    Reinterpret the high half of the range as the negative value it stands for.

    Args:
        code: Exit code from :attr:`subprocess.Popen.returncode`, or None when
            the process has not been reaped.

    Returns:
        The same code as a signed 32-bit integer; -1 when no code is available.
    """
    if code is None:
        return -1
    if code > 0x7FFFFFFF:
        return code - 0x100000000
    return code


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
                self.finished.emit(_signed_exit_code(self._proc.returncode) if not self._cancelled else -1)
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
                self.finished.emit(_signed_exit_code(self._proc.returncode) if not self._cancelled else -1)
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


# Resolves the interpreter a bundle will actually run under, in the panel's own
# shell. The order matches hmi-gui-launch exactly -- $HMI_PYTHON, then the
# provisioned /opt/hmi-python, then whatever is on PATH -- because a package
# installed into a different interpreter from the one that will import it is
# indistinguishable, from the console, from not installing it at all.
_RESOLVE_PYTHON = (
    'P="${HMI_PYTHON:-}"; '
    '[ -x "$P" ] || P=/opt/hmi-python/bin/python3; '
    '[ -x "$P" ] || P="$(command -v python3)"; '
)

# A PySide2 bundle runs under the separate Qt5 runtime, which has its own
# site-packages. See the runtime-selection section of hmi-gui-launch.
_RESOLVE_PYTHON_QT5 = (
    'P=/opt/hmi-python-qt5/bin/python3; '
    '[ -x "$P" ] || P="${HMI_PYTHON:-}"; '
    '[ -x "$P" ] || P="$(command -v python3)"; '
)


def _resolver(qt_binding: str) -> str:
    """Return the shell prologue that puts the right interpreter in $P."""
    return _RESOLVE_PYTHON_QT5 if qt_binding == "pyside2" else _RESOLVE_PYTHON


def build_dep_check_command(modules: Sequence[str], qt_binding: str = "pyside6") -> str:
    """
    Build a remote command that reports which of these modules import.

    Args:
        modules: import names to test, as the application spells them.
        qt_binding: the bundle's binding, which selects the interpreter.

    Returns:
        A shell command printing `DEP <module> ok|missing` per module, and
        `DEP_PYTHON=<path>` first so the console records which interpreter
        answered.

    Importing is the only honest test. A package can be present on disk and
    still fail to import -- a wheel built for the wrong architecture, a
    compiled extension missing a library the panel does not have -- and that
    failure is exactly the one that kills the application at startup.
    """
    listed = " ".join(shlex.quote(module) for module in modules)
    return (
        _resolver(qt_binding)
        + 'echo "DEP_PYTHON=$P"; '
        + f"for m in {listed}; do "
        + 'if "$P" -c "import $m" >/dev/null 2>&1; '
        + 'then echo "DEP $m ok"; else echo "DEP $m missing"; fi; '
        + "done"
    )


def build_dep_install_command(
    distributions: Sequence[str], qt_binding: str = "pyside6"
) -> str:
    """
    Build a remote command that pip-installs these distributions.

    Args:
        distributions: pip requirement specifiers.
        qt_binding: the bundle's binding, which selects the interpreter.

    Returns:
        A shell command printing `PIP_START`, then pip's own output, then
        `PIP_OK <name>` or `PIP_FAIL <name>` for each.

    One pip run per distribution, deliberately. A single run is all-or-nothing,
    so one name a scan got wrong -- and a scan reads names out of source, so it
    will sometimes get one wrong -- would take every other package down with
    it, including the ones the application genuinely cannot start without.
    """
    lines = [_resolver(qt_binding)]
    for distribution in distributions:
        quoted = shlex.quote(distribution)
        lines.append(
            f"echo PIP_START {quoted}; "
            f'if "$P" -m pip install --no-input --disable-pip-version-check '
            f"--root-user-action=ignore {quoted}; "
            f"then echo PIP_OK {quoted}; else echo PIP_FAIL {quoted}; fi; "
        )
    return "".join(lines)


def build_scp_cmd(host: str, user: str, port: int, key_path: str, src: str, dest: str) -> List[str]:
    """Builds a non-interactive scp command."""
    args = [_openssh_executable("scp"), *CONNECTION_OPTS]
    if port != 22:
        args.extend(["-P", str(port)])
    if key_path:
        args.extend(["-i", key_path])
    args.extend([src, f"{user}@{host}:{dest}"])
    return args


# ---- Release history --------------------------------------------------------
# `hmi-install list` prints one indented line per release, marking the active
# one and the one rollback would reach:
#
#     rel-a
#     rel-b [previous]
#     rel-c [current]
#
# The markers are part of the installer's stable output; see target/README.md.
_RELEASE_LINE_RE = re.compile(
    r"^\s{2}(?P<name>\S+)(?P<markers>(?:\s+\[(?:current|previous)\])*)\s*$"
)


class Release(NamedTuple):
    """One release retained on the panel."""

    name: str
    is_current: bool
    is_previous: bool

    def label(self) -> str:
        """How the release reads in a picker."""
        if self.is_current:
            return f"{self.name}  — running now"
        if self.is_previous:
            return f"{self.name}  — rollback target"
        return self.name


def parse_release_line(line: str):
    """Parse one line of `hmi-install list`, or None if it is not one.

    STEP lines, log output and blank lines all arrive on the same stream, so
    anything that is not a release row has to be ignored rather than guessed
    at.
    """
    if not line or line.startswith("STEP ") or line.lstrip().startswith("["):
        return None
    match = _RELEASE_LINE_RE.match(line.rstrip("\r\n"))
    if match is None:
        return None
    markers = match.group("markers")
    return Release(
        name=match.group("name"),
        is_current="[current]" in markers,
        is_previous="[previous]" in markers,
    )


def build_release_list_command() -> str:
    """Remote command listing the releases the panel still holds."""
    return "hmi-install list"


def build_activate_command(release: str) -> str:
    """Remote command making an already-installed release current.

    The name is quoted rather than interpolated: it comes from the panel's own
    listing, but it reaches a shell, and a release directory is only ever
    validated on the far side.
    """
    return f"hmi-install activate {shlex.quote(release)}"


# ---- Panel logs -------------------------------------------------------------
# The units that make up a running panel: the loader that hosts the customer's
# application, and the daemon that owns the hardware. A fault in either is
# something the operator needs to see, and neither writes anywhere but the
# journal.
LOG_UNITS = ("hmi-gui", "hmi-hwd")


def build_logs_command(lines: int = 200, follow: bool = True) -> str:
    """Remote command tailing the panel's service journals.

    Args:
        lines: how much history to fetch before following.
        follow: keep the connection open and stream new entries.

    `--no-pager` matters: journalctl pipes into less when it thinks it has a
    terminal, and ssh gives it one, which would hang the reader forever
    waiting for output that is sitting in a pager.
    """
    units = " ".join(f"-u {unit}" for unit in LOG_UNITS)
    follow_flag = " -f" if follow else ""
    # --no-hostname because you already know which panel you connected to, and
    # the name is repeated on every line: roughly thirty characters of the pane
    # spent saying the same thing, in a view that is mostly long messages
    # wrapping in a narrow column.
    return (
        f"journalctl --no-pager --no-hostname -o short-iso {units} "
        f"-n {int(lines)}{follow_flag}"
    )
