"""Frozen entry point for EmbeddedDisplay Studio.

`python -m tools.hmi_deployer.app` is the way the Studio is started from a
checkout, but PyInstaller freezes a script rather than a module. This is that
script, and it is deliberately the only thing in it: everything the Studio
does still lives in the package.
"""
import sys


def main() -> None:
    from tools.hmi_deployer.app import main as studio_main
    studio_main()


if __name__ == "__main__":
    sys.exit(main())
