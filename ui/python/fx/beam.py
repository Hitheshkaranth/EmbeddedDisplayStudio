"""ui/python/fx/beam.py -- Border Beam: a glow travelling a widget's border.

Port of libdev packages/border-beam (spec/beam-spec.json holds the tuned
numbers; docs/UI_FX.md has the porting notes).

BorderBeam is an overlay: a transparent child widget laid exactly over its
target (it follows the target's resizes through an event filter), clicks go
through it (WA_TransparentForMouseEvents), and it paints the beam layers --
inner glow, 1 px stroke ring, blurred bloom -- over the target's content, as
the web version does. Sizes:
    'sm'   button-sized rotating beam (smallMask, smallColorPalettes)
    'md'   card-sized rotating beam
    'line' a glow travelling along the bottom edge
Colour variants: colorful (default), mono, ocean, sunset (the four in
beam-spec.json). Pulse types are out of scope.

Active / fade: set_active(True) fades in over 0.6 s (CSS "ease") and keeps
the beam moving; set_active(False) fades out over 0.5 s and stops the clock
subscription when the fade ends (nothing is painted then). A toggle during a
fade is remembered and applied when the fade ends.

Hue shift, brightness and saturation (CSS filters) are applied to gradient
stop colours with the 3x3 CSS filter matrices (linear, so equivalent). Blur
is approximated without numpy: draw the layer into a small QImage (e.g. 1/4
size) and scale it up smoothly, or stroke the ring several times with
widening, fading pens -- whichever looks closest in the gallery.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient)

import ui.python.fx as fx
from ui.python.fx import FxWidget

SIZES = ("sm", "md", "line")
VARIANTS = ("colorful", "mono", "ocean", "sunset")
FADE_IN_S = 0.6
FADE_OUT_S = 0.5

# ---------------------------------------------------------------- the spec
# Every number below is from libdev packages/border-beam/spec/beam-spec.json
# (v1.3.0) or src/styles.ts; nothing is read at runtime.

_DURATION_ROTATE = 1.96
_DURATION_LINE = 3.1
_HUE_RANGE = 30.0            # deg, hue-rotate swings +-this
_LINE_HUE_CAP = 13.0
_HUE_PERIOD = 12.0           # s, beam-hue-shift (ease-in-out per half)
_LINE_BLOOM_HUE_PERIOD = 8.0
_LINE_BLOOM_HUE_BONUS = 10.0
_BRIGHTNESS = 1.3            # brightnessFallback
_MONO_OPACITY = 0.5
_INNER_EDGE_PX = 28.0        # rotate.innerEdgeMaskPx
_INNER_SHADOW_BLUR = {"md": 9.0, "sm": 5.0, "line": 9.0}
_BLOOM_BLUR_PX = 8.0
_MONO_LINE_BLOOM_BLUR_PX = 6.0

# sizeThemePresets: (strokeOpacity, innerOpacity, bloomOpacity, innerShadow rgba, saturation)
_THEME = {
    "sm": {"dark": (0.46, 0.24, 0.38, (255, 255, 255, 0.30), 1.2),
           "light": (0.12, 0.30, 0.16, (0, 0, 0, 0.14), 1.8)},
    "md": {"dark": (0.26, 0.42, 0.24, (255, 255, 255, 0.27), 1.2),
           "light": (0.12, 0.26, 0.34, (0, 0, 0, 0.14), 1.5)},
    "line": {"dark": (1.14, 0.70, 0.80, (255, 255, 255, 0.10), 1.2),
             "light": (0.16, 0.32, 0.30, (0, 0, 0, 0.14), 1.95)},
}
_DEFAULT_RADIUS = {"sm": 32.0, "md": 16.0, "line": 16.0}

# Conic stops, (percent, alpha): rotate.whiteGradientStops / bloomGradientStops
_WHITE_STOPS = {
    "dark": ((0, 0), (54, 0), (57, .1), (60, .3), (63, .6), (66, .75), (69, .6), (72, .3),
             (75, .1), (78, 0), (100, 0)),
    "light": ((0, 0), (54, 0), (57, .08), (60, .2), (63, .4), (66, .55), (69, .4), (72, .2),
              (75, .08), (78, 0), (100, 0)),
}
_BLOOM_STOPS = {
    "dark": ((0, 0), (58, 0), (62, .03), (65, .08), (67, .2), (69, .45), (70, .85), (70.5, .85),
             (71.5, .45), (73, .2), (75, .08), (78, .03), (82, 0), (100, 0)),
    "light": ((0, 0), (58, 0), (62, .02), (65, .08), (67, .2), (69, .4), (70, .6), (70.5, .6),
              (71.5, .4), (73, .2), (75, .08), (78, .02), (82, 0), (100, 0)),
}
_BEAM_MASK = ((0, 0), (30, 0), (36, .1), (44, .35), (52, 1), (80, 1), (86, .35), (92, .1),
              (95, 0), (100, 0))
_SMALL_MASK = ((0, 0), (22, 0), (28, .12), (36, .4), (46, 1), (82, 1), (88, .4), (94, .12),
               (97, 0), (100, 0))

# palettes.border: shared geometry (x, y as fractions of the box; ellipse
# radii px) and per-variant colours. CSS lists the top layer first.
_MD_GEOM = ((.33, -.074, 70, 40), (.12, -.05, 60, 35), (.021, .683, 40, 70),
            (.021, .683, 20, 35), (.744, 1.0, 180, 32), (.55, 1.0, 85, 26),
            (.939, 0.0, 74, 32), (1.0, .271, 26, 42), (1.0, .271, 52, 48))
_MD_COLOURS = {
    "colorful": ((255, 50, 100), (40, 140, 255), (50, 200, 80), (30, 185, 170), (100, 70, 255),
                 (40, 140, 255), (255, 120, 40), (240, 50, 180), (180, 40, 240)),
    "mono": ((180,) * 3, (140,) * 3, (160,) * 3, (130,) * 3, (170,) * 3, (150,) * 3,
             (190,) * 3, (145,) * 3, (165,) * 3),
    "ocean": ((100, 80, 220), (60, 120, 255), (80, 100, 200), (50, 140, 220), (120, 80, 255),
              (70, 130, 255), (140, 100, 240), (90, 110, 230), (130, 70, 255)),
    "sunset": ((255, 80, 50), (255, 160, 40), (255, 120, 60), (255, 200, 50), (255, 100, 80),
               (255, 180, 60), (255, 60, 60), (255, 140, 50), (255, 90, 70)),
}
# rotate.innerGradientDerivation
_INNER_SIZE_SCALE = 0.9
_INNER_ALPHA = 0.45
_INNER_ALPHA_MONO = 0.225

# palettes.small
_SM_GEOM = ((.02, .68, 9, 18), (.02, .68, 4, 8), (.72, -.03, 59, 9), (.74, 1.0, 42, 7),
            (1.0, .27, 10, 17), (1.0, .27, 10, 18), (1.0, .27, 5, 10), (1.0, .27, 11, 12))
_SM_COLOURS = {
    "colorful": ((50, 200, 80), (30, 185, 170), (255, 120, 40), (100, 70, 255), (240, 50, 180),
                 (180, 40, 240), (40, 140, 255), (255, 50, 100)),
    "mono": ((160,) * 3, (140,) * 3, (180,) * 3, (150,) * 3, (170,) * 3, (155,) * 3,
             (145,) * 3, (165,) * 3),
    "ocean": ((60, 140, 200), (50, 120, 180), (100, 80, 220), (80, 100, 255), (120, 70, 240),
              (90, 80, 220), (70, 110, 255), (110, 90, 230)),
    "sunset": ((255, 180, 50), (255, 150, 40), (255, 80, 60), (255, 100, 80), (255, 60, 80),
               (255, 120, 60), (255, 200, 50), (255, 90, 70)),
}
_SM_INNER_ALPHA = (.5, .45, .35, .35, .3, .4, .3, .3)
_SM_INNER_ALPHA_MONO = (.25, .22, .17, .17, .15, .20, .15, .15)
# sizePresets.sm: the small palette's px radii are authored for a 70 x 36
# button; they scale with the widget per axis (clamped) so a wider button
# or a chip keeps the same look instead of a few specks.
_SM_REF = (70.0, 36.0)
_SM_SCALE_RANGE = (0.75, 2.5)

# palettes.line: (sizeW, sizeH, offsetX, offsetY) per theme, colours per variant/theme
_LINE_GEOM = {
    "dark": ((36, 36, 0, 2), (30, 32, 39, 0), (33, 28, -36, 2), (29, 34, -54, 0), (27, 30, 51, -1),
             (36, 24, 21, 1), (30, 22, -21, 0), (25, 28, 66, 1), (23, 30, -66, -1)),
    "light": ((45, 36, 0, 2), (35, 32, 65, 0), (40, 28, -60, 2), (35, 34, -90, 0), (38, 30, 85, -1),
              (50, 24, 35, 1), (40, 22, -35, 0), (35, 28, 110, 1), (30, 30, -110, -1)),
}
_LINE_COLOURS = {
    "colorful": {
        "dark": ((255, 50, 100), (40, 180, 220), (50, 200, 80), (180, 40, 240), (255, 160, 30),
                 (100, 70, 255), (40, 140, 255), (240, 50, 180), (30, 185, 170)),
        "light": ((255, 50, 100), (40, 140, 255), (50, 200, 80), (180, 40, 240), (30, 185, 170),
                  (100, 70, 255), (40, 140, 255), (255, 120, 40), (240, 50, 180))},
    "mono": {
        "dark": tuple((v,) * 3 for v in (200, 170, 155, 185, 165, 180, 160, 175, 190)),
        "light": tuple((v,) * 3 for v in (100, 80, 90, 70, 85, 95, 75, 105, 65))},
    "ocean": {
        "dark": ((100, 80, 220), (60, 120, 255), (80, 100, 200), (130, 70, 255), (70, 130, 255),
                 (120, 80, 255), (90, 110, 230), (110, 90, 240), (140, 100, 255)),
        "light": ((80, 60, 200), (50, 100, 220), (70, 90, 190), (110, 60, 220), (60, 110, 230),
                  (100, 70, 240), (80, 100, 210), (90, 80, 225), (120, 90, 245))},
    "sunset": {
        "dark": ((255, 100, 60), (255, 180, 50), (255, 140, 70), (255, 80, 80), (255, 200, 60),
                 (255, 120, 50), (255, 160, 80), (255, 90, 60), (255, 70, 70)),
        "light": ((220, 80, 40), (230, 150, 30), (210, 110, 50), (200, 60, 60), (220, 170, 40),
                  (210, 100, 30), (230, 130, 60), (190, 70, 50), (180, 50, 50))},
}
# palettes.lineInner: geometry + alpha; the colours are the variant's dark line colours
_LINE_INNER_GEOM = ((33, 30, 0, 0), (24, 26, 39, -3), (27, 24, -36, 0), (23, 28, -54, -2),
                    (24, 24, 51, -1), (30, 20, 21, 0), (25, 18, -21, -2), (21, 24, 66, 0),
                    (18, 26, -66, -1))
_LINE_INNER_ALPHA = (.48, .42, .48, .42, .50, .45, .40, .45, .52)
# palettes.border.<variant>.spike / spikeLt (rgba)
_SPIKES = {
    "colorful": {"dark": ((255, 60, 80, 1), (40, 190, 180, .98)),
                 "light": ((200, 30, 60, 1), (20, 150, 140, 1))},
    "mono": {"dark": ((200, 200, 200, 1), (170, 170, 170, 1)),
             "light": ((80, 80, 80, 1), (120, 120, 120, 1))},
    "ocean": {"dark": ((100, 120, 255, 1), (130, 100, 220, .98)),
              "light": ((60, 60, 180, 1), (80, 100, 200, 1))},
    "sunset": {"dark": ((255, 140, 80, 1), (255, 100, 60, .98)),
               "light": ((200, 80, 40, 1), (220, 120, 30, 1))},
}
# palettes.lineBloom.<variant>.<theme>.spikes: (color1, color2) rgba
_LINE_BLOOM = {
    "colorful": {
        "dark": (((100, 70, 255, 1), (100, 70, 255, 1)), ((255, 170, 40, .59), (255, 170, 40, .29)),
                 ((50, 200, 100, 1), (50, 200, 100, 1)), ((200, 50, 240, .91), (200, 50, 240, .45)),
                 ((40, 140, 255, 1), (40, 140, 255, 1))),
        "light": (((80, 50, 200, 1), (80, 50, 200, .8)), ((210, 130, 0, .7), (210, 130, 0, .46)),
                  ((30, 160, 70, 1), (30, 160, 70, .82)), ((160, 30, 190, 1), (160, 30, 190, .7)),
                  ((30, 100, 200, 1), (30, 100, 200, .78)))},
    "mono": {
        "dark": (((200,) * 3 + (1,), (200,) * 3 + (1,)), ((180,) * 3 + (.59,), (180,) * 3 + (.29,)),
                 ((190,) * 3 + (1,), (190,) * 3 + (1,)), ((170,) * 3 + (.91,), (170,) * 3 + (.45,)),
                 ((185,) * 3 + (1,), (185,) * 3 + (1,))),
        "light": (((80,) * 3 + (1,), (80,) * 3 + (.8,)), ((100,) * 3 + (.7,), (100,) * 3 + (.46,)),
                  ((70,) * 3 + (1,), (70,) * 3 + (.82,)), ((90,) * 3 + (1,), (90,) * 3 + (.7,)),
                  ((85,) * 3 + (1,), (85,) * 3 + (.78,)))},
    "ocean": {
        "dark": (((100, 80, 255, 1), (100, 80, 255, 1)), ((80, 130, 220, .59), (80, 130, 220, .29)),
                 ((60, 100, 255, 1), (60, 100, 255, 1)), ((90, 120, 200, .91), (90, 120, 200, .45)),
                 ((120, 90, 255, 1), (120, 90, 255, 1))),
        "light": (((50, 40, 180, 1), (50, 40, 180, .8)), ((40, 80, 200, .7), (40, 80, 200, .46)),
                  ((30, 50, 190, 1), (30, 50, 190, .82)), ((60, 90, 180, 1), (60, 90, 180, .7)),
                  ((70, 60, 200, 1), (70, 60, 200, .78)))},
    "sunset": {
        "dark": (((255, 100, 80, 1), (255, 100, 80, 1)), ((255, 150, 80, .59), (255, 150, 80, .29)),
                 ((255, 80, 60, 1), (255, 80, 60, 1)), ((255, 120, 50, .91), (255, 120, 50, .45)),
                 ((255, 140, 70, 1), (255, 140, 70, 1))),
        "light": (((200, 60, 30, 1), (200, 60, 30, .8)), ((220, 100, 20, .7), (220, 100, 20, .46)),
                  ((180, 40, 20, 1), (180, 40, 20, .82)), ((210, 80, 10, 1), (210, 80, 10, .7)),
                  ((190, 70, 30, 1), (190, 70, 30, .78)))},
}
# line.keyframes: (percent, value); travel/edge linear, the rest ease-in-out
_TRAVEL_X = ((0, .06), (10, .15), (20, .25), (30, .35), (40, .44), (50, .5), (60, .56), (70, .65),
             (80, .75), (90, .85), (100, .94))
_TRAVEL_W = ((0, .5), (10, .8), (20, 1.1), (30, 1.3), (40, 1.45), (50, 1.5), (60, 1.45), (70, 1.3),
             (80, 1.1), (90, .8), (100, .5))
_EDGE_FADE = ((0, 0), (12.5, 0), (32.5, 1), (67.5, 1), (87.5, 0), (100, 0))
_BREATHE = ((0, .8), (25, 1.25), (55, .85), (80, 1.3), (100, .8))
_SPIKE = ((0, .8), (25, 1.3), (50, .9), (75, 1.4), (100, .8))
_SPIKE2 = ((0, 1.2), (25, .7), (50, 1.4), (75, .8), (100, 1.2))
# CSS writes the periods with toFixed(1): duration * scale, rounded
_BREATHE_SCALE, _SPIKE_SCALE, _SPIKE2_SCALE = 1.3, 1.33, 1.7
_LINE_BEAM_MASK = (78, 60, ((0, 1.0), (.45, .5), (1.0, 0.0)))      # line.beamMaskEllipse
_LINE_BLOOM_MASK = (84, 110, ((0, 1.0), (.35, .5), (1.0, 0.0)))    # line.bloomMaskEllipse
_LINE_WHITE = {"dark": (24, 28, 2, (255, 255, 255), ((0, .38), (.30, .12), (.65, 0))),
               "light": (35, 28, 2, (0, 0, 0), ((0, .6), (.35, .25), (.70, 0)))}


# ---------------------------------------------------------------- helpers

def _filter_matrix(hue_deg: float, brightness: float, saturation: float):
    """CSS hue-rotate(h) brightness(b) saturate(s) as one 3x3 (row-major),
    the W3C feColorMatrix maths (colorMatrix.ts composedFilterMatrix)."""
    rad = math.radians(hue_deg)
    c, s, b = math.cos(rad), math.sin(rad), brightness
    hue = ((0.213 + c * 0.787 - s * 0.213) * b, (0.715 - c * 0.715 - s * 0.715) * b, (0.072 - c * 0.072 + s * 0.928) * b,
           (0.213 - c * 0.213 + s * 0.143) * b, (0.715 + c * 0.285 + s * 0.140) * b, (0.072 - c * 0.072 - s * 0.283) * b,
           (0.213 - c * 0.213 - s * 0.787) * b, (0.715 - c * 0.715 + s * 0.715) * b, (0.072 + c * 0.928 + s * 0.072) * b)
    t = saturation
    sat = (0.213 + 0.787 * t, 0.715 - 0.715 * t, 0.072 - 0.072 * t,
           0.213 - 0.213 * t, 0.715 + 0.285 * t, 0.072 - 0.072 * t,
           0.213 - 0.213 * t, 0.715 - 0.715 * t, 0.072 + 0.928 * t)
    return tuple(sum(sat[r * 3 + k] * hue[k * 3 + col] for k in range(3))
                 for r in range(3) for col in range(3))


def _apply(m, rgb):
    if m is None:
        return rgb
    r, g, b = rgb[0], rgb[1], rgb[2]
    return tuple(max(0.0, min(255.0, m[i * 3] * r + m[i * 3 + 1] * g + m[i * 3 + 2] * b)) for i in range(3))


def _qcolor(rgb, alpha: float) -> QColor:
    c = QColor()
    c.setRgbF(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, max(0.0, min(1.0, alpha)))
    return c


def _keyframes(frames, phase: float, eased: bool) -> float:
    """Value of CSS keyframes (percent, value) at phase 0..1; `eased` applies
    ease-in-out within each interval (animation-timing-function)."""
    p = (phase % 1.0) * 100.0
    for (p0, v0), (p1, v1) in zip(frames, frames[1:]):
        if p <= p1:
            u = 0.0 if p1 == p0 else (p - p0) / (p1 - p0)
            if eased:
                u = fx.EASE_IN_OUT(u)
            return v0 + (v1 - v0) * u
    return frames[-1][1]


def _hue_swing(t: float, period: float, span: float) -> float:
    """beam-hue-shift: -span at 0 %, +span at 50 %, -span at 100 %, each half
    ease-in-out."""
    phase = (t / period) % 1.0
    if phase < 0.5:
        return -span + 2 * span * fx.EASE_IN_OUT(phase * 2)
    return span - 2 * span * fx.EASE_IN_OUT((phase - 0.5) * 2)


def _conic(cx: float, cy: float, from_deg: float, stops, rgb, scale: float = 1.0) -> QConicalGradient:
    """CSS conic-gradient(from A, rgba(rgb, a) p%...) as a QConicalGradient:
    start angle 90 - A, CSS stop p at Qt stop 1 - p."""
    g = QConicalGradient(cx, cy, 90.0 - from_deg)
    for pct, alpha in stops:
        g.setColorAt(1.0 - pct / 100.0, _qcolor(rgb, alpha * scale))
    return g


def _blob(p: QPainter, cx: float, cy: float, rx: float, ry: float, stops) -> None:
    """radial-gradient(ellipse rx ry at cx cy, ...): stops are (pos, QColor)."""
    if rx <= 0.05 or ry <= 0.05:
        return
    g = QRadialGradient(0.0, 0.0, 1.0)
    for pos, colour in stops:
        g.setColorAt(pos, colour)
    p.save()
    p.translate(cx, cy)
    p.scale(rx, ry)
    p.fillRect(QRectF(-1.0, -1.0, 2.0, 2.0), g)
    p.restore()


def _plain_blob(p, cx, cy, rx, ry, rgb, alpha):
    c = _qcolor(rgb, alpha)
    _blob(p, cx, cy, rx, ry, ((0.0, c), (1.0, _qcolor(rgb, 0.0))))


def _blurred(rx: float, ry: float, sigma: float):
    """A CSS radial blob (colour -> transparent, spread ~0.35 r) convolved with
    a Gaussian of `sigma`: the widened radii and the peak scale that keeps its
    integral. The analytic stand-in for filter: blur()."""
    k = 0.35
    sx = math.hypot(k * rx, sigma)
    sy = math.hypot(k * ry, sigma)
    rx2, ry2 = sx / k, sy / k
    return rx2, ry2, (rx / rx2) * (ry / ry2)


def _rounded(rect: QRectF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    return path


def _soft_edge(p: QPainter, path: QPainterPath, rgb, alpha: float, blur: float) -> None:
    """box-shadow: inset 0 0 <blur> 1px colour -- stacked strokes of the edge
    (half of each pen falls inside), a stepped Gaussian falloff."""
    p.save()
    p.setBrush(Qt.NoBrush)
    for frac in (0.2, 0.5, 0.95, 1.5, 2.2):
        pen = QPen(_qcolor(rgb, alpha * 0.16), 2.0 + frac * blur)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)
    p.restore()


class _Follow(QObject):
    """Keeps the overlay on top of and the size of its target."""

    def __init__(self, overlay):
        super().__init__(overlay)
        self._overlay = overlay

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.Resize, QEvent.Show, QEvent.ChildAdded):
            overlay = self._overlay
            overlay.setGeometry(obj.rect())
            if kind != QEvent.Resize:
                overlay.raise_()
        return False


# ---------------------------------------------------------------- the widget

class BorderBeam(FxWidget):
    """Overlay beam on `target`.

    Args:
        target: the widget whose border glows (the overlay becomes its child).
        size: one of SIZES.
        variant: one of VARIANTS.
        radius: the target's corner radius in px (None: 32 for 'sm', 16 else).
        strength: 0..1 multiplier on every layer's opacity.
        duration: seconds per revolution / pass (None: 1.96 rotate, 3.1 line).
    """

    def __init__(self, target, size: str = "md", variant: str = "colorful",
                 radius: float | None = None, strength: float = 1.0,
                 duration: float | None = None):
        super().__init__(target)
        self._size = size if size in SIZES else "md"
        self._variant = variant if variant in VARIANTS else "colorful"
        self._radius = float(radius) if radius is not None else _DEFAULT_RADIUS[self._size]
        self._strength = max(0.0, min(1.0, float(strength)))
        self._duration = float(duration) if duration else (
            _DURATION_LINE if self._size == "line" else _DURATION_ROTATE)
        # fade state: 'off' | 'in' | 'on' | 'out'
        self._target_on = False
        self._phase = "off"
        self._stamp = 0.0
        self._origin = 0.0          # clock time the spin / travel started at
        self._fade = 0.0
        self._cache = {}
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setGeometry(target.rect())
        self._follow = _Follow(self)
        target.installEventFilter(self._follow)
        self.raise_()

    # -- public
    def set_active(self, active: bool) -> None:
        """Fade the beam in (and animate) or out (and stop)."""
        active = bool(active)
        self._target_on = active
        if not fx.animations_enabled():
            # No motion allowed: settle at once on the still frame.
            self._phase = "on" if active else "off"
            self._fade = 1.0 if active else 0.0
            if active:
                self.start()
            else:
                FxWidget.stop(self)
            return
        if self._phase in ("in", "out"):
            return                              # applied when the fade ends
        if active and self._phase == "off":
            # The CSS animations start with data-active: spin from 0 deg,
            # the line's travel from its first keyframe.
            self._phase, self._stamp = "in", fx.now()
            self._origin = self._stamp
            self.start()
        elif not active and self._phase == "on":
            self._phase, self._stamp = "out", fx.now()
            if not self.is_running():
                self.start()
        self.update()

    def is_active(self) -> bool:
        """The requested state (True from set_active(True) until
        set_active(False), fades included)."""
        return self._target_on

    def fade(self) -> float:
        """The current fade value 0..1 (0 = invisible)."""
        if not fx.animations_enabled():
            return 1.0 if self._target_on else 0.0
        return self._fade

    def set_radius(self, radius: float) -> None:
        self._radius = max(0.0, float(radius))
        self._cache.clear()
        self.update()

    def set_variant(self, variant: str) -> None:
        if variant in VARIANTS:
            self._variant = variant
            self.update()

    # -- geometry
    def _sync_geometry(self) -> None:
        """Match the target's rect. The event filter covers a shown target;
        a hidden one defers its resize event until shown, so geometry() and
        painting check too."""
        parent = self.parentWidget()
        if parent is not None:
            rect = parent.rect()
            if FxWidget.geometry(self) != rect:
                self.setGeometry(rect)

    def geometry(self):
        self._sync_geometry()
        return FxWidget.geometry(self)

    # -- fade machinery
    def _fade_value(self, phase, stamp, t) -> float:
        if phase == "on":
            return 1.0
        if phase == "off":
            return 0.0
        if phase == "in":
            return fx.EASE(fx.clamp01((t - stamp) / FADE_IN_S))
        return 1.0 - fx.EASE(fx.clamp01((t - stamp) / FADE_OUT_S))

    def advance(self, t: float, dt: float) -> None:
        if self._phase in ("in", "out") and t < self._stamp - 1e-3:
            # A driver on another time base (a gallery, a test clock): the
            # fade (and the motion) start at its first tick instead.
            self._origin += t - self._stamp
            self._stamp = t
        while self._phase in ("in", "out"):
            length = FADE_IN_S if self._phase == "in" else FADE_OUT_S
            end = self._stamp + length
            if t < end:
                break
            if self._phase == "in":
                self._phase = "out" if not self._target_on else "on"
            else:
                self._phase = "in" if self._target_on else "off"
                if self._phase == "in":
                    self._origin = end
            self._stamp = end
        self._fade = self._fade_value(self._phase, self._stamp, t)
        if self._phase == "off":
            self._fade = 0.0
            FxWidget.stop(self)

    def still_time(self) -> float:
        # The still frame: the beam over the top-right corner.
        return self._duration * 0.62

    def _fade_at(self, t: float) -> float:
        if not self.animating():
            if not fx.animations_enabled():
                return 1.0 if self._target_on else 0.0
            return self._fade
        if self._phase in ("in", "out") and t >= self._stamp - 1e-3:
            return self._fade_value(self._phase, self._stamp, t)
        return self._fade

    # -- painting
    def paint_frame(self, painter, t: float) -> None:
        fade = self._fade_at(t) * self._strength
        if self.animating():
            t -= self._origin               # motion time since activation
        self._sync_geometry()
        w, h = self.width(), self.height()
        if fade <= 0.001 or w < 4 or h < 4:
            return
        painter.save()
        try:
            if self._size == "line":
                self._paint_line(painter, t, fade, w, h)
            else:
                self._paint_rotate(painter, t, fade, w, h)
        finally:
            painter.restore()

    def _dpr(self, painter) -> float:
        try:
            return max(1.0, float(painter.device().devicePixelRatioF()))
        except Exception:
            return 1.0

    def _layer(self, key, w, h, dpr) -> QImage:
        """A reusable transparent layer image at the painter's resolution."""
        img = self._cache.get(("layer", key, w, h, dpr))
        if img is None:
            img = QImage(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))),
                         QImage.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            self._cache[("layer", key, w, h, dpr)] = img
        img.fill(0)
        return img

    def _radius_for(self, w, h) -> float:
        return max(0.0, min(self._radius, w / 2.0, h / 2.0))

    def _ring_mask(self, w, h, dpr) -> QImage:
        """The 1 px border ring (border-box minus content-box), antialiased."""
        key = ("ring", w, h, dpr, self._radius)
        img = self._cache.get(key)
        if img is None:
            img = QImage(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))),
                         QImage.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(0)
            r = self._radius_for(w, h)
            path = _rounded(QRectF(0, 0, w, h), r)
            path.addRoundedRect(QRectF(1, 1, w - 2, h - 2), max(0.0, r - 1), max(0.0, r - 1))
            path.setFillRule(Qt.OddEvenFill)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.fillPath(path, QColor(255, 255, 255))
            p.end()
            self._cache[key] = img
        return img

    def _inner_mask(self, w, h, dpr, edge: bool) -> QImage:
        """The rounded clip (clip-path: inset(0 round r)), times -- with `edge` --
        the 28 px edge fade: linear-gradient(white, transparent 28px, ...,
        white) added to its horizontal twin."""
        key = ("inner", w, h, dpr, self._radius, edge)
        img = self._cache.get(key)
        if img is None:
            img = QImage(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))),
                         QImage.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.fillPath(_rounded(QRectF(0, 0, w, h), self._radius_for(w, h)), QColor(255, 255, 255))
            if edge:
                # A composition mode only touches the pixels a shape covers,
                # so the edge fade goes into its own image, applied whole.
                p.end()
                fade = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
                fade.setDevicePixelRatio(dpr)
                fade.fill(0)
                p = QPainter(fade)
                e = _INNER_EDGE_PX
                white, clear = QColor(255, 255, 255, 255), QColor(255, 255, 255, 0)
                for vertical in (True, False):
                    length = h if vertical else w
                    g = QLinearGradient(0, 0, 0, length) if vertical else QLinearGradient(0, 0, length, 0)
                    f = min(0.5, e / max(1.0, length))
                    g.setColorAt(0.0, white)
                    g.setColorAt(f, clear)
                    g.setColorAt(1.0 - f, clear)
                    g.setColorAt(1.0, white)
                    p.setCompositionMode(QPainter.CompositionMode_SourceOver if vertical
                                         else QPainter.CompositionMode_Plus)
                    p.fillRect(QRectF(0, 0, w, h), g)
                p.end()
                p = QPainter(img)
                p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                p.drawImage(QPointF(0, 0), fade)
            p.end()
            self._cache[key] = img
        return img

    def _colour_state(self, t, theme, hue_span, period):
        """The filter matrix for this moment (None for mono: staticColors)."""
        if self._variant == "mono":
            return None
        sat = _THEME[self._size][theme][4]
        return _filter_matrix(_hue_swing(t, period, hue_span), _BRIGHTNESS, sat)

    def _paint_rotate(self, painter, t, fade, w, h):
        size, theme, variant = self._size, self._theme, self._variant
        stroke_op, inner_op, bloom_op, shadow, _sat = _THEME[size][theme]
        mono = _MONO_OPACITY if variant == "mono" else 1.0
        stroke_op = min(1.0, stroke_op * mono) * fade
        inner_op = min(1.0, inner_op * mono) * fade
        bloom_op = min(1.0, bloom_op * mono) * fade
        dpr = self._dpr(painter)
        r = self._radius_for(w, h)
        cx, cy = w / 2.0, h / 2.0
        angle = (360.0 * t / self._duration) % 360.0
        m = self._colour_state(t, theme, _HUE_RANGE, _HUE_PERIOD)
        full = QRectF(0, 0, w, h)
        edge_rgb = (255, 255, 255) if theme == "dark" else (0, 0, 0)

        if size == "sm":
            lo, hi = _SM_SCALE_RANGE
            sx = max(lo, min(hi, w / _SM_REF[0]))
            sy = max(lo, min(hi, h / _SM_REF[1]))
            geom = tuple((x, y, rx * sx, ry * sy) for x, y, rx, ry in _SM_GEOM)
            colours = _SM_COLOURS[variant]
            inner_alpha = _SM_INNER_ALPHA_MONO if variant == "mono" else _SM_INNER_ALPHA
            inner_geom = geom
            inner_mask_stops = _SMALL_MASK
        else:
            geom, colours = _MD_GEOM, _MD_COLOURS[variant]
            a = _INNER_ALPHA_MONO if variant == "mono" else _INNER_ALPHA
            inner_alpha = (a,) * len(geom)
            inner_geom = tuple((x, y, fx.js_round(rx * _INNER_SIZE_SCALE), fx.js_round(ry * _INNER_SIZE_SCALE))
                               for x, y, rx, ry in geom)
            inner_mask_stops = _BEAM_MASK
        tinted = [_apply(m, c) for c in colours]

        # ::before -- the inner glow: colour blobs + inset shadow, masked by
        # the travelling conic and (md) the 28 px edge fade, clipped round.
        inner = self._layer("inner", w, h, dpr)
        p = QPainter(inner)
        p.setRenderHint(QPainter.Antialiasing)
        for (x, y, rx, ry), rgb, al in reversed(list(zip(inner_geom, tinted, inner_alpha))):
            _plain_blob(p, x * w, y * h, rx, ry, rgb, al)
        _soft_edge(p, _rounded(full, r), _apply(m, shadow[:3]), shadow[3], _INNER_SHADOW_BLUR[size])
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.fillRect(full, _conic(cx, cy, angle, inner_mask_stops, (255, 255, 255)))
        p.drawImage(QPointF(0, 0), self._inner_mask(w, h, dpr, edge=(size == "md")))
        p.end()

        # ::after -- the stroke: white conic over the blobs in the 1 px ring,
        # under the beam mask.
        ring = self._layer("ring", w, h, dpr)
        p = QPainter(ring)
        p.setRenderHint(QPainter.Antialiasing)
        for (x, y, rx, ry), rgb in reversed(list(zip(geom, tinted))):
            _plain_blob(p, x * w, y * h, rx, ry, rgb, 1.0)
        p.fillRect(full, _conic(cx, cy, angle, _WHITE_STOPS[theme], edge_rgb))
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.fillRect(full, _conic(cx, cy, angle, _BEAM_MASK, (255, 255, 255)))
        p.drawImage(QPointF(0, 0), self._ring_mask(w, h, dpr))
        p.end()

        painter.setOpacity(inner_op)
        painter.drawImage(QPointF(0, 0), inner)
        painter.setOpacity(stroke_op)
        painter.drawImage(QPointF(0, 0), ring)

        # bloom -- the bright conic in the ring, blur(8px): widening strokes
        # of the rim whose summed profile is the blurred line's (clipped round).
        bloom = self._layer("bloom", w, h, dpr)
        p = QPainter(bloom)
        p.fillRect(full, _conic(cx, cy, angle, self._bloom_stops(theme, w, h), edge_rgb))
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(QPointF(0, 0), self._ring_mask(w, h, dpr))
        p.end()
        painter.setOpacity(bloom_op)
        painter.drawImage(QPointF(0, 0), bloom)

    def _bloom_stops(self, theme, w, h):
        """bloomGradient after blur(8px). CSS filters before it masks, so the
        bloom is the blurred conic seen through the 1 px ring: at the rim the
        blur is an angular one, sigma = 8 px over the mean rim radius."""
        key = ("bloomstops", theme, w, h)
        stops = self._cache.get(key)
        if stops is None:
            rim = max(8.0, (w + h) / 4.0)
            sigma = _BLOOM_BLUR_PX / (2 * math.pi * rim) * 100.0      # percent of a turn
            src = _BLOOM_STOPS[theme]

            def at(pct):
                pct %= 100.0
                for (p0, a0), (p1, a1) in zip(src, src[1:]):
                    if pct <= p1:
                        return a0 if p1 == p0 else a0 + (a1 - a0) * (pct - p0) / (p1 - p0)
                return 0.0

            step = 0.25
            kernel = [math.exp(-0.5 * (k * step / sigma) ** 2) for k in range(-int(3 * sigma / step), int(3 * sigma / step) + 1)]
            norm = sum(kernel)
            half = len(kernel) // 2
            stops = [(0.0, 0.0)]
            pct = 50.0
            while pct <= 90.0:
                value = sum(kv * at(pct + (i - half) * step) for i, kv in enumerate(kernel)) / norm
                stops.append((pct, value))
                pct += 1.0
            stops.append((100.0, 0.0))
            self._cache[key] = stops
        return stops

    # -- the line type
    def _line_state(self, t):
        d = self._duration
        phase = (t / d) % 1.0
        periods = [round(d * s, 1) or d for s in (_BREATHE_SCALE, _SPIKE_SCALE, _SPIKE2_SCALE)]
        return (_keyframes(_TRAVEL_X, phase, False), _keyframes(_TRAVEL_W, phase, False),
                _keyframes(_EDGE_FADE, phase, False),
                _keyframes(_BREATHE, t / periods[0], True),
                _keyframes(_SPIKE, t / periods[1], True),
                _keyframes(_SPIKE2, t / periods[2], True))

    def _paint_line(self, painter, t, fade, w, h):
        theme, variant = self._theme, self._variant
        stroke_op, inner_op, bloom_op, shadow, sat = _THEME["line"][theme]
        bx, bw, edge, bh, spike, spike2 = self._line_state(t)
        fade *= edge
        if fade <= 0.001:
            return
        stroke_op, inner_op, bloom_op = (min(1.0, v) * fade for v in (stroke_op, inner_op, bloom_op))
        dpr = self._dpr(painter)
        r = self._radius_for(w, h)
        full = QRectF(0, 0, w, h)
        x = bx * w
        mono = variant == "mono"
        m = None if mono else _filter_matrix(_hue_swing(t, _HUE_PERIOD, _LINE_HUE_CAP), _BRIGHTNESS, sat)
        mb = None if mono else _filter_matrix(
            _hue_swing(t, _LINE_BLOOM_HUE_PERIOD, _LINE_HUE_CAP + _LINE_BLOOM_HUE_BONUS), _BRIGHTNESS, sat)

        def ellipse_mask(p, spec):
            ew, eh, stops = spec
            _blob(p, x, h, ew * bw, eh * bh, [(pos, QColor(255, 255, 255, int(255 * a))) for pos, a in stops])

        # ::before -- inner blobs travelling with the beam
        inner = self._layer("inner", w, h, dpr)
        p = QPainter(inner)
        p.setRenderHint(QPainter.Antialiasing)
        inner_colours = _LINE_COLOURS[variant]["dark"]
        for (sw, sh, ox, oy), rgb, al in reversed(list(zip(_LINE_INNER_GEOM, inner_colours, _LINE_INNER_ALPHA))):
            _plain_blob(p, x + ox, h - abs(oy), sw * bw, sh * bh, _apply(m, rgb), al)
        _soft_edge(p, _rounded(full, r), _apply(m, shadow[:3]), shadow[3], _INNER_SHADOW_BLUR["line"])
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask = self._layer("mask", w, h, dpr)
        mp = QPainter(mask)
        mp.setRenderHint(QPainter.Antialiasing)
        ellipse_mask(mp, _LINE_BEAM_MASK)
        mp.end()
        p.drawImage(QPointF(0, 0), mask)
        p.drawImage(QPointF(0, 0), self._inner_mask(w, h, dpr, edge=True))
        p.end()

        # ::after -- the stroke: highlight over the colour blobs, in the ring
        ring = self._layer("ring", w, h, dpr)
        p = QPainter(ring)
        p.setRenderHint(QPainter.Antialiasing)
        for (sw, sh, ox, oy), rgb in reversed(list(zip(_LINE_GEOM[theme], _LINE_COLOURS[variant][theme]))):
            _plain_blob(p, x + ox, h + oy, sw * bw, sh * bh, _apply(m, rgb), 1.0)
        ww, wh, wy, wrgb, wstops = _LINE_WHITE[theme]
        _blob(p, x, h + wy, ww * bw, wh * bh, [(pos, _qcolor(wrgb, a)) for pos, a in wstops])
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(QPointF(0, 0), mask)
        p.drawImage(QPointF(0, 0), self._ring_mask(w, h, dpr))
        p.end()

        # bloom -- spikes, the glow dot and the ambient wash, blurred
        # (analytically), masked by the tall bloom ellipse.
        bloom = self._layer("bloom", w, h, dpr)
        p = QPainter(bloom)
        p.setRenderHint(QPainter.Antialiasing)
        sigma = _MONO_LINE_BLOOM_BLUR_PX if mono else _BLOOM_BLUR_PX
        for gx, gy, rx, ry, stops in reversed(self._line_bloom(theme, variant, w, h, x, bw, bh, spike, spike2)):
            rx2, ry2, k = _blurred(rx, ry, sigma)
            _blob(p, gx, gy, rx2, ry2, [(pos, _qcolor(_apply(mb, rgb), a * k)) for pos, rgb, a in stops])
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask.fill(0)
        mp = QPainter(mask)
        mp.setRenderHint(QPainter.Antialiasing)
        ellipse_mask(mp, _LINE_BLOOM_MASK)
        mp.end()
        p.drawImage(QPointF(0, 0), mask)
        p.drawImage(QPointF(0, 0), self._inner_mask(w, h, dpr, edge=False))
        p.end()

        painter.setOpacity(inner_op)
        painter.drawImage(QPointF(0, 0), inner)
        painter.setOpacity(stroke_op)
        painter.drawImage(QPointF(0, 0), ring)
        painter.setOpacity(bloom_op)
        painter.drawImage(QPointF(0, 0), bloom)

    @staticmethod
    def _line_bloom(theme, variant, w, h, x, bw, bh, spike, spike2):
        """getLineBloomGradients: [(x, y, rx, ry, [(pos, rgb, alpha)])],
        top layer first."""
        mono = variant == "mono"
        dark = theme == "dark"
        prim, sec = _SPIKES[variant][theme]
        spikes = _LINE_BLOOM[variant][theme]

        def att(c, f):          # attenuateSpike: rgba alpha x f, rgb -> alpha f
            return c[:3], (c[3] * f if c[3] < 1 else f)

        if mono:
            spikes = [(att(c1, 0.14), att(c2, 0.14 * 0.7)) for c1, c2 in spikes]
            sc1, sc2 = att(prim, 0.14), att(sec, 0.12)
            sc1_mid = att(prim, 0.09) if dark else att(prim, 0.11)
            sc2_mid = (sec[:3], 0.06) if dark else att(sec, 0.09)
            thin_w = (12, 14, 12, 10 if dark else 12)
            thin_h = (42, 38, 40, 32)
            dot, amb = (0.5, 0.45, 0.25), (0.15, 0.06, 0.015)
        else:
            spikes = [((c1[:3], c1[3]), (c2[:3], c2[3])) for c1, c2 in spikes]
            sc1, sc2 = (prim[:3], prim[3]), (sec[:3], sec[3])
            sc1_mid = (prim[:3], prim[3]) if dark else (prim[:3], 0.85)
            sc2_mid = (sec[:3], 0.49) if dark else (sec[:3], 0.7)
            thin_w = (0.8, 2, 1.2, 0.6 if dark else 1)
            thin_h = (92, 72, 85, 60)
            dot, amb = (1.0, 0.9, 0.5), (0.3, 0.12, 0.03)

        def stops(c0, c1, p1, p2):
            return [(0.0, c0[0], c0[1]), (p1, c1[0], c1[1]), (p2, c1[0], 0.0), (1.0, c1[0], 0.0)]

        inv_spike, inv_spike2 = 2 - spike, 2 - spike2
        out = [
            (0.08 * w, h - 2, thin_w[0] * spike, thin_h[0] * bh, stops(sc1, sc1_mid, .30, .88)),
            (0.22 * w, h - 4, 10 * spike2, 35 * bh, stops(sc2, sc2_mid, .50, .95)),
            (0.36 * w, h - 3, thin_w[1] * inv_spike, thin_h[1] * bh, stops(spikes[0][0], spikes[0][1], .40, .90)),
            (0.50 * w, h - 2, 14 * spike2, 28 * bh, stops(spikes[1][0], spikes[1][1], .55, .96)),
            (0.64 * w, h - 4, thin_w[2] * inv_spike2, thin_h[2] * bh, stops(spikes[2][0], spikes[2][1], .35, .89)),
            (0.78 * w, h - 2, 7 * spike, 45 * bh, stops(spikes[3][0], spikes[3][1], .48, .94)),
            (0.92 * w, h - 3, thin_w[3] * inv_spike, thin_h[3] * bh, stops(spikes[4][0], spikes[4][1], .42, .91)),
        ]
        white, black = (255, 255, 255), (0, 0, 0)
        if dark:
            out.append((x, h + 1, 21 * spike, 15 * spike2,
                        [(0.0, white, dot[0]), (0.2, white, dot[1]), (0.5, white, dot[2]), (1.0, white, 0.0)]))
            out.append((x, h, 42 * bw, 40 * bh,
                        [(0.0, white, amb[0]), (0.25, white, amb[1]), (0.55, white, amb[2]), (0.8, white, 0.0),
                         (1.0, white, 0.0)]))
        else:
            out.append((x, h, 50 * bw, 32 * bh,
                        [(0.0, black, 0.5), (0.3, black, 0.18), (0.6, black, 0.03), (0.85, black, 0.0),
                         (1.0, black, 0.0)]))
        return out
