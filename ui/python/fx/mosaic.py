"""ui/python/fx/mosaic.py -- a pixel-mosaic loader that dissolves into an image.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-D. Port of libdev
packages/img-fx, 'sweep-gradient' preset (dark / light palettes), in
QPainter with no numpy: a grid of square cells (constant cell size, grid =
max(2, floor(22.28 * W / 320)) columns, same for rows) each filled with
the sweep-gradient field's colour for that cell (two diagonal bands
crossing every ~2.4 s, per-cell flicker re-rolled ~4.2 times a second,
5-colour palette with Gaussian weights), a thin gap between cells, the
contrast gate against the background and the 20-24 px edge fade. When an
image arrives, the reveal runs for REVEAL_S seconds with easeOutCubic: a
cell-stepped diagonal front sweeps the sharp image in, cells near the front
show the image's own blocky average colour (per-cell random drop times),
and the loader fades out underneath. Rendering is throttled to 15 fps, as
the web engine caps at 10.

MosaicView is a widget showing: the loader (while loading()), the reveal
(after set_image during a load), or the image (fitted, aspect kept, centred,
as a QLabel with a scaled pixmap would) -- or a message line.
"""
from __future__ import annotations

from ui.python.fx import FxWidget

REVEAL_S = 2.65


class MosaicView(FxWidget):
    """Args: radius -- corner radius of the tile in px (clip)."""

    fps = 15.0

    def __init__(self, parent=None, radius: float = 8.0):
        super().__init__(parent)
        raise NotImplementedError

    def set_loading(self) -> None:
        """Show the animated loader (starts the animation)."""
        raise NotImplementedError

    def set_image(self, image) -> None:
        """A QImage (or None). During a load: reveal it; otherwise show it at
        once. The animation stops when the reveal ends."""
        raise NotImplementedError

    def set_message(self, text: str) -> None:
        """Show a line of text (centred, muted) instead of an image; stops."""
        raise NotImplementedError

    def loading(self) -> bool:
        raise NotImplementedError

    def revealing(self) -> bool:
        raise NotImplementedError

    def image(self):
        """The current QImage, or None."""
        raise NotImplementedError

    def message(self) -> str:
        raise NotImplementedError
