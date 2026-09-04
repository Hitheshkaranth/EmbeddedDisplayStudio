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

Exits 0 when both halves of the fixture's EFIS horizon are present, 1 otherwise.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtGui import QImage, QColor  # noqa: E402

# The QML fixture deliberately fills the panel with an attitude indicator.
# Requiring both convention colours proves that the Shadcn import resolved and
# the custom Canvas/Rectangle hierarchy rendered; a shell fallback contains
# neither colour.
SMOKE_COLOURS = ("#2b6fb5", "#7a5230")

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

    counts = {colour: 0 for colour in SMOKE_COLOURS}
    wanted = {QColor(colour).rgb(): colour for colour in SMOKE_COLOURS}
    for y in range(image.height()):
        for x in range(image.width()):
            colour = wanted.get(image.pixel(x, y))
            if colour is not None:
                counts[colour] += 1

    print(f"capture {image.width()}x{image.height()}, " +
          ", ".join(f"{count} px of {colour}" for colour, count in counts.items()))

    insufficient = {colour: count for colour, count in counts.items()
                    if count < MIN_MATCHING_PIXELS}
    if insufficient:
        sys.stderr.write(
            "FAIL: the avionics horizon is incomplete: " +
            ", ".join(f"{colour}={count}" for colour, count in insufficient.items()) +
            f" (minimum {MIN_MATCHING_PIXELS} each). The window opened but the "
            "application was not rendered inside the bezel.\n"
        )
        return 1

    print("OK: the packaged executable previewed the bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
