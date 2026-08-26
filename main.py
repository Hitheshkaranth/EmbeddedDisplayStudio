#!/usr/bin/env python3
"""
main.py
Layer: 3 (Host Deployer)
Purpose: The one entry point for EmbeddedDisplay Studio, from a checkout and
         from the packaged executable alike.

    python main.py                 # from the repository root
    EmbeddedDisplayStudio.exe      # the same thing, packaged

Why the sub-commands
--------------------
Two jobs must run in a child process rather than on the UI thread: scanning a
bundle's imports (ast.parse holds the GIL for the whole of one file, and a
generated resource module can be megabytes) and hosting the customer's
application for the live preview.

From a checkout those children are `python -m schema.deps` and `python -c
<shim>`. A packaged build has no interpreter to call: sys.executable is the
Studio itself. So the Studio re-executes *itself* with one of these flags, and
the child does the one job and exits. This is what lets the executable preview
a PySide6 application on a machine with no Python installed at all -- the
runtime it needs is the one it already carries.

The flags are deliberately not in --help: they are an implementation detail of
how the Studio talks to itself, not a supported command line.
"""
import sys


def _flags():
    """The two sub-command flags, read from the code that passes them.

    Imported lazily and from their owners rather than restated here: a flag
    the launcher and the dispatcher disagree about would fail as a Studio that
    silently opens a second window instead of a preview.
    """
    from tools.hmi_deployer.deployer import DEPS_SCAN_FLAG
    from tools.hmi_deployer.native_preview import PIP_FLAG, PREVIEW_SHIM_FLAG
    return PREVIEW_SHIM_FLAG, DEPS_SCAN_FLAG, PIP_FLAG


def _run_preview_shim() -> int:
    """Host the customer's application and stream frames to the Studio.

    The shim text lives beside the code that launches it, so a checkout and a
    packaged build cannot drift into running different previews.
    """
    from tools.hmi_deployer.native_preview import _SHIM
    exec(compile(_SHIM, "<preview-shim>", "exec"), {"__name__": "__main__"})
    return 0


def _run_deps_scan(argv) -> int:
    """Scan a bundle for the distributions it imports."""
    from schema.deps import main as deps_main
    # deps.main() takes argv in script form: [program, bundle_dir].
    return deps_main(["deps", *argv])


def _run_pip(argv) -> int:
    """Run pip against this runtime.

    pip is pure Python, so a packaged Studio can carry it and run it under its
    own frozen interpreter. That is what lets the executable install a
    customer application's third-party packages on a machine that has no
    Python at all -- there is nothing for the user to install first, which was
    the whole problem with telling them to pip install something.
    """
    from pip._internal.cli.main import main as pip_main
    return pip_main(list(argv))


def main(argv=None) -> int:
    """Dispatch to a child-process job, or start the Studio."""
    argv = list(sys.argv[1:] if argv is None else argv)
    preview_shim_flag, deps_scan_flag, pip_flag = _flags()

    if argv[:1] == [preview_shim_flag]:
        return _run_preview_shim()

    if argv[:1] == [deps_scan_flag]:
        return _run_deps_scan(argv[1:])

    if argv[:1] == [pip_flag]:
        return _run_pip(argv[1:])

    from tools.hmi_deployer.app import main as studio_main
    studio_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
