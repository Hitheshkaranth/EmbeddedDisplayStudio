"""ui/python/fx/metal.py -- liquid-metal surfaces.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-D. Port of libdev
packages/metal-fx. The web version renders Paper Shaders' liquidMetal
fragment shader (WebGL); here it is the pure-gradient approximation (no
numpy, no GL): a repeating stripe QLinearGradient ~20 deg off vertical whose
stops follow the shader's colorChanges band (bright white band, thin dark
line, thin white line, dark, long white->near-black fade, hard jump back),
scrolling 0.3 periods per second; chromatic dispersion by painting the
stripe three times, one channel each, offset, with CompositionMode_Plus;
the dome "bump" as a white radial highlight low-centre; the preset tint as
a colour-burn applied to the stop colours. Presets: chromatic (default),
silver, gold, each with dark / light values (engine/presets.ts). Metal runs
at 15 fps like the web renderer.

paint_metal() fills any path; MetalRing wraps a widget in a metal rim.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPainterPath

from ui.python.fx import FxWidget

PRESETS = ("chromatic", "silver", "gold")


def paint_metal(painter: QPainter, path: QPainterPath, t: float, preset: str = "chromatic",
                theme: str = "dark", scale: float = 1.6, opacity: float = 1.0) -> None:
    """Fill `path` with the liquid-metal look at time t (seconds). `scale`
    is the web shaderScale: the stripe field spans 140*scale px, centred on
    the path's bounding box. Leaves the painter's state unchanged."""
    raise NotImplementedError


class MetalRing(FxWidget):
    """A rim of liquid metal around a child widget.

    MetalRing(child, ring=2, radius=None, padding=3): the ring widget lays
    `child` out inside itself (padding px from the ring's inner edge) and
    paints, behind the child: the root fill (#272727 dark / #ffffff light),
    the metal in a band `ring` px wide along its rounded outline (radius
    None = fully round, i.e. min(w,h)/2), the 1 px inner hairline
    (rgba(255,255,255,.1) dark / rgba(0,0,0,.06) light) and a white top rim
    light. It animates while running (start/stop).
    """

    fps = 15.0

    def __init__(self, child, ring: float = 2.0, radius: float | None = None,
                 padding: float = 3.0, preset: str = "chromatic", parent=None):
        super().__init__(parent)
        raise NotImplementedError

    def child(self):
        raise NotImplementedError

    def set_preset(self, preset: str) -> None:
        raise NotImplementedError

    def ring_rect(self) -> QRectF:
        """The outer rect of the metal band in this widget's coordinates."""
        raise NotImplementedError
