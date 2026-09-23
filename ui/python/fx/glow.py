"""ui/python/fx/glow.py -- a coloured beam sweeping a bar while work runs.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-A. Port of libdev
packages/voice-glow's "processing" mode with no audio: the seven colour
lobes gather into one compact beam that sweeps left <-> right along the
bottom edge (1.1 s per pass, ping-pong with power-2.1 easing at the ends)
with colours flowing inside it, glow held at level 0.55. Drawn as
horizontally offset radial gradients of the seven "colorful" lobe colours
(rgb(255,70,120) rgb(60,190,255) rgb(175,70,255) rgb(60,220,130)
rgb(255,150,40) rgb(90,100,255) rgb(40,200,190)), plus a 1 px edge line
and a soft bloom above it.

A thin widget (default fixed height 6 px) placed under a header or across
the top of a card: start() while work runs, stop() when it ends (the glow
fades out over 0.4 s, then nothing is painted).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient

import ui.python.fx as fx
from ui.python.fx import FxWidget

LOBE_COLOURS = ((255, 70, 120), (60, 190, 255), (175, 70, 255), (60, 220, 130),
                (255, 150, 40), (90, 100, 255), (40, 200, 190))
PASS_S = 1.1

# voice-glow src/styles.ts voiceLobes: (x offset, width, height) px on the
# ~350 px reference host; presets.ts voiceDefaults for the processing knobs.
_LOBES = ((0, 74, 46), (-36, 54, 40), (36, 54, 40), (-72, 48, 32), (72, 48, 32),
          (-108, 42, 26), (108, 42, 26))
_REF_WIDTH = 350.0
_LOBE_SPACING = 0.85                     # voiceDefaults.lobeSpacing
_SPAN = 36.0 * len(_LOBES) * _LOBE_SPACING
_LEVEL = 0.55                            # processingLevel
_CURVE = 2.1                             # processingCurve
_TRAVEL = 1.55                           # processingTravel (x half the lobe ring)
_GATHER = 0.4                            # lobes pulled to 40 % of their spread
_MASK_WIDTH = 0.55                       # the visible range narrowed to match
_FLOW = 48.0                             # px/s the colours slide at full level
_FADE_IN_S = 0.3
_FADE_OUT_S = 0.4
# themePresets (+ the default type's brightness): stroke, inner, bloom,
# saturation, brightness, hue range, hue period, hue base, strength
_THEME = {
    "dark": (1.0, 0.47, 0.89, 1.2, 1.15, 24.0, 12.0, 0.0, 1.0),
    "light": (1.0, 0.85, 0.50, 1.6, 0.95, 40.0, 8.5, 5.0, 0.8),
}


def _filter(hue_deg, brightness, saturation):
    rad = math.radians(hue_deg)
    c, s, b = math.cos(rad), math.sin(rad), brightness
    hue = ((0.213 + c * 0.787 - s * 0.213) * b, (0.715 - c * 0.715 - s * 0.715) * b, (0.072 - c * 0.072 + s * 0.928) * b,
           (0.213 - c * 0.213 + s * 0.143) * b, (0.715 + c * 0.285 + s * 0.140) * b, (0.072 - c * 0.072 - s * 0.283) * b,
           (0.213 - c * 0.213 - s * 0.787) * b, (0.715 - c * 0.715 + s * 0.715) * b, (0.072 + c * 0.928 + s * 0.072) * b)
    t = saturation
    sat = (0.213 + 0.787 * t, 0.715 - 0.715 * t, 0.072 - 0.072 * t,
           0.213 - 0.213 * t, 0.715 + 0.285 * t, 0.072 - 0.072 * t,
           0.213 - 0.213 * t, 0.715 - 0.715 * t, 0.072 + 0.928 * t)
    return tuple(sum(sat[r * 3 + k] * hue[k * 3 + col] for k in range(3)) for r in range(3) for col in range(3))


def _tint(m, rgb, alpha):
    r, g, b = rgb
    c = QColor()
    c.setRgbF(*(max(0.0, min(255.0, m[i * 3] * r + m[i * 3 + 1] * g + m[i * 3 + 2] * b)) / 255.0 for i in range(3)),
              max(0.0, min(1.0, alpha)))
    return c


def _wrap(x, span):
    half = span / 2
    return ((x + half) % span + span) % span - half


def _envelope(x, span):
    u = x / (span / 2 + 4)
    return max(0.0, 1.0 - u * u)


class WorkingGlow(FxWidget):
    """Args: height -- the fixed height in px (the glow blooms upward
    within it)."""

    def __init__(self, parent=None, height: int = 6):
        super().__init__(parent)
        self.setFixedHeight(max(2, int(height)))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._want = False
        self._amount = 0.0          # 0..1 blend of the whole effect
        self._origin = None         # clock time the sweep started from
        self._image = None

    # -- public
    def level(self) -> float:
        """The current glow level 0..~0.55 (0 when stopped and faded)."""
        if not fx.animations_enabled():
            return _LEVEL if self._want else 0.0
        a = self._amount
        return _LEVEL * a * a * (3 - 2 * a)

    def start(self) -> None:
        self._want = True
        if not fx.animations_enabled():
            self._amount = 1.0
        super().start()

    def stop(self) -> None:
        self._want = False
        if not fx.animations_enabled() or self._amount <= 0.0 or not self.is_running():
            self._amount = 0.0
            self._origin = None
            super().stop()
        else:
            self.update()               # fades out on the clock, then stops

    # -- FxWidget
    def advance(self, t: float, dt: float) -> None:
        if self._origin is None or t < self._origin - 1e-3:
            # A fresh start begins mid-pass, at the centre heading right.
            self._origin = t - PASS_S / 2
        if self._want:
            self._amount = min(1.0, self._amount + dt / _FADE_IN_S)
        else:
            self._amount = max(0.0, self._amount - dt / _FADE_OUT_S)
            if self._amount <= 0.0:
                self._origin = None
                FxWidget.stop(self)

    def still_time(self) -> float:
        return 0.0

    def paint_frame(self, painter, t: float) -> None:
        w, h = self.width(), self.height()
        if self.animating():
            amount = self._amount
            scan = t - self._origin if self._origin is not None else PASS_S / 2
        else:
            amount = 1.0 if (self._want and not fx.animations_enabled()) else (self._amount if self._want else 0.0)
            scan, t = PASS_S / 2, 0.0          # the still frame: centred
        if amount <= 0.001 or w < 4:
            return
        blend = amount * amount * (3 - 2 * amount)
        eff = _LEVEL * blend
        glow = (0.15 + 0.85 * eff) * blend
        stroke_op, inner_op, bloom_op, sat, bright, hue_range, hue_period, hue_base, strength = _THEME[self._theme]
        hue = hue_base - hue_range + 2 * hue_range * (1 - math.cos(2 * math.pi * t / hue_period)) / 2
        m = _filter(hue, bright, sat)

        # The pass: -1 .. 1, ping-pong, eased on a power curve at the turns.
        passes = max(0.0, scan) / PASS_S
        index = math.floor(passes)
        u = passes - index
        eased = 0.5 * (2 * u) ** _CURVE if u < 0.5 else 1 - 0.5 * (2 - 2 * u) ** _CURVE
        pos = 2 * eased - 1 if index % 2 == 0 else 1 - 2 * eased
        scale = max(0.6, min(1.4, w / _REF_WIDTH))
        pass_width = 1 + 0.3 * (1 - pos * pos)
        half = max(8.0, (_SPAN / 2 + 40) * scale * _MASK_WIDTH * pass_width)
        # Ride out towards the ends but keep most of the beam on the bar.
        travel = min((_SPAN / 2) * _TRAVEL * scale, max(0.0, w / 2 - half * 0.7))
        cx = w / 2 + travel * pos * blend
        phase = (t * _FLOW * eff) % _SPAN

        lobes = []
        for i, (lx, lw, _lh) in enumerate(_LOBES):
            xr = _wrap(lx * _LOBE_SPACING + phase, _SPAN)
            env = _envelope(xr, _SPAN)
            if env <= 0.01:
                continue
            lobes.append((cx + xr * _GATHER * scale * pass_width, lw * 0.5 * scale * pass_width,
                          LOBE_COLOURS[i], env))

        dpr = 1.0
        try:
            dpr = max(1.0, float(painter.device().devicePixelRatioF()))
        except Exception:
            pass
        size = (max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))
        img = self._image
        if img is None or (img.width(), img.height()) != size:
            img = self._image = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)

        def blob(x, rx, ry, colour):
            g = QRadialGradient(0.0, 0.0, 1.0)
            g.setColorAt(0.0, colour)
            clear = QColor(colour)
            clear.setAlphaF(0.0)
            g.setColorAt(1.0, clear)
            p.save()
            p.translate(x, h)
            p.scale(rx, ry)
            p.fillRect(QRectF(-1, -1, 2, 1), g)
            p.restore()

        k = glow * strength
        # bloom: wide, faint, rising the full height
        for x, rx, rgb, env in lobes:
            blob(x, rx * 1.7, h * 2.4, _tint(m, rgb, bloom_op * 0.45 * env * k))
        # inner light: the lobes themselves
        for x, rx, rgb, env in lobes:
            blob(x, rx, h * 1.25, _tint(m, rgb, inner_op * env * k))
        # the 1 px edge line along the bottom
        p.save()
        p.setClipRect(QRectF(0, h - 1, w, 1))
        for x, rx, rgb, env in lobes:
            blob(x, rx * 1.15, h, _tint(m, rgb, stroke_op * env * k))
        p.restore()
        # the beam's visible range, narrowed around the centre
        g = QLinearGradient(cx - half, 0, cx + half, 0)
        for pos_, a in ((0.0, 0.0), (0.275, 0.5), (0.5, 1.0), (0.725, 0.5), (1.0, 0.0)):
            g.setColorAt(pos_, QColor(255, 255, 255, int(255 * a)))
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.fillRect(QRectF(0, 0, w, h), g)
        p.end()
        painter.drawImage(QPointF(0, 0), img)
