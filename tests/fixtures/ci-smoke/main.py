"""A bundle whose only job is to be unmistakable in a screenshot.

Used by the packaging smoke test: the executable is asked to preview this and
grab the bezel, and the grab is searched for this colour. It is deliberately a
colour nothing else in the Studio's chrome uses, so finding it means the frame
came from this application and not from the surrounding UI.

It also imports a standard-library module the Studio itself does not, which is
the failure that shipped in 0.0.1: a frozen build carries only what static
analysis can reach, and an application loaded at runtime is not reachable.
"""
import pkgutil  # noqa: F401  -- the 0.0.1 regression, asserted by being here
import sys

from PySide6.QtWidgets import QApplication, QWidget


SMOKE_COLOUR = "#ff00d4"


def main():
    app = QApplication(sys.argv)
    window = QWidget()
    window.setStyleSheet(f"background: {SMOKE_COLOUR};")
    window.resize(600, 400)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
