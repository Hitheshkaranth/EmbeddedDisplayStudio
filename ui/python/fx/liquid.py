"""ui/python/fx/liquid.py -- a tab bar whose selection flows like liquid.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-E. Port of libdev
packages/liquid-gooey, effect="move" on a tab bar (the Tabs demo in
sites/gooey/playground/demos/Tabs.tsx + styles.css). The web goo is an SVG
blur + alpha-threshold filter; with no numpy this port builds the goo
geometrically: the selected pill (a rounded rect, radius h/2) is a body on
a spring (k=380, c=18, semi-implicit Euler, substeps <= 1/60 s) chasing a
carrier that tweens x and width over 250 ms with cubic-bezier(.3,1.05,.4,1);
velocity stretch (st = min(.18, speed*.0006), scale (1+st, 1/(1+.65st))
along the motion); a tail droplet on its own spring (k=170, c=22) with two
mid droplets (45 % / 75 %, radii .62 / .40 of the tail) -- all unioned into
one QPainterPath with pinched "necks" joining body and droplets so it reads
as liquid. Selected label colour cross-fades over 250 ms.

LiquidTabBar is a QTabBar: a drop-in for the Studio's primary navigation
(it keeps QTabBar's API, signals, icons and stylesheet text colours). It
paints its own background track, the goo pill under the selected tab and
the tab labels/icons; the style sheet's ::tab rules are used for sizes.
Colours: pill fill = the theme's primary action colour (set_colors), label
on pill = its contrasting colour, other labels = muted foreground.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyleOptionTab, QTabBar

from . import FxClock, animations_enabled, clamp01, cubic_bezier

SPRING_K, SPRING_C = 380.0, 18.0
TAIL_K, TAIL_C = 170.0, 22.0
SLIDE_MS = 250

# Private tuning, straight from the Tabs demo / observer.ts MOVE_DEFAULTS.
_STRETCH_MAX = 0.18        # move.stretch
_TAIL = 0.46               # move.tail: droplet radius = tail x half the trailing side
_FORCE = 0.5               # move.force: how far past the trailing edge the droplet may lag
_LABEL_MS = 250
_SLIDE_EASE = cubic_bezier(0.3, 1.05, 0.4, 1.0)
_LABEL_EASE = cubic_bezier(0.22, 1.0, 0.36, 1.0)
_NECK_SPREAD = 0.85        # metaball connector: how far round each circle the neck grips
_NECK_HANDLE = 2.4         # metaball connector: handle length rate (the pinch)


def _spring(x: float, v: float, target: float, k: float, c: float, dt: float):
    """observer.ts springSteps: semi-implicit Euler, substeps <= 1/60 s."""
    if dt <= 0.0:
        return x, v
    n = max(1, math.ceil(dt * 60.0 - 1e-9))
    h = dt / n
    for _ in range(n):
        v += (k * (target - x) - c * v) * h
        x += v * h
    return x, v


def _mix(a: QColor, b: QColor, f: float) -> QColor:
    f = clamp01(f)
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * f,
        a.greenF() + (b.greenF() - a.greenF()) * f,
        a.blueF() + (b.blueF() - a.blueF()) * f,
        a.alphaF() + (b.alphaF() - a.alphaF()) * f,
    )


def _contrast(c: QColor) -> QColor:
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return QColor("#000000") if lum > 0.55 else QColor("#ffffff")


def _theme_colors(theme: str):
    """(pill, on_pill, label, track) from the shadcn tokens."""
    fallback = {
        "dark": ("#006fee", None, "#a1a1aa", "#27272a"),
        "light": ("#0f172a", None, "#64748b", "#f1f5f9"),
    }[theme]
    try:
        from .. import shadcn
    except Exception:                                   # pragma: no cover
        shadcn = None

    def token(name, i):
        if shadcn is not None:
            try:
                c = QColor(shadcn.color(name, theme))
                if c.isValid():
                    return c
            except Exception:
                pass
        return QColor(fallback[i]) if fallback[i] else None

    pill = token("primary", 0)
    on_pill = token("primaryForeground", 1) or _contrast(pill)
    return pill, on_pill, token("mutedForeground", 2), token("muted", 3)


def _signed_area(path: QPainterPath) -> float:
    poly = path.toFillPolygon()
    n = poly.size()
    s = 0.0
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        s += a.x() * b.y() - b.x() * a.y()
    return s


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addEllipse(QPointF(cx, cy), r, r)
    return p


def _inside_stadium(x, y, r, cx, cy, half_core, cap_r) -> bool:
    """Is the circle (x, y, r) inside the horizontal stadium?"""
    dx = max(0.0, abs(x - cx) - half_core)
    return math.hypot(dx, y - cy) + r <= cap_r


def _neck(c1, r1, c2, r2):
    """The liquid bridge between two circles: the classic metaball connector
    (a quad whose sides are concave cubic curves pinched toward the axis).
    None when one circle holds the other."""
    x1, y1 = c1
    x2, y2 = c2
    d = math.hypot(x2 - x1, y2 - y1)
    if r1 <= 0 or r2 <= 0 or d <= abs(r1 - r2) + 1e-6:
        return None
    if d < r1 + r2:
        u1 = math.acos(max(-1.0, min(1.0, (r1 * r1 + d * d - r2 * r2) / (2 * r1 * d))))
        u2 = math.acos(max(-1.0, min(1.0, (r2 * r2 + d * d - r1 * r1) / (2 * r2 * d))))
    else:
        u1 = u2 = 0.0
    v = _NECK_SPREAD
    a1 = math.atan2(y2 - y1, x2 - x1)
    a2 = math.acos(max(-1.0, min(1.0, (r1 - r2) / d)))
    a1a = a1 + u1 + (a2 - u1) * v
    a1b = a1 - u1 - (a2 - u1) * v
    a2a = a1 + math.pi - u2 - (math.pi - u2 - a2) * v
    a2b = a1 - math.pi + u2 + (math.pi - u2 - a2) * v

    def polar(cx, cy, ang, r):
        return QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r)

    p1a, p1b = polar(x1, y1, a1a, r1), polar(x1, y1, a1b, r1)
    p2a, p2b = polar(x2, y2, a2a, r2), polar(x2, y2, a2b, r2)
    gap = math.hypot(p1a.x() - p2a.x(), p1a.y() - p2a.y())
    handle = min(v * _NECK_HANDLE, gap / (r1 + r2)) * min(1.0, d * 2 / (r1 + r2))
    h1, h2 = r1 * handle, r2 * handle
    hp = math.pi / 2
    path = QPainterPath(p1a)
    path.cubicTo(p1a + polar(0, 0, a1a - hp, h1), p2a + polar(0, 0, a2a + hp, h2), p2a)
    path.lineTo(p2b)
    path.cubicTo(p2b + polar(0, 0, a2b - hp, h2), p1b + polar(0, 0, a1b + hp, h1), p1b)
    path.closeSubpath()
    return path


class LiquidTabBar(QTabBar):
    """A QTabBar with the liquid selection pill. Animates through the fx
    clock only while the pill moves (it sleeps when settled: centre error
    < 0.05 px, speed < 1 px/s, tail radius < 0.3 px), and jumps without
    motion when animations are switched off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "dark"
        self._custom_colors = False
        self._pill_c, self._on_pill_c, self._label_c, self._track_c = _theme_colors("dark")
        # motion state (only meaningful while not settled)
        self._settled = True
        self._subscribed = False
        self._index = -1
        self._last = None
        self._t0 = None
        self._elapsed = 0.0
        self._car_from = (0.0, 0.0)          # carrier (left, width) when the slide began
        self._car = (0.0, 0.0)               # carrier now
        self._cx = self._vx = 0.0            # body centre x on its spring
        self._tail_x = self._tail_vx = 0.0   # the tail droplet on its spring
        self._tail_r = 0.0
        self._phase = 0.0
        self._amt_from: dict[int, float] = {}
        self._label_p = 1.0
        # caches
        self._margins = None                 # (key, (l, t, r, b)) of the ::tab border box
        self._masks: dict = {}
        self.currentChanged.connect(self._on_current_changed)
        FxClock.instance().animationsChanged.connect(self._on_switch)

    # ------------------------------------------------------------ public
    def set_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        self._theme = "light" if theme == "light" else "dark"
        if not self._custom_colors:
            self._pill_c, self._on_pill_c, self._label_c, self._track_c = _theme_colors(self._theme)
        self._masks.clear()
        self._margins = None
        self.update()

    def set_colors(self, pill: QColor, on_pill: QColor, label: QColor, track: QColor) -> None:
        """The pill fill, the selected label colour, other labels, the track."""
        self._custom_colors = True
        self._pill_c, self._on_pill_c = QColor(pill), QColor(on_pill)
        self._label_c, self._track_c = QColor(label), QColor(track)
        self.update()

    def pill_rect(self) -> QRectF:
        """Where the pill body is right now (before stretch), in px."""
        target = self._target_box()
        if self._settled or target.isNull():
            return target
        _left, w = self._car
        return QRectF(self._cx - w / 2, target.top(), w, target.height())

    def goo_path(self) -> QPainterPath:
        """The whole liquid shape drawn this frame (body + tail + necks)."""
        body = self.pill_rect()
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        if body.isNull() or body.width() <= 0:
            return path
        cx, cy = body.center().x(), body.center().y()
        w, h = body.width(), body.height()
        speed = 0.0 if self._settled else abs(self._vx)
        st = min(_STRETCH_MAX, speed * 0.0006) if speed > 2 else 0.0
        W, H = w * (1 + st), h / (1 + 0.65 * st)
        # A drop that overshoots the bar's end squashes against it (and
        # bulges a little) instead of being cut off by the widget edge.
        lo, hi = 1.0, self.width() - 1.0
        left, right = max(lo, cx - W / 2), min(hi, cx + W / 2)
        if right - left < W and right - left > h * 0.5:
            H = min(max(1.0, self.height() - 2.0), H * (1 + 0.5 * (W / (right - left) - 1)))
            cx, W = (left + right) / 2, right - left
        r = min(W, H) / 2
        path.addRoundedRect(QRectF(cx - W / 2, cy - H / 2, W, H), r, r)
        if self._settled or self._tail_r < 0.3:
            return path

        lag = self._tail_x - cx
        if abs(lag) < 1e-3:
            return path
        side = 1.0 if lag > 0 else -1.0
        half_core = W / 2 - r
        R = self._tail_r
        wob = R * 0.16
        w1 = math.sin(self._phase) * wob
        w2 = math.sin(self._phase + 2.4) * -wob
        drops = [
            (cx + lag * 0.45, cy + w1, R * 0.62),
            (cx + lag * 0.75, cy + w2, R * 0.40),
            (self._tail_x, cy, R),
        ]
        prev = (cx + side * half_core, cy, r)          # the trailing end cap
        for x, y, rr in drops:
            if rr < 0.25 or _inside_stadium(x, y, rr, cx, cy, half_core, r):
                continue
            neck = _neck(prev[:2], prev[2], (x, y), rr)
            if neck is not None:
                if _signed_area(neck) < 0:
                    neck = neck.toReversed()
                path.addPath(neck)
            path.addPath(_circle(x, y, rr))
            prev = (x, y, rr)
        return path

    def settled(self) -> bool:
        """True when the pill rests under the current tab."""
        return self._settled

    # ------------------------------------------------------------ geometry
    def _box_margins(self):
        """The ::tab rule's margins (tabRect includes them; the pill covers
        the tab's border box). Measured once by painting the style's tab
        shape, only under a style sheet; plain styles use a small inset."""
        if self.count() == 0:
            return (0, 0, 0, 0)
        index = max(0, self.currentIndex())
        rect = self.tabRect(index)
        cls = self.style().metaObject().className()
        key = (cls, rect.height(), self.styleSheet())
        if self._margins is not None and self._margins[0] == key:
            return self._margins[1]
        margins = (1, 2, 1, 2)
        if cls == "QStyleSheetStyle" and rect.width() > 2 and rect.height() > 2:
            try:
                margins = self._measure_margins(index, rect)
            except Exception:
                pass
        self._margins = (key, margins)
        return margins

    def _measure_margins(self, index, rect):
        opt = QStyleOptionTab()
        self.initStyleOption(opt, index)
        opt.state &= ~(QStyle.State_Selected | QStyle.State_MouseOver | QStyle.State_HasFocus)
        opt.rect = QRect(0, 0, rect.width(), rect.height())
        image = QImage(rect.width(), rect.height(), QImage.Format_ARGB32)
        image.fill(0)
        p = QPainter(image)
        try:
            self.style().drawControl(QStyle.CE_TabBarTabShape, opt, p, self)
        finally:
            p.end()
        w, h = rect.width(), rect.height()
        my, mx = h // 2, w // 2
        xs = [x for x in range(w) if (image.pixel(x, my) >> 24) & 255]
        ys = [y for y in range(h) if (image.pixel(mx, y) >> 24) & 255]
        if not xs or not ys:
            return (1, 2, 1, 2)
        return (xs[0], ys[0], w - 1 - xs[-1], h - 1 - ys[-1])

    def _box(self, index: int) -> QRectF:
        if index < 0 or index >= self.count():
            return QRectF()
        l, t, r, b = self._box_margins()
        return QRectF(self.tabRect(index)).adjusted(l, t, -r, -b)

    def _target_box(self) -> QRectF:
        return self._box(self.currentIndex())

    # ------------------------------------------------------------ motion
    def _amount(self, index: int, current: int) -> float:
        """How selected a label looks (0 = label colour, 1 = on-pill)."""
        target = 1.0 if index == current else 0.0
        if self._label_p >= 1.0:
            return target
        start = self._amt_from.get(index, 0.0)
        return start + (target - start) * _LABEL_EASE(self._label_p)

    def _snap(self) -> None:
        self._settled = True
        self._tail_r = 0.0
        self._label_p = 1.0
        self._amt_from = {}
        if self._subscribed:
            FxClock.instance().unsubscribe(self)
            self._subscribed = False
        self.update()

    def _on_current_changed(self, index: int) -> None:
        prev, self._index = self._index, index
        if (prev < 0 or index < 0 or self._box(index).isNull() or not animations_enabled()
                or not self.isVisible()):
            self._snap()
            return
        if self._settled:
            old = self._box(prev)
            if old.isNull():
                self._snap()
                return
            self._car = (old.left(), old.width())
            self._cx, self._vx = old.center().x(), 0.0
            self._tail_x, self._tail_vx, self._tail_r = self._cx, 0.0, 0.0
            self._amt_from = {prev: 1.0}
        else:
            # Retarget mid-flight: labels continue from where they are.
            self._amt_from = {i: self._amount(i, prev) for i in range(self.count())}
        self._car_from = self._car
        self._label_p = 0.0
        self._t0 = None
        self._last = None
        self._settled = False
        FxClock.instance().subscribe(self, self._tick, 60)
        self._subscribed = True
        self.update()

    def _tick(self, t: float) -> None:
        if self._settled:
            self._snap()
            return
        if self._last is None:
            dt, self._t0 = 0.0, t
        else:
            dt = min(0.1, max(0.0, t - self._last))
        self._last = t
        self._elapsed = t - self._t0
        self._advance(dt)
        self.update()

    def _advance(self, dt: float) -> None:
        target = self._target_box()
        if target.isNull():
            self._snap()
            return
        slide = clamp01(self._elapsed * 1000.0 / SLIDE_MS)
        e = _SLIDE_EASE(slide)
        fl, fw = self._car_from
        left = fl + (target.left() - fl) * e
        width = fw + (target.width() - fw) * e
        self._car = (left, width)
        tcx = left + width / 2
        self._cx, self._vx = _spring(self._cx, self._vx, tcx, SPRING_K, SPRING_C, dt)
        # Tail droplet: a laggier spring on the body centre, the lag clamped
        # so it never leaves the trailing side's reach.
        self._tail_x, self._tail_vx = _spring(self._tail_x, self._tail_vx, self._cx, TAIL_K, TAIL_C, dt)
        speed = abs(self._vx)
        base = max(4.0, target.height()) / 2
        max_lag = width / 2 + base * (0.2 + _FORCE * 1.6)
        lag = self._tail_x - self._cx
        if abs(lag) > max_lag:
            self._tail_x = self._cx + math.copysign(max_lag, lag)
        onset = clamp01((speed - 20.0) / 120.0)
        self._tail_r += (base * _TAIL * onset - self._tail_r) * min(1.0, dt * 10.0)
        self._phase += speed * dt * 0.045
        self._label_p = clamp01(self._elapsed * 1000.0 / _LABEL_MS)
        if (slide >= 1.0 and self._label_p >= 1.0 and abs(self._cx - tcx) < 0.05
                and speed < 1.0 and self._tail_r < 0.3):
            self._snap()

    def _on_switch(self, enabled: bool) -> None:
        if not enabled and not self._settled:
            self._snap()
        self.update()

    # ------------------------------------------------------------ Qt
    def tabLayoutChange(self) -> None:
        super().tabLayoutChange()
        self._masks.clear()
        self.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        self._masks.clear()
        self._margins = None

    def _label_mask(self, index: int, rect: QRect, dpr: float) -> QImage:
        """The style's own label (text + icon, ::tab font and padding) as an
        alpha mask, so the colours are ours but the layout is the style's."""
        icon = self.tabIcon(index)
        selected = index == self.currentIndex()
        key = (index, self.tabText(index), icon.cacheKey(), rect.width(), rect.height(),
               selected, dpr, self.iconSize().width(), self.iconSize().height())
        mask = self._masks.get(key)
        if mask is not None:
            return mask
        if len(self._masks) > 64:
            self._masks.clear()
        opt = QStyleOptionTab()
        self.initStyleOption(opt, index)
        opt.state &= ~QStyle.State_HasFocus
        opt.rect = QRect(rect)   # styles may lay the label out from tabRect()
        mask = QImage(max(1, int(math.ceil(rect.width() * dpr))),
                      max(1, int(math.ceil(rect.height() * dpr))),
                      QImage.Format_ARGB32_Premultiplied)
        mask.setDevicePixelRatio(dpr)
        mask.fill(0)
        p = QPainter(mask)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            p.translate(-rect.left(), -rect.top())
            self.style().drawControl(QStyle.CE_TabBarTabLabel, opt, p, self)
        finally:
            p.end()
        self._masks[key] = mask
        return mask

    def _draw_label(self, painter: QPainter, index: int, color: QColor, dpr: float) -> None:
        rect = self.tabRect(index)
        if rect.isEmpty() or not rect.intersects(self.rect()):
            return
        tinted = self._label_mask(index, rect, dpr).copy()
        p = QPainter(tinted)
        try:
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(QRectF(0, 0, rect.width(), rect.height()), color)
        finally:
            p.end()
        painter.drawImage(rect.topLeft(), tinted)

    def paintEvent(self, _event) -> None:
        if self.count() == 0:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            if self._track_c.alpha() > 0:           # the track, under every tab
                track = self._box(0)
                for i in range(1, self.count()):
                    track = track.united(self._box(i))
                r = track.height() / 2
                painter.setBrush(self._track_c)
                painter.drawRoundedRect(track, r, r)
            goo = self.goo_path()
            if not goo.isEmpty():
                # The pill's own small shadow travels (and stretches) with it.
                strong = 0.5 if self._theme == "dark" else 0.11
                painter.setBrush(QColor(0, 0, 0, int(255 * strong * 0.6)))
                painter.drawPath(goo.translated(0, 1.0))
                painter.setBrush(QColor(0, 0, 0, int(255 * strong * 0.35)))
                painter.drawPath(goo.translated(0, 0.5))
                painter.setBrush(self._pill_c)
                painter.drawPath(goo)
            # Labels: the muted colour on the track; where the liquid covers
            # a label it takes the on-pill colour -- fully for the selected
            # tab (cross-faded in over 250 ms), half-way for tabs the drop is
            # only passing over. A label never sits in on-pill colour on the
            # bare track, where it could vanish (light theme: white on white).
            dpr = self.devicePixelRatioF()
            current = self.currentIndex()
            for i in range(self.count()):
                self._draw_label(painter, i, self._label_c, dpr)
            if not goo.isEmpty():
                painter.save()
                painter.setClipPath(goo)
                painter.setBrush(self._pill_c)      # cover the track-coloured labels
                painter.drawPath(goo)
                for i in range(self.count()):
                    if not goo.intersects(QRectF(self.tabRect(i))):
                        continue
                    f = 0.5 + 0.5 * self._amount(i, current)
                    self._draw_label(painter, i, _mix(self._label_c, self._on_pill_c, f), dpr)
                painter.restore()
        finally:
            painter.end()
