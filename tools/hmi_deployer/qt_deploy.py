"""
tools/hmi_deployer/qt_deploy.py
Layer: 3 (Host Deployer)
Purpose: bring a Qt runtime to a Qt-free panel when, and only when, the bundle
         being deployed is a Qt application.

A panel provisioned today runs hmi-ui and carries no Qt at all: no loader, no
PySide, no Qt app launcher (deploy/provision_remote.sh removes them). A
`runtime: "python"` bundle -- an existing PySide2 or PySide6 application --
cannot run on it as it stands, and used to fail in the least helpful way: the
dependency step fell through to the image's stripped /usr/bin/python3, reported
"No module named pip", and even with its packages the app would have been
started by hmi-ui, which only reads .edsui.

So the deploy of such a bundle gains one stage before everything else:

  1. ask the panel what it has (RT lines, build_runtime_check_command);
  2. for whatever is missing, build it on this machine (qt_runtime.py -- the
     panel has no internet and no package feed), upload it and install it:
       launcher  /usr/bin/hmi-gui-launch, hmi-gui.service, /etc/default/hmi-gui
                 and an hmi-install that starts the service matching the
                 bundle's runtime;
       runtime   /opt/hmi-python-qt5 (PySide2) or PySide6 in /opt/hmi-python;
  3. carry on with the ordinary deploy.

Designer bundles (`runtime: "edsui"`) never enter this stage, and the panel
keeps hmi-ui for them: hmi-install switches back when one is deployed.

The application's own third-party packages go the same way: wheels are fetched
here and installed on the panel with `pip --no-index` (start_offline_dep_install).

Inputs: the loaded bundle's manifest, the connection fields of MainWindow.
Outputs: files on the panel; console lines; the deploy continues or fails.
"""

import os
import shlex
import tarfile
import tempfile
import time
from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox

from .ssh import build_ssh_cmd, build_upload_cmd

#: Repository root, which the packaged Studio mirrors inside its bundle (see
#: packaging/EmbeddedDisplayStudio.spec, datas).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Where uploads land on the panel; systemd-tmpfiles creates it at boot and
#: build_upload_cmd creates it anyway.
REMOTE_STAGE = "/tmp/hmi_upload"

#: The line hmi-install carries once it starts the GUI service matching the
#: bundle's runtime. An installer without it restarts hmi-ui for everything,
#: which crash-loops on a Qt bundle and rolls it back, so it is replaced.
INSTALLER_FEATURE_MARKER = "HMI_INSTALL_FEATURES: runtime-service"

#: The Qt5 runtime's location; hmi-gui-launch hard-codes the same path.
QT5_ROOT = "/opt/hmi-python-qt5"

#: The panel's complete CPython 3.12, which PySide6 bundles run on.
QT6_PYTHON = "/opt/hmi-python/bin/python3"

#: Makes sure /tmp/.X11-unix exists whenever weston starts; see the file.
WESTON_DROPIN = "/etc/systemd/system/weston.service.d/hmi-x11-unix.conf"

#: Files the Qt app launcher needs, as (repository path, name in the upload).
#: The names are flat; build_launcher_install_command puts each in place.
LAUNCHER_FILES = (
    ("native/hmi-gui/target/bin/hmi-gui-launch", "hmi-gui-launch"),
    ("native/hmi-gui/target/systemd/hmi-gui.service", "hmi-gui.service"),
    ("native/hmi-gui/target/etc/default/hmi-gui", "hmi-gui.default"),
    ("native/hmi-gui/target/systemd/weston.service.d/hmi-x11-unix.conf", "weston-x11-unix.conf"),
    ("target/bin/hmi-install", "hmi-install"),
)

#: Upload allowance: a floor, plus the payload at a slow-but-working rate. The
#: Qt5 runtime is ~100 MB, which a 100 Mbit link moves in seconds and a bad
#: one in minutes; a fixed short timeout would cut it off partway.
UPLOAD_BASE_TIMEOUT_S = 60
UPLOAD_MIN_BYTES_PER_S = 256 * 1024

#: Unpacking and verifying a runtime on the panel: tens of seconds on the
#: i.MX8M Plus's eMMC, with margin.
RUNTIME_INSTALL_TIMEOUT_S = 600

#: One ssh round trip that only inspects the panel.
CHECK_TIMEOUT_S = 60


def needs_qt_runtime(manifest: Optional[dict]) -> Optional[str]:
    """Return the Qt binding a bundle needs on the panel, or None.

    Args:
        manifest: the bundle's parsed manifest.json (None when none is loaded).

    Returns:
        "pyside2" or "pyside6" for a `runtime: "python"` bundle, else None.

    A qml bundle also needs Qt, but through the retired native loader and its
    private Qt 6 (deploy/provision_native.sh), which is not built here.
    """
    manifest = manifest or {}
    if manifest.get("runtime") != "python":
        return None
    return "pyside2" if manifest.get("qt_binding") == "pyside2" else "pyside6"


def panel_python_version(binding: str) -> str:
    """The CPython minor version of the panel interpreter for this binding.

    Args:
        binding: "pyside2" or "pyside6".

    Returns:
        "3.11" for the Qt5 runtime (Debian's PySide2 is cp311), "3.12" for
        /opt/hmi-python. Wheels for the app's packages are fetched for it.
    """
    return "3.11" if binding == "pyside2" else "3.12"


def _qt_env_and_python(binding: str) -> str:
    """Shell prologue: `$P` is the binding's interpreter, Qt env exported."""
    if binding == "pyside2":
        return (
            f"P={QT5_ROOT}/bin/python3; "
            f"export LD_LIBRARY_PATH={QT5_ROOT}/qt5/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}; "
            f"export QT_PLUGIN_PATH={QT5_ROOT}/qt5/plugins; "
        )
    return f"P={QT6_PYTHON}; "


def build_runtime_check_command(binding: str) -> str:
    """Build a remote command reporting what a Qt bundle needs and lacks.

    Args:
        binding: "pyside2" or "pyside6".

    Returns:
        A shell command printing one `RT <item> ok|missing` line each for
        weston, launcher, installer, python and qt.

    `qt` is an import under the same environment hmi-gui-launch sets, done
    offscreen, because files on disk that do not import are exactly what
    kills the app at startup.
    """
    module = "PySide2.QtWidgets" if binding == "pyside2" else "PySide6.QtWidgets"
    # Each probe reads nothing: stdin is the ssh channel, which never closes,
    # so a probe that fell back to reading it (a grep whose file argument was
    # lost to quoting did exactly that) would hang the whole check.
    return (
        _qt_env_and_python(binding)
        + 'r() { if eval "$2" </dev/null >/dev/null 2>&1; then echo "RT $1 ok"; else echo "RT $1 missing"; fi; }; '
        + "r weston 'command -v weston'; "
        + "r launcher 'test -x /usr/bin/hmi-gui-launch && test -f /etc/systemd/system/hmi-gui.service"
        + f" && test -f {WESTON_DROPIN}'; "
        + f"r installer 'grep -qF \"{INSTALLER_FEATURE_MARKER}\" /usr/bin/hmi-install'; "
        + "r python 'test -x \"$P\"'; "
        + f"r qt 'QT_QPA_PLATFORM=offscreen \"$P\" -c \"import {module}\"'"
    )


def parse_runtime_line(line: str):
    """Return (item, present) for an `RT <item> ok|missing` line, else None."""
    parts = line.split()
    if len(parts) == 3 and parts[0] == "RT" and parts[2] in ("ok", "missing"):
        return parts[1], parts[2] == "ok"
    return None


def pack_launcher(dest_tar: str, repo_root: str = _REPO_ROOT) -> str:
    """Pack the Qt app launcher files into one upload.

    Args:
        dest_tar: path of the .tar.gz to write.
        repo_root: where LAUNCHER_FILES are read from.

    Returns:
        dest_tar.

    Raises:
        FileNotFoundError: a launcher file is missing from this Studio (a
            packaged build whose spec forgot to ship it).
    """
    with tarfile.open(dest_tar, "w:gz") as tar:
        for rel, name in LAUNCHER_FILES:
            src = os.path.join(repo_root, *rel.split("/"))
            if not os.path.isfile(src):
                raise FileNotFoundError(f"{rel} is not part of this Studio")
            info = tar.gettarinfo(src, arcname=name)
            # Modes are set on the panel by `install -m`; LF-only content is
            # guaranteed by .gitattributes, so nothing is rewritten here.
            with open(src, "rb") as fh:
                tar.addfile(info, fh)
    return dest_tar


def build_launcher_install_command(remote_tar: str) -> str:
    """Build the remote command that installs an uploaded pack_launcher().

    Args:
        remote_tar: where the upload landed on the panel.

    Returns:
        A shell command that exits 0 and prints `RT_INSTALLED launcher` on
        success.

    hmi-gui.service is installed but not enabled: hmi-install enables the
    service that matches the bundle it activates. An existing
    /etc/default/hmi-gui is left alone, since that is where site settings
    live. The previous hmi-install is kept beside the new one.
    """
    tar_q = shlex.quote(remote_tar)
    return (
        "set -e; d=$(mktemp -d); "
        f"tar xzf {tar_q} -C \"$d\"; "
        "install -m 0755 \"$d/hmi-gui-launch\" /usr/bin/hmi-gui-launch; "
        "install -m 0644 \"$d/hmi-gui.service\" /etc/systemd/system/hmi-gui.service; "
        "[ -e /etc/default/hmi-gui ] || install -m 0644 \"$d/hmi-gui.default\" /etc/default/hmi-gui; "
        f"install -D -m 0644 \"$d/weston-x11-unix.conf\" {WESTON_DROPIN}; "
        "if ! cmp -s \"$d/hmi-install\" /usr/bin/hmi-install; then "
        "cp -p /usr/bin/hmi-install \"/usr/bin/hmi-install.bak-$(date +%Y%m%dT%H%M%S)\" 2>/dev/null || true; "
        "install -m 0755 \"$d/hmi-install\" /usr/bin/hmi-install; fi; "
        "systemctl daemon-reload; "
        f"rm -rf \"$d\" {tar_q}; "
        "echo 'RT_INSTALLED launcher'"
    )


def build_qt5_runtime_install_command(remote_tar: str) -> str:
    """Build the remote command that installs an uploaded Qt5 runtime.

    Args:
        remote_tar: the uploaded qt_runtime.build_pyside2_runtime() tarball,
            whose single top directory is `python/`.

    Returns:
        A shell command that unpacks beside the old runtime, swaps it in, and
        proves it by creating a widget offscreen; prints `RT_INSTALLED qt`.

    Unpacked next to its destination and moved into place, so a failed
    extraction (a full disk, a truncated upload) leaves the previous runtime,
    if any, untouched.
    """
    tar_q = shlex.quote(remote_tar)
    stage = "/opt/.hmi-python-qt5.new"
    return (
        f"set -e; rm -rf {stage}; mkdir -p {stage}; "
        f"tar xzf {tar_q} -C {stage}; "
        f"rm -rf {QT5_ROOT}.old; [ -d {QT5_ROOT} ] && mv {QT5_ROOT} {QT5_ROOT}.old || true; "
        f"mv {stage}/python {QT5_ROOT}; rm -rf {stage} {QT5_ROOT}.old {tar_q}; "
        + _qt_env_and_python("pyside2")
        + "QT_QPA_PLATFORM=offscreen \"$P\" -c "
        + shlex.quote(
            "import PySide2, PySide2.QtCore as C; "
            "from PySide2.QtWidgets import QApplication, QLabel; "
            "a = QApplication([]); w = QLabel('probe'); w.show(); "
            "print('PySide2', PySide2.__version__, 'on Qt', C.qVersion())"
        )
        + "; echo 'RT_INSTALLED qt'"
    )


def build_wheel_install_command(
    remote_tar: str, distributions: Sequence[str], binding: str,
    marker: str = "PIP",
) -> str:
    """Build the remote command that pip-installs uploaded wheels, offline.

    Args:
        remote_tar: an uploaded pack_dir() of wheels.
        distributions: requirement names to install from them.
        binding: selects the interpreter ("pyside2" -> the Qt5 runtime).
        marker: prefix of the progress lines, `<marker>_START name` then
            `<marker>_OK name` or `<marker>_FAIL name`.

    Returns:
        A shell command; one pip run per distribution, so one package that
        will not install does not take the others down with it.

    `--no-index` because the panel has no route to an index: pip is told the
    uploaded directory is the whole world, and fails at once, naming what is
    missing, instead of timing out against PyPI.
    """
    tar_q = shlex.quote(remote_tar)
    lines = [
        _qt_env_and_python(binding),
        "d=$(mktemp -d); ",
        f"tar xzf {tar_q} -C \"$d\" || {{ echo {marker}_FAIL upload; exit 1; }}; ",
    ]
    for distribution in distributions:
        q = shlex.quote(distribution)
        lines.append(
            f"echo {marker}_START {q}; "
            f'if "$P" -m pip install --no-index --find-links "$d" --no-input '
            f"--disable-pip-version-check --root-user-action=ignore {q}; "
            f"then echo {marker}_OK {q}; else echo {marker}_FAIL {q}; fi; "
        )
    lines.append(f"rm -rf \"$d\" {tar_q}")
    return "".join(lines)


def pack_dir(src_dir: str, dest_tar: str) -> str:
    """Pack the files of a directory (not the directory itself) as .tar.gz.

    Args:
        src_dir: a directory of wheels.
        dest_tar: path of the archive to write.

    Returns:
        dest_tar.
    """
    with tarfile.open(dest_tar, "w:gz") as tar:
        for name in sorted(os.listdir(src_dir)):
            tar.add(os.path.join(src_dir, name), arcname=name)
    return dest_tar


def upload_timeout_s(size: int) -> int:
    """Watchdog for uploading `size` bytes."""
    return UPLOAD_BASE_TIMEOUT_S + int(size / UPLOAD_MIN_BYTES_PER_S)


class PrepWorker(QThread):
    """
    Runs one host-side preparation (building a runtime, fetching wheels) off
    the UI thread. The first build of the Qt5 runtime downloads ~100 MB and
    can take minutes; the window has to keep painting and the console has to
    keep moving.

    Signals:
        progress(str): a line for the console.
        done(str): path of the archive ready to upload.
        failed(str): why it could not be prepared.
    """

    progress = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, job: Callable[[Callable[[str], None]], str],
                 parent: Optional[QObject] = None) -> None:
        """
        Args:
            job: called on the worker thread with a progress callback;
                returns the path to upload.
            parent: parent QObject.
        """
        super().__init__(parent)
        self._job = job

    def run(self) -> None:
        """Run the job; any exception becomes failed(str)."""
        try:
            path = self._job(self.progress.emit)
        except Exception as exc:  # reported, never swallowed: see failed
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(str(path))


def _job_launcher(progress: Callable[[str], None]) -> str:
    """Pack the launcher files; trivially fast, but kept on the same path."""
    out = os.path.join(tempfile.mkdtemp(prefix="hmi-qt-"), "hmi-qt-launcher.tar.gz")
    progress("Packing the Qt app launcher...")
    return pack_launcher(out)


def _job_runtime(binding: str) -> Callable[[Callable[[str], None]], str]:
    """The job that produces the runtime upload for `binding`."""
    from . import qt_runtime

    def job(progress: Callable[[str], None]) -> str:
        if binding == "pyside2":
            return str(qt_runtime.build_pyside2_runtime(progress))
        wheels = qt_runtime.pyside6_wheels(progress)
        out = os.path.join(tempfile.mkdtemp(prefix="hmi-qt-"), "hmi-pyside6-wheels.tar.gz")
        return pack_dir(str(wheels), out)

    return job


def _job_app_wheels(distributions: List[str], binding: str):
    """The job that fetches the app's packages as wheels for the panel."""
    from . import qt_runtime

    def job(progress: Callable[[str], None]) -> str:
        wheels = qt_runtime.app_wheels(
            list(distributions), panel_python_version(binding), progress
        )
        out = os.path.join(tempfile.mkdtemp(prefix="hmi-deps-"), "hmi-app-wheels.tar.gz")
        return pack_dir(str(wheels), out)

    return job


class QtRuntimeDeployMixin:
    """
    The Qt-runtime stage of MainWindow's deploy chain, and its offline
    package install. Written against MainWindow's own helpers (run_ssh_worker,
    run_upload_worker, the _progress_* family, log) so the stage looks and
    fails like every other step of a deploy.
    """

    # ------------------------------------------------------------ entry

    def _start_qt_runtime_stage(self) -> bool:
        """Begin the stage if this bundle is a Qt app; False if it is not."""
        binding = needs_qt_runtime(self.current_manifest)
        if binding is None:
            return False
        self._qt_binding_needed = binding
        self._qt_rechecked = False
        self._check_qt_runtime()
        return True

    def _qt_connection(self):
        """(host, user, port, key) from the connection fields."""
        return (
            self.inp_host.text().strip(), self.inp_user.text().strip(),
            self.ssh_port(), self.inp_key.text().strip(),
        )

    def _check_qt_runtime(self) -> None:
        """Ask the panel what the Qt bundle needs and it lacks."""
        binding = self._qt_binding_needed
        label = "PySide2 (Qt 5)" if binding == "pyside2" else "PySide6 (Qt 6)"
        self._progress_busy(f"Checking the panel for {label}...")
        self._qt_have = {}
        host, user, port, key = self._qt_connection()
        self.run_ssh_worker(
            build_ssh_cmd(host, user, port, key, build_runtime_check_command(binding)),
            "Qt runtime check", self._on_qt_runtime_checked,
            timeout_s=CHECK_TIMEOUT_S, line_hook=self._note_qt_runtime_line,
        )

    def _note_qt_runtime_line(self, line: str) -> None:
        """Collect RT verdicts."""
        parsed = parse_runtime_line(line.strip())
        if parsed:
            self._qt_have[parsed[0]] = parsed[1]

    # ------------------------------------------------------------ decide

    def _on_qt_runtime_checked(self, code: int) -> None:
        """Work out what to install, ask once, then install it in order."""
        if code != 0 or not self._qt_have:
            self._qt_fail(self._transport_failure("the Qt runtime check", code))
            return

        if not self._qt_have.get("weston", False):
            self._qt_fail(
                "This panel has no Wayland compositor (weston), which a Qt "
                "application needs to display. It cannot run this bundle."
            )
            return

        steps = []
        if not (self._qt_have.get("launcher") and self._qt_have.get("installer")):
            steps.append("launcher")
        if not (self._qt_have.get("python") and self._qt_have.get("qt")):
            steps.append("runtime")

        if not steps:
            self.log("Qt runtime: the panel has everything this bundle needs.")
            self._start_dependency_scan()
            return
        if self._qt_rechecked:
            # Installed, and still not importable: say so rather than loop.
            missing = ", ".join(k for k, v in self._qt_have.items() if not v)
            self._qt_fail(f"The Qt runtime was installed but the panel still reports missing: {missing}.")
            return

        binding = self._qt_binding_needed
        what = []
        if "launcher" in steps:
            what.append("the Qt app launcher (hmi-gui) and an hmi-install that "
                        "starts it for Qt bundles")
        if "runtime" in steps:
            what.append(
                f"the PySide2 / Qt 5 runtime at {QT5_ROOT} (~100 MB, built on "
                "this PC the first time)" if binding == "pyside2" else
                "PySide6 into /opt/hmi-python (~150 MB of wheels, fetched on "
                "this PC the first time)"
            )
        self.log("Qt runtime: this panel needs " + "; ".join(what) + ".")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Qt runtime needed on the panel")
        box.setText(
            "This bundle is a Qt application, and the panel runs Qt-free.\n\n"
            "To run it, the Studio will install:\n    - "
            + "\n    - ".join(what)
            + "\n\nDesigner bundles keep using hmi-ui; the panel switches back "
            "when one is deployed."
        )
        go = box.addButton("Install and deploy", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(go)
        box.exec()
        if box.clickedButton() is not go:
            self.log("Deployment cancelled.")
            self._progress_cancel("Cancelled -- the panel has no Qt runtime.")
            self.btn_deploy.setEnabled(self.bundle_dir is not None)
            return

        self._qt_steps = steps
        self._qt_next_step()

    # ------------------------------------------------------------ install

    def _qt_next_step(self) -> None:
        """Prepare, upload and install the next missing piece; then re-check."""
        if not self._qt_steps:
            self._qt_rechecked = True
            self._check_qt_runtime()
            return
        step = self._qt_steps.pop(0)
        binding = self._qt_binding_needed
        if step == "launcher":
            self._qt_prepare(
                _job_launcher, "Qt app launcher", build_launcher_install_command,
            )
        else:
            installer = (
                build_qt5_runtime_install_command if binding == "pyside2"
                else lambda tar: build_wheel_install_command(
                    tar, ["PySide6-Essentials"], "pyside6", marker="RT_PIP"
                ) + "; echo 'RT_INSTALLED qt'"
            )
            self._qt_prepare(
                _job_runtime(binding),
                "PySide2 runtime" if binding == "pyside2" else "PySide6",
                installer,
            )

    def _qt_prepare(self, job, what: str, install_command: Callable[[str], str]) -> None:
        """Run a host-side job, then upload its archive and install it."""
        generation = self._deploy_generation
        self._progress_busy(f"Preparing {what}...")
        worker = PrepWorker(job, parent=self)
        self._qt_prep_worker = worker   # keep the thread referenced until it ends

        def on_done(path: str) -> None:
            worker.wait(2000)
            if generation != self._deploy_generation:
                return
            self._qt_upload_and_install(path, what, install_command)

        def on_failed(message: str) -> None:
            worker.wait(2000)
            if generation != self._deploy_generation:
                return
            self._qt_fail(f"Could not prepare {what}: {message}")

        worker.progress.connect(self.log)
        worker.progress.connect(lambda line: self._progress_busy(line[:90]))
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        worker.start()

    def _qt_upload_and_install(self, path: str, what: str,
                               install_command: Callable[[str], str]) -> None:
        """Upload one prepared archive, then run its install command."""
        host, user, port, key = self._qt_connection()
        generation = self._deploy_generation
        size = os.path.getsize(path)
        remote = f"{REMOTE_STAGE}/{os.path.basename(path)}"

        def on_upload(code: int) -> None:
            if generation != self._deploy_generation:
                return
            if code != 0:
                self._qt_fail(self._transport_failure(f"the {what} upload", code))
                return
            self._progress_busy(f"Installing {what} on the panel...")
            self.run_ssh_worker(
                build_ssh_cmd(host, user, port, key, install_command(remote)),
                f"Install {what}", on_install,
                timeout_s=RUNTIME_INSTALL_TIMEOUT_S, heartbeat_s=10,
            )

        def on_install(code: int) -> None:
            if generation != self._deploy_generation:
                return
            if code != 0:
                self._qt_fail(f"Installing {what} on the panel failed (exit {code}); see the console.")
                return
            self.log(f"Installed {what} on the panel.")
            self._qt_next_step()

        self.log(f"Uploading {what}: {size / (1024 * 1024):.1f} MB...")
        self.run_upload_worker(
            build_upload_cmd(host, user, port, key, remote),
            path, size, f"Upload {what}", on_upload, timeout_s=upload_timeout_s(size),
        )

    def _qt_fail(self, reason: str) -> None:
        """End the deploy at this stage."""
        self._progress_fail(reason)
        self.btn_deploy.setEnabled(self.bundle_dir is not None)

    # ------------------------------------------------------------ app packages

    def _start_offline_dep_install(self, distributions: List[str]) -> None:
        """Fetch the app's packages as wheels here and install them offline.

        Args:
            distributions: requirement names the panel could not import.

        Reports through MainWindow's existing _note_pip_line and
        _on_deps_installed, so the verify-by-importing step that follows is
        unchanged.
        """
        binding = needs_qt_runtime(self.current_manifest) or self._qt_binding()
        generation = self._deploy_generation
        self._progress_busy(f"Fetching {len(distributions)} package(s) for the panel...")
        worker = PrepWorker(_job_app_wheels(distributions, binding), parent=self)
        self._qt_prep_worker = worker

        def on_done(path: str) -> None:
            worker.wait(2000)
            if generation != self._deploy_generation:
                return
            host, user, port, key = self._qt_connection()
            size = os.path.getsize(path)
            remote = f"{REMOTE_STAGE}/{os.path.basename(path)}"

            def on_upload(code: int) -> None:
                if generation != self._deploy_generation:
                    return
                if code != 0:
                    self._qt_fail(self._transport_failure("the package upload", code))
                    return
                self._progress_busy(f"Installing {self._pip_total} package(s) on the panel...")
                self.run_ssh_worker(
                    build_ssh_cmd(host, user, port, key,
                                  build_wheel_install_command(remote, distributions, binding)),
                    "Install packages", self._on_deps_installed,
                    timeout_s=RUNTIME_INSTALL_TIMEOUT_S, heartbeat_s=10,
                    line_hook=self._note_pip_line,
                )

            self.run_upload_worker(
                build_upload_cmd(host, user, port, key, remote),
                path, size, "Upload packages", on_upload, timeout_s=upload_timeout_s(size),
            )

        def on_failed(message: str) -> None:
            worker.wait(2000)
            if generation != self._deploy_generation:
                return
            self._qt_fail(f"Could not fetch the packages on this PC: {message}")

        worker.progress.connect(self.log)
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        worker.start()
