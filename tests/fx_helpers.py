"""Shared helpers for the tests/test_fx_*.py gates (UI FX swarm, 2026-09-23).

Effects take time only through `t`: a test drives a widget with
widget._tick(base + dt) (FxWidget._tick) instead of sleeping, so frames are
deterministic. Pixel checks work on QImages from FxWidget.render_at or
QWidget.grab().toImage().
"""
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "/usr/share/fonts")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def app():
    return QApplication.instance() or QApplication(sys.argv)


def pixels(image: QImage, step: int = 1):
    """(x, y, QColor) for every `step`-th pixel."""
    image = image.convertToFormat(QImage.Format_ARGB32)
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            yield x, y, QColor.fromRgba(image.pixel(x, y))


def coverage(image: QImage, alpha_min: int = 8, step: int = 1) -> float:
    """Fraction of pixels with alpha >= alpha_min."""
    total = hit = 0
    for _x, _y, c in pixels(image, step):
        total += 1
        hit += c.alpha() >= alpha_min
    return hit / max(1, total)


def region_alpha(image: QImage, x0: float, y0: float, x1: float, y1: float) -> float:
    """Mean alpha 0..255 over the fractional rect (x0, y0)-(x1, y1) of the image."""
    image = image.convertToFormat(QImage.Format_ARGB32)
    w, h = image.width(), image.height()
    xs = range(int(x0 * w), max(int(x0 * w) + 1, int(x1 * w)))
    ys = range(int(y0 * h), max(int(y0 * h) + 1, int(y1 * h)))
    total = n = 0
    for y in ys:
        for x in xs:
            total += QColor.fromRgba(image.pixel(x, y)).alpha()
            n += 1
    return total / max(1, n)


def difference(a: QImage, b: QImage, step: int = 2) -> float:
    """Mean absolute per-channel difference 0..255 between two images."""
    a = a.convertToFormat(QImage.Format_ARGB32)
    b = b.convertToFormat(QImage.Format_ARGB32)
    if a.size() != b.size():
        return 255.0
    total = n = 0
    for y in range(0, a.height(), step):
        for x in range(0, a.width(), step):
            p, q = a.pixel(x, y), b.pixel(x, y)
            for shift in (0, 8, 16, 24):
                total += abs(((p >> shift) & 255) - ((q >> shift) & 255))
            n += 4
    return total / max(1, n)


def distinct_colours(image: QImage, step: int = 2, quant: int = 16) -> int:
    """How many distinct (quantised) opaque colours the image has."""
    seen = set()
    for _x, _y, c in pixels(image, step):
        if c.alpha() > 32:
            seen.add((c.red() // quant, c.green() // quant, c.blue() // quant))
    return len(seen)


def paint_ms(widget, frames: int = 10) -> float:
    """Average milliseconds for render_at over `frames` successive times."""
    base = time.monotonic()
    start = time.perf_counter()
    for i in range(frames):
        widget.render_at(base + i * 0.033)
    return (time.perf_counter() - start) * 1000 / frames


def clock_has(widget) -> bool:
    """True while `widget` is subscribed to the fx clock."""
    from ui.python.fx import FxClock
    return id(widget) in FxClock.instance()._subs
