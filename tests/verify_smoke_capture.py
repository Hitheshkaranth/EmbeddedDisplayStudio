"""
tests/verify_smoke_capture.py
Layer: Test (W11)

Checks that a bezel grab taken from the packaged executable actually contains
the smoke fixture's application.

Why a separate script rather than a unittest: this runs against a built
artefact, not against the source tree, and it is the last gate before a binary
is attached to a release. Its whole value is that it fails when the source is
green and the executable is not -- which is precisely what shipped in 0.0.1,
where the released binary died on a customer application's first standard
library import while every test passed.

    python tests/verify_smoke_capture.py <capture.png>

Exits 0 when the fixture's colour is present in the grab, 1 otherwise.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtGui import QImage, QColor  # noqa: E402

# Kept in step with tests/fixtures/ci-smoke/main.py by hand: the fixture must
# not import from the repository, because it is executed by a frozen runtime
# that has never heard of it.
SMOKE_COLOUR = "#ff00d4"

# How many pixels of the fixture's colour count as "the application rendered".
# A handful could be an artefact of scaling; a panel filled by the fixture is
# thousands. Low enough to survive the bezel scaling the frame down, high
# enough that a stray pixel cannot pass.
MIN_MATCHING_PIXELS = 500


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: verify_smoke_capture.py <capture.png>\n")
        return 2

    path = Path(argv[1])
    if not path.is_file():
        sys.stderr.write(
            f"FAIL: no capture at {path}. The executable did not reach the "
            f"point of grabbing its bezel.\n"
        )
        return 1

    image = QImage(str(path))
    if image.isNull() or image.width() == 0:
        sys.stderr.write(f"FAIL: {path} is not a readable image.\n")
        return 1

    wanted = QColor(SMOKE_COLOUR).rgb()
    matching = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixel(x, y) == wanted:
                matching += 1

    print(f"capture {image.width()}x{image.height()}, "
          f"{matching} px of {SMOKE_COLOUR}")

    if matching < MIN_MATCHING_PIXELS:
        sys.stderr.write(
            f"FAIL: the bundle's colour appears {matching} times, under the "
            f"{MIN_MATCHING_PIXELS} expected. The window opened but the "
            f"application was not rendered inside the bezel.\n"
        )
        return 1

    print("OK: the packaged executable previewed the bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
