"""ui/python/fx/mosaic.py -- a pixel-mosaic loader that dissolves into an image.

Port of libdev packages/img-fx, 'sweep-gradient' preset (dark / light
palettes), in QPainter with no numpy: a grid of square cells (constant cell
size, grid = max(2, floor(22.28 * W / 320)) columns, same for rows) each
filled with the sweep-gradient field's colour for that cell (two diagonal
bands crossing every ~2.4 s, per-cell flicker re-rolled ~4.2 times a second,
5-colour palette with Gaussian weights), a thin gap between cells, the
contrast gate against the background and the 20-24 px edge fade. When an
image arrives, the reveal runs for REVEAL_S seconds with easeOutCubic: a
cell-stepped diagonal front sweeps the sharp image in, cells near the front
show the image's own blocky average colour (per-cell random drop times), and
the loader fades out underneath. Rendering is throttled to 15 fps, as the
web engine caps at 10.

MosaicView is a widget showing: the loader (while loading()), the reveal
(after set_image during a load), or the image (fitted, aspect kept, centred,
as a QLabel with a scaled pixmap would) -- or a message line.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from ui.python.fx import FxWidget, ease_out_cubic, smoothstep

REVEAL_S = 2.65

_BASE_COUNT = 6.0 + 0.22 * 74.0       # pixelConfig.cellSize 0.22 -> 22.28 cells per 320 px
_REF_DIM = 320.0
_SPEED = 2.65                         # preset speed (u_time multiplier)
_REST = 0.42                          # field level between the sweeps

# presets/sweep-gradient.ts, per theme.
_MODES = {
    "dark": {
        "palette": ("#0f0f0f", "#0f0f0f", "#282828", "#3a3a3a", "#525252"),
        "bg": "#0f0f0f", "intensity": 1.0, "highlight": 0.32, "vignette": 0.26,
        "fill": 0.44, "dot": 0.68, "gap": 0.14, "hl_scale": 0.8, "edge_fade": 24.0,
        "flicker": 0.5,
    },
    "light": {
        "palette": ("#f5f5f5", "#f5f5f5", "#ededed", "#eaeaea", "#d2d2d2"),
        "bg": "#f5f5f5", "intensity": 0.85, "highlight": 0.92, "vignette": 0.0,
        "fill": 0.18, "dot": 0.68, "gap": 0.14, "hl_scale": 0.8, "edge_fade": 20.0,
        "flicker": 0.5,
    },
}


def _rgb(hex_colour: str):
    c = QColor(hex_colour)
    return (c.redF(), c.greenF(), c.blueF())


def _lum(c) -> float:
    return c[0] * 0.299 + c[1] * 0.587 + c[2] * 0.114


def _palette(v: float, colours):
    """The shader's palette(): 5 colours, Gaussian weights at 0, .25 ... 1."""
    v = 0.0 if v < 0.0 else 1.0 if v > 1.0 else v
    v = v * v * (3.0 - 2.0 * v)
    r = g = b = total = 0.0
    for i, c in enumerate(colours):
        d = v - i * 0.25
        w = math.exp(-64.0 * d * d)
        r += c[0] * w
        g += c[1] * w
        b += c[2] * w
        total += w
    total += 0.0001
    return (r / total, g / total, b / total)


def _hash(seed: float, step: float) -> float:
    v = math.sin(seed + step * 17.23) * 43758.5453
    return v - math.floor(v)


def _fit_rect(image_w: int, image_h: int, w: float, h: float) -> QRectF:
    """Aspect-kept, centred, never upscaled past the widget (QLabel-like)."""
    if image_w <= 0 or image_h <= 0 or w <= 0 or h <= 0:
        return QRectF()
    k = min(w / image_w, h / image_h)
    fw, fh = image_w * k, image_h * k
    return QRectF((w - fw) / 2, (h - fh) / 2, fw, fh)


class MosaicView(FxWidget):
    """Args: radius -- corner radius of the tile in px (clip)."""

    fps = 15.0

    def __init__(self, parent=None, radius: float = 8.0):
        super().__init__(parent)
        self._radius = max(0.0, float(radius))
        self._mode = "empty"            # empty | loading | reveal | image | message
        self._image = None
        self._message = ""
        self._reveal_start = 0.0
        self._reveal_synced = True
        self._drops = []                # per-cell drop times of this reveal
        self._cache_key = None          # (image id, w, h, cols, rows)
        self._fitted = None             # the image scaled into the widget
        self._fit = QRectF()
        self._blocks = None             # the image averaged down to the cell grid
        self._colour_cache = {}

    # -- public
    def set_loading(self) -> None:
        """Show the animated loader (starts the animation)."""
        self._mode = "loading"
        self._message = ""
        self.start()

    def set_image(self, image) -> None:
        """A QImage (or None). During a load: reveal it; otherwise show it at
        once. The animation stops when the reveal ends."""
        if image is not None and image.isNull():
            image = None
        self._image = image
        self._message = ""
        self._cache_key = None
        if image is None:
            self._mode = "empty"
            self.stop()
            return
        if self._mode == "loading" and self.animating():
            self._mode = "reveal"
            self._reveal_start = _now()
            self._reveal_synced = False
            self._drops = []
            self.update()
        else:
            self._mode = "image"
            self.stop()

    def set_message(self, text: str) -> None:
        """Show a line of text (centred, muted) instead of an image; stops."""
        self._mode = "message"
        self._message = str(text or "")
        self._image = None
        self._cache_key = None
        self.stop()

    def loading(self) -> bool:
        return self._mode == "loading"

    def revealing(self) -> bool:
        return self._mode == "reveal"

    def image(self):
        """The current QImage, or None."""
        return self._image

    def message(self) -> str:
        return self._message

    # -- animation
    def advance(self, t: float, dt: float) -> None:
        if self._mode != "reveal":
            return
        if not self._reveal_synced:
            # The stamp is fx.now(); a caller driving its own timeline (a
            # gallery at t=1000, a widget that was hidden) is re-based on
            # the first tick so the reveal plays from its start.
            self._reveal_synced = True
            if abs(t - self._reveal_start) > 1.0:
                self._reveal_start = t
        if t - self._reveal_start >= REVEAL_S:
            self._mode = "image"
            self.stop()

    # -- geometry
    def _grid(self):
        w, h = max(1, self.width()), max(1, self.height())
        cols = max(2, int(math.floor(_BASE_COUNT * w / _REF_DIM)))
        rows = max(2, int(math.floor(_BASE_COUNT * h / _REF_DIM)))
        return cols, rows

    def _tile_path(self) -> QPainterPath:
        path = QPainterPath()
        r = min(self._radius, self.width() / 2, self.height() / 2)
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), r, r)
        return path

    def _prepare_image(self, cols: int, rows: int) -> None:
        w, h = self.width(), self.height()
        key = (id(self._image), w, h, cols, rows)
        if key == self._cache_key:
            return
        self._cache_key = key
        image = self._image
        self._fit = _fit_rect(image.width(), image.height(), w, h)
        fw, fh = max(1, round(self._fit.width())), max(1, round(self._fit.height()))
        self._fitted = image.scaled(fw, fh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
            .convertToFormat(QImage.Format_ARGB32_Premultiplied)
        # the blocky layer: the fitted image on the tile, averaged per cell
        canvas = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
        canvas.fill(0)
        p = QPainter(canvas)
        p.drawImage(self._fit.topLeft(), self._fitted)
        p.end()
        small = canvas.scaled(cols, rows, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
            .convertToFormat(QImage.Format_ARGB32)
        self._blocks = [[QColor.fromRgba(small.pixel(c, r)) for c in range(cols)] for r in range(rows)]

    # -- painting
    def paint_frame(self, painter, t: float) -> None:
        w, h = self.width(), self.height()
        if w < 1 or h < 1:
            return
        painter.save()
        try:
            painter.setClipPath(self._tile_path())
            if self._mode == "loading":
                self._paint_loader(painter, t, 1.0)
            elif self._mode == "reveal":
                self._paint_reveal(painter, t)
            elif self._mode == "image" and self._image is not None:
                cols, rows = self._grid()
                self._prepare_image(cols, rows)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawImage(self._fit.topLeft(), self._fitted)
            elif self._mode == "message" and self._message:
                muted = QColor("#a1a1aa") if self._theme != "light" else QColor("#71717a")
                painter.setPen(muted)
                painter.drawText(QRectF(8, 0, w - 16, h), Qt.AlignCenter | Qt.TextWordWrap, self._message)
        finally:
            painter.restore()

    def _paint_loader(self, painter, t: float, opacity: float) -> None:
        """The sweep-gradient field, one fillRect pair per cell."""
        if opacity <= 0.003:
            return
        mode = _MODES["light" if self._theme == "light" else "dark"]
        colours = self._colour_cache.get(self._theme)
        if colours is None:
            colours = ([_rgb(c) for c in mode["palette"]], _rgb(mode["bg"]))
            self._colour_cache[self._theme] = colours
        palette, bg = colours
        bg_lum = _lum(bg)
        w, h = self.width(), self.height()
        cols, rows = self._grid()
        cw, ch = w / cols, h / rows

        painter.save()
        painter.setOpacity(painter.opacity() * opacity)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(QRectF(0, 0, w, h), QColor.fromRgbF(*bg))

        st = t * _SPEED
        band_w = 0.9                                   # 0.9 / scale
        cyc = st * 0.08
        f_a = cyc - math.floor(cyc)
        f_b = (cyc + 0.5) - math.floor(cyc + 0.5)
        p_a = -band_w + (1 + 2 * band_w) * (f_a * f_a * (3 - 2 * f_a))
        p_b = -band_w + (1 + 2 * band_w) * (f_b * f_b * (3 - 2 * f_b))
        clk = st * 1.6
        step0 = math.floor(clk) % 1024
        step1 = (step0 + 1) % 1024
        fz = clk - math.floor(clk)
        fz = fz * fz * (3 - 2 * fz)
        flicker = mode["flicker"] * 0.9
        intensity = mode["intensity"]
        highlight = mode["highlight"]
        vignette = mode["vignette"]
        vig_range = 40.0 * (1.0 + vignette * 3.0)
        edge_fade = mode["edge_fade"]
        fill_a, dot_a = mode["fill"], mode["dot"]
        gap_base = mode["gap"] * 0.35
        hl_scale = mode["hl_scale"]
        aspect = w / h
        sin, fill = math.sin, painter.fillRect

        for r in range(rows):
            y0 = round(r * ch)
            y1 = round((r + 1) * ch)
            v_c = (r + 0.5) / rows                     # 0 top .. 1 bottom
            cy = y0 + (y1 - y0) / 2
            hl_y = sin(2.5 * (v_c - 0.5) * -1.0 - st * 1.1) * 0.5 + 0.5
            for c in range(cols):
                x0 = round(c * cw)
                x1 = round((c + 1) * cw)
                u_c = (c + 0.5) / cols
                # the two diagonal bands
                d = (u_c + v_c) * 0.5
                band = max(0.0, 1.0 - abs(d - p_a) / band_w, 1.0 - abs(d - p_b) / band_w)
                band = min(1.0, band)
                # a resting level under the bands keeps a calm field on
                # screen between sweeps (the web card goes blank there)
                v = _REST + band * intensity * (1.0 - _REST)
                # per-cell flicker, cross-faded between re-rolls
                seed = c * 127.1 + (rows - 1 - r) * 311.7
                rnd = _hash(seed, step0) * (1 - fz) + _hash(seed, step1) * fz
                v += (rnd - 0.5) * flicker * (0.3 + band * 0.7)
                base = _palette(v, palette)
                # the contrast gate, eased (sqrt) so the field stays legible
                # on a desktop panel rather than a dimmed web card
                gate = smoothstep(0.0, 0.33, abs(_lum(base) - bg_lum)) ** 0.5
                if gate <= 0.004:
                    continue
                # highlight ("sparkle"): travelling sine lobes over the grid
                px = (u_c - 0.5) * aspect
                py = 0.5 - v_c
                lw = (sin(px * 3.0 + st * 1.5) * 0.5 + 0.5) * hl_y
                lw += (sin(px * 4.1 + py * 2.3 + st * 0.6) * sin(py * 3.7 - px * 1.9 - st * 0.45)
                       * 0.5 + 0.5) * 0.3
                hlf = 0.0 if lw < 0 else 1.0 if lw > 1 else lw
                hlf *= hlf
                hl = hlf * highlight
                k = 1.0 + hl * 2.5
                add = hl * hl * 0.3
                cx = x0 + (x1 - x0) / 2
                edge_px = min(cx, w - cx, cy, h - cy)
                col_r, col_g, col_b = base[0] * k + add, base[1] * k + add, base[2] * k + add
                if vignette > 0:
                    vg = smoothstep(0.0, 1.0, (edge_px * edge_px) / (vig_range * vig_range))
                    m = 1.0 + (vg - 1.0) * vignette
                    col_r, col_g, col_b = col_r * m, col_g * m, col_b * m
                colour = QColor.fromRgbF(min(1.0, col_r), min(1.0, col_g), min(1.0, col_b))
                ef = smoothstep(0.0, edge_fade, edge_px)
                # the gap: the cell's rim shows fillOpacity, its body dotOpacity
                inner_a = (fill_a + (dot_a - fill_a) * ef) * gate
                rim_a = fill_a * gate
                boost = 1.0 + smoothstep(0.2, 0.8, hlf) * hl_scale * 1.2
                gap = gap_base / boost * (x1 - x0)
                colour.setAlphaF(rim_a)
                fill(QRectF(x0, y0, x1 - x0, y1 - y0), colour)
                # inner over rim: a = rim + x(1 - rim)  =>  x
                extra = (inner_a - rim_a) / max(1e-3, 1.0 - rim_a)
                if extra > 0.004:
                    colour.setAlphaF(min(1.0, extra))
                    fill(QRectF(x0 + gap, y0 + gap, x1 - x0 - 2 * gap, y1 - y0 - 2 * gap), colour)
        painter.restore()

    def _paint_reveal(self, painter, t: float) -> None:
        cols, rows = self._grid()
        self._prepare_image(cols, rows)
        elapsed = max(0.0, t - self._reveal_start)
        progress = min(1.0, elapsed / REVEAL_S)
        eased = ease_out_cubic(progress)
        # the loader fades out underneath
        self._paint_loader(painter, t, 1.0 - eased)
        if eased <= 0.0:
            return
        if len(self._drops) != cols * rows:
            rng = random.Random(hash((id(self._image), cols, rows)))
            self._drops = [0.07 + rng.random() * 0.86 for _ in range(cols * rows)]
        w, h = self.width(), self.height()
        cw, ch = w / cols, h / rows
        # gradientSweep mask: a diagonal front, flickering at its edge
        gs_w = 0.9
        gs_pos = -gs_w + eased * (1 + 2 * gs_w)
        clk = t * max(_SPEED, 2.0) * 1.6
        step0 = math.floor(clk) % 1024
        step1 = (step0 + 1) % 1024
        fz = clk - math.floor(clk)
        fz = fz * fz * (3 - 2 * fz)
        amp = _MODES["dark"]["flicker"] * 1.6
        fade_t = eased                               # pixDuration == REVEAL_S here
        inv_band2 = 1.0 / (2 * 0.07)
        fitted, fit = self._fitted, self._fit
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        for r in range(rows):
            y0 = round(r * ch)
            y1 = round((r + 1) * ch)
            if y1 <= fit.top() or y0 >= fit.bottom():
                continue
            ny = (r + 0.5) / rows
            for c in range(cols):
                x0 = round(c * cw)
                x1 = round((c + 1) * cw)
                if x1 <= fit.left() or x0 >= fit.right():
                    continue
                nx = (c + 0.5) / cols
                a = (gs_pos + gs_w - (nx + ny) * 0.5) / (2 * gs_w)
                if -0.5 < a < 1.5:
                    at = 0.0 if a < 0 else 1.0 if a > 1 else a
                    edge = at * (1 - at) * 4
                    if edge > 0.001:
                        i = r * cols + c
                        rnd = _hash(i * 127.1, step0) * (1 - fz) + _hash(i * 127.1, step1) * fz
                        a += (rnd - 0.5) * amp * edge
                a = 0.0 if a < 0 else 1.0 if a > 1 else a
                m = a * a * (3 - 2 * a)
                if progress >= 1.0:
                    m = 1.0
                if m <= 0.004:
                    continue
                cell = QRectF(x0, y0, x1 - x0, y1 - y0).intersected(fit)
                painter.setOpacity(m)
                painter.drawImage(cell, fitted, cell.translated(-fit.left(), -fit.top()))
                # the blocky average on top until the cell's drop time passes
                pa = 0.5 + (self._drops[r * cols + c] - fade_t) * inv_band2
                pa = 0.0 if pa < 0 else 1.0 if pa > 1 else pa
                if pa > 0.004:
                    block = QColor(self._blocks[r][c])
                    block.setAlphaF(block.alphaF() * pa)
                    painter.fillRect(cell, block)
        painter.restore()


def _now() -> float:
    from ui.python import fx
    return fx.now()
