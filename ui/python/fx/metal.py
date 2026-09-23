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

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

from ui.python.fx import FxWidget, smoothstep

PRESETS = ("chromatic", "silver", "gold")

# engine/presets.ts: (tint rgba 0..1, speed, repetition, softness, shiftRed,
# shiftBlue, shaderOpacity) per preset and theme.
_PRESET_VALUES = {
    ("chromatic", "dark"): ((0x88 / 255, 0xcc / 255, 1.0, 0x2e / 255), 1.0, 2.0, 0.09, 0.75, 0.75, 1.0),
    ("chromatic", "light"): ((0x66 / 255, 0xb0 / 255, 1.0, 0x99 / 255), 1.0, 1.5, 0.05, 0.6, 0.6, 1.0),
    ("silver", "dark"): ((1.0, 1.0, 1.0, 0x66 / 255), 1.0, 1.5, 0.05, 0.3, 0.3, 0.88),
    ("silver", "light"): ((1.0, 1.0, 1.0, 0x40 / 255), 1.0, 1.5, 0.05, 0.3, 0.3, 1.0),
    ("gold", "dark"): ((1.0, 0xcc / 255, 0x55 / 255, 0xcc / 255), 0.85, 1.5, 0.05, 0.3, 0.3, 0.92),
    ("gold", "light"): ((0xf7 / 255, 0xd4 / 255, 0x88 / 255, 0xaa / 255), 1.0, 1.5, 0.05, 0.3, 0.3, 1.0),
}

# The shader's stripe endpoints (hard-coded in Paper's liquidMetal).
_C1 = (0.98, 0.98, 1.0)
_C2 = (0.1, 0.1, 0.14)
_BUMP = 0.45                 # a typical dome value for the band widths
_ANGLE = math.radians(20.0)  # stripes this far off vertical
_SPAN = 140.0                # the web's field, px per unit of shaderScale

_stop_cache: dict = {}


def _band_widths():
    """colorChanges' breakpoints of one period (w[0], w[1] at a typical bump)."""
    w0 = 0.12 * (1.0 - 0.4 * _BUMP)
    w1 = 0.07 * (1.0 + 0.4 * _BUMP) - 0.02 * smoothstep(0.0, 1.0, 0.5 + _BUMP)
    b1 = w0
    b2 = w0 + 0.4 * (1.0 - _BUMP) * w1
    b3 = w0 + 0.5 * (1.0 - _BUMP) * w1
    b3 = max(b3, b2 + 0.012)                 # keep the thin white line visible
    b4 = max(w0 + w1, b3 + 0.012)
    return (b1, b2, b3, b4)


def _channel(c1: float, c2: float, p: float, bands, blur: float, tint: float, tint_a: float) -> float:
    """One channel of the shader's colorChanges band at stripe phase p."""
    p = p - math.floor(p)
    b1, b2, b3, b4 = bands
    ch = c2 + (c1 - c2) * smoothstep(0.0, 2.0 * blur, p)
    ch = ch + (c2 - ch) * smoothstep(b1, b1 + 2.0 * blur, p)
    ch = ch + (c1 - ch) * smoothstep(b2, b2 + 2.0 * blur, p)
    ch = ch + (c2 - ch) * smoothstep(b3, b3 + 2.0 * blur, p)
    ch = ch + (c1 - ch) * smoothstep(b4, b4 + 2.0 * blur, p)
    wide = 1.0 - b4
    g = c1 + (c2 - c1) * smoothstep(0.0, 1.0, (p - b4) / wide)
    ch = ch + (g - ch) * smoothstep(b4, b4 + 0.5 * blur + 1e-6, p)
    # the preset tint as colour-burn, weighted by its alpha
    burn = 1.0 - min(1.0, (1.0 - ch) / max(tint, 0.0001))
    ch = ch + (burn - ch) * tint_a
    return 0.0 if ch < 0.0 else 1.0 if ch > 1.0 else ch


def _stops(preset: str, theme: str, blur: float):
    """Gradient stops for one period, the three channels sampled at their
    own dispersion offsets (the three Plus-composited copies of the brief,
    folded into one gradient: same pixels, a third of the fills)."""
    key = (preset, theme, round(blur, 4))
    stops = _stop_cache.get(key)
    if stops is not None:
        return stops
    tint, _speed, _rep, _soft, shift_r, shift_b, _op = _PRESET_VALUES[(preset, theme)]
    # the shader's dR ~ (1 - bump) * shiftRed / 20, dB ~ 1.3x that
    d_r = 0.4 * shift_r / 20.0
    d_b = 0.5 * shift_b / 20.0
    bands = _band_widths()
    marks = {0.0, 1.0}
    for shift in (0.0, -d_r, d_b):           # where each channel's edges land
        for b in (0.0,) + bands:
            for e in (0.0, 2.0 * blur):
                marks.add((b + e + shift) % 1.0)
    for i in range(1, 16):                   # the long fade (burn is non-linear)
        marks.add(bands[3] + (1.0 - bands[3]) * i / 16.0)
    stops = []
    for p in sorted(marks):
        r = _channel(_C1[0], _C2[0], p + d_r, bands, blur, tint[0], tint[3])
        g = _channel(_C1[1], _C2[1], p, bands, blur, tint[1], tint[3])
        b = _channel(_C1[2], _C2[2], p - d_b, bands, blur, tint[2], tint[3])
        stops.append((p, QColor.fromRgbF(r, g, b, 1.0)))
    if len(_stop_cache) > 64:
        _stop_cache.clear()
    _stop_cache[key] = stops
    return stops


def paint_metal(painter: QPainter, path: QPainterPath, t: float, preset: str = "chromatic",
                theme: str = "dark", scale: float = 1.6, opacity: float = 1.0) -> None:
    """Fill `path` with the liquid-metal look at time t (seconds). `scale`
    is the web shaderScale: the stripe field spans 140*scale px, centred on
    the path's bounding box. Leaves the painter's state unchanged."""
    if preset not in PRESETS:
        preset = "chromatic"
    theme = "light" if theme == "light" else "dark"
    box = path.boundingRect()
    if box.isEmpty():
        return
    _tint, speed, rep, soft, _sr, _sb, shader_opacity = _PRESET_VALUES[(preset, theme)]
    span = _SPAN * max(0.05, scale)
    cw = rep * 2.0
    period = span / cw * 1.25                # px per colorChanges period
    blur = max(soft / 15.0, 1.6 / period)    # stripe AA never below ~1.5 px
    phase = 0.3 * (t * speed + 2.8)          # periods scrolled

    centre = box.center()
    # gradient axis: perpendicular to stripes that lean 20 deg off vertical
    ax, ay = math.cos(_ANGLE), -math.sin(_ANGLE)
    base = (phase % 1.0) * period - span / 2
    stops = _stops(preset, theme, blur)

    def stripes(shift: float) -> QLinearGradient:
        off = base + shift
        start = QPointF(centre.x() + off * ax, centre.y() + off * ay)
        grad = QLinearGradient(start, QPointF(start.x() + period * ax, start.y() + period * ay))
        grad.setSpread(QLinearGradient.RepeatSpread)
        grad.setStops(stops)
        return grad

    painter.save()
    try:
        painter.setOpacity(painter.opacity() * max(0.0, min(1.0, opacity)) * shader_opacity)
        painter.setPen(Qt.NoPen)
        # The shader's bands bend around its dome: fill in horizontal slices
        # (cheap rect clips), each with the stripe shifted by a bowl-shaped
        # offset plus a slow wobble, so the straight gradient reads as
        # curved, flowing metal.
        top, h = box.top(), box.height()
        slices = max(1, min(36, int(h // 1.25)))
        if slices == 1:
            painter.fillPath(path, stripes(0.0))
        else:
            clip0 = painter.clipPath() if painter.hasClipping() else None
            y0 = math.floor(top)
            step = (math.ceil(box.bottom()) - y0) / slices
            for i in range(slices):
                a = round(y0 + i * step)
                b = round(y0 + (i + 1) * step)
                yn = ((a + b) / 2 - top) / h * 2.0 - 1.0          # -1 top .. 1 bottom
                bend = period * (0.12 * yn * yn + 0.035 * math.sin(3.0 * yn + t * 0.9 * speed))
                if clip0 is None:
                    painter.setClipRect(QRectF(box.left() - 1, a, box.width() + 2, b - a))
                else:
                    painter.setClipPath(clip0)
                    painter.setClipRect(QRectF(box.left() - 1, a, box.width() + 2, b - a), Qt.IntersectClip)
                painter.fillPath(path, stripes(bend))
            if clip0 is None:
                painter.setClipping(False)
            else:
                painter.setClipPath(clip0)
        # The dome "bump": the shader's stripes flatten into a bright,
        # low-centred swell. A white radial highlight carries it.
        w, h = box.width(), box.height()
        dome_c = QPointF(centre.x(), box.top() + h * 0.78)
        dome = QRadialGradient(dome_c, max(w, h) * 0.55, QPointF(centre.x(), box.bottom()))
        glow = QColor(255, 236, 190) if preset == "gold" else QColor(255, 255, 255)
        for pos, alpha in ((0.0, 105 if theme == "dark" else 90), (0.45, 40), (1.0, 0)):
            glow.setAlpha(alpha)
            dome.setColorAt(pos, glow)
        painter.fillPath(path, dome)
        # a soft shade from the top: the shader's field darkens as uv.y -> 0
        shade = QLinearGradient(QPointF(0, box.top()), QPointF(0, box.top() + h * 0.5))
        shade.setColorAt(0.0, QColor(0, 0, 0, 55))
        shade.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, shade)
    finally:
        painter.restore()


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    r = max(0.0, min(radius, rect.width() / 2, rect.height() / 2))
    path.addRoundedRect(rect, r, r)
    return path


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
        self._child = child
        self._ring = max(0.0, float(ring))
        self._radius = radius
        self._padding = max(0.0, float(padding))
        self._preset = preset if preset in PRESETS else "chromatic"
        child.setParent(self)
        child.show()
        self._layout_child()

    def child(self):
        return self._child

    def set_preset(self, preset: str) -> None:
        self._preset = preset if preset in PRESETS else "chromatic"
        self.update()

    def ring_rect(self) -> QRectF:
        """The outer rect of the metal band in this widget's coordinates."""
        return QRectF(0.0, 0.0, float(self.width()), float(self.height()))

    # -- internals
    def _inset(self) -> int:
        return int(math.ceil(self._ring + self._padding))

    def _outer_radius(self) -> float:
        rect = self.ring_rect()
        full = min(rect.width(), rect.height()) / 2
        return full if self._radius is None else max(0.0, min(float(self._radius), full))

    def _layout_child(self) -> None:
        inset = self._inset()
        self._child.setGeometry(inset, inset, max(0, self.width() - 2 * inset),
                                max(0, self.height() - 2 * inset))

    def sizeHint(self):
        hint = self._child.sizeHint()
        inset = self._inset()
        return QSize(max(0, hint.width()) + 2 * inset, max(0, hint.height()) + 2 * inset)

    def resizeEvent(self, event):
        self._layout_child()
        super().resizeEvent(event)

    def paint_frame(self, painter, t: float) -> None:
        rect = self.ring_rect()
        if rect.width() < 2 or rect.height() < 2:
            return
        dark = self._theme != "light"
        radius = self._outer_radius()
        outer = _rounded(rect, radius)
        inner_rect = rect.adjusted(self._ring, self._ring, -self._ring, -self._ring)
        inner = _rounded(inner_rect, max(0.0, radius - self._ring))
        painter.save()
        try:
            painter.setPen(Qt.NoPen)
            painter.fillPath(outer, QColor("#272727") if dark else QColor("#ffffff"))
            if self._ring > 0:
                band = outer.subtracted(inner)
                # the web crops a 140*scale window centred on the element;
                # a small ring wants a smaller field so a few bands show
                scale = max(0.35, min(1.6, max(rect.width(), rect.height()) / 140.0))
                paint_metal(painter, band, t, preset=self._preset, theme=self._theme, scale=scale)
                # the white rim light along the top of the band
                rim = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.top() + rect.height() * 0.45))
                rim.setColorAt(0.0, QColor(255, 255, 255, 120 if dark else 150))
                rim.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillPath(band, rim)
            # the 1 px inner hairline on the root's edge
            painter.setPen(QPen(QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 15), 1.0))
            painter.setBrush(Qt.NoBrush)
            hair = rect.adjusted(0.5, 0.5, -0.5, -0.5)
            painter.drawPath(_rounded(hair, max(0.0, radius - 0.5)))
            if self._ring > 0 and dark:
                # the dark hairline where the metal meets the interior
                painter.setPen(QPen(QColor(0, 0, 0, 115), 1.0))
                edge = inner_rect.adjusted(-0.5, -0.5, 0.5, 0.5)
                painter.drawPath(_rounded(edge, max(0.0, radius - self._ring + 0.5)))
        finally:
            painter.restore()
