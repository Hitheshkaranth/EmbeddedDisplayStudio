"""ui/python/fx -- the Studio's animated effects, ported to QPainter.

Ports of Libraries.dev (https://github.com/Jakubantalik/Libraries.dev, MIT,
(c) 2026 Jakub Antalik) from React/CSS/WebGL to plain QPainter: no numpy (the
packaged Studio excludes it), no OpenGL, no web engine. See docs/UI_FX.md.

    beam.BorderBeam     animated glow travelling a widget's border
    glow.WorkingGlow    a coloured beam sweeping a bar while work runs
    orb.ThinkingOrb     nine "thinking" states drawn from dots
    avatar.BotAvatar    an animated agent face
    metal.MetalRing     a liquid-metal rim around a widget (the logo)
    mosaic.MosaicView   a pixel-mosaic loader that dissolves into an image
    liquid.LiquidTabBar a tab bar whose selection flows like liquid

This module is the shared part: one clock that drives every running effect
(so a dozen effects cost one timer, and no timer runs when nothing
animates), the user's "Animations" switch, and small helpers.

FROZEN CONTRACT (UI FX swarm, 2026-09-23): the coordinator owns this file.
"""
from __future__ import annotations

import math
import time
import weakref

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QWidget

SETTINGS_KEY = "ui/animations"
# The rate the clock ticks at while anything animates. Effects that need
# less (the pulse and metal presets are tuned for 15-30 fps) skip ticks.
FRAME_MS = 16


_enabled = None      # cached: paintEvent asks on every frame


def animations_enabled() -> bool:
    """The user's switch (QSettings "MIL-HMI"/"Deployer" key SETTINGS_KEY,
    default on). With it off every effect draws one still frame."""
    global _enabled
    if _enabled is None:
        value = QSettings("MIL-HMI", "Deployer").value(SETTINGS_KEY, True)
        _enabled = value not in (False, "false", "0", 0)
    return _enabled


def set_animations_enabled(enabled: bool) -> None:
    global _enabled
    _enabled = bool(enabled)
    QSettings("MIL-HMI", "Deployer").setValue(SETTINGS_KEY, _enabled)
    FxClock.instance().animationsChanged.emit(_enabled)


def now() -> float:
    """Seconds on the monotonic clock every effect shares, so two orbs on
    screen stay in phase, as the web versions do."""
    return time.monotonic()


class FxClock(QObject):
    """One QTimer for every effect.

    An effect calls subscribe(widget, callback, fps) when it starts
    animating and unsubscribe(widget) when it stops. The callback gets the
    shared time in seconds. The timer runs only while at least one
    subscribed widget is visible and animations are enabled; a widget that
    is hidden (another tab, a minimised window) is skipped, and one that is
    deleted drops out on its own (the clock holds weak references).

    Signals:
        animationsChanged(bool): the user flipped the switch; effects redraw
            (a still frame when off) and subscribe again when on.
    """

    animationsChanged = Signal(bool)
    _instance = None

    @classmethod
    def instance(cls) -> "FxClock":
        if cls._instance is None:
            cls._instance = FxClock()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._subs: dict[int, tuple] = {}     # id(widget) -> (weakref, callback, period, last)
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.animationsChanged.connect(self._on_switch)

    def subscribe(self, widget, callback, fps: float = 60.0) -> None:
        """Calls callback(t) about fps times a second while `widget` is
        visible. Subscribing again replaces the previous callback."""
        period = 1.0 / max(1.0, min(60.0, fps))
        self._subs[id(widget)] = (weakref.ref(widget), callback, period, 0.0)
        if animations_enabled() and not self._timer.isActive():
            self._timer.start()

    def unsubscribe(self, widget) -> None:
        self._subs.pop(id(widget), None)
        if not self._subs:
            self._timer.stop()

    def is_running(self) -> bool:
        """True while the timer ticks (tests, and the idle-CPU check)."""
        return self._timer.isActive()

    def subscribers(self) -> int:
        return len(self._subs)

    def _on_switch(self, enabled: bool) -> None:
        if enabled and self._subs:
            self._timer.start()
        elif not enabled:
            self._timer.stop()

    def _tick(self) -> None:
        t = now()
        visible = 0
        for key, (ref, callback, period, last) in list(self._subs.items()):
            widget = ref()
            if widget is None:
                self._subs.pop(key, None)
                continue
            try:
                shown = widget.isVisible()
            except RuntimeError:              # the C++ side is gone
                self._subs.pop(key, None)
                continue
            if not shown:
                continue
            visible += 1
            if t - last >= period * 0.9:
                self._subs[key] = (ref, callback, period, t)
                callback(t)
        if not self._subs:
            self._timer.stop()
        elif not visible:
            # Nothing on screen: tick slowly just to notice a widget
            # becoming visible again, instead of 60 times a second.
            self._timer.setInterval(250)
            return
        self._timer.setInterval(FRAME_MS)


class FxWidget(QWidget):
    """Base of the effect widgets: owns running / theme / the still frame.

    Subclasses implement paint_frame(painter, t) -- draw the effect at time t
    (seconds, the shared clock) -- and may override advance(t, dt) for
    effects with state (springs, a simulation), `fps`, and still_time().

    start() subscribes to the clock; stop() unsubscribes and repaints one
    still frame. With animations switched off (or not running) paintEvent
    draws paint_frame(painter, still_time()), so every effect has a sensible
    static look. The painter arrives with antialiasing on and nothing
    clipped; paint_frame must not leave state behind (save/restore).
    """

    fps = 60.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "dark"
        self._running = False
        self._t = now()
        self._last = None
        FxClock.instance().animationsChanged.connect(self._on_switch)

    # -- public
    def theme(self) -> str:
        return self._theme

    def set_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        self._theme = "light" if theme == "light" else "dark"
        self.update()

    def start(self) -> None:
        self._running = True
        self._last = None
        if animations_enabled():
            FxClock.instance().subscribe(self, self._tick, self.fps)
        self.update()

    def stop(self) -> None:
        self._running = False
        FxClock.instance().unsubscribe(self)
        self.update()

    def is_running(self) -> bool:
        return self._running

    def animating(self) -> bool:
        """Running and allowed to move (the switch is on)."""
        return self._running and animations_enabled()

    def render_at(self, t: float, size=None):
        """A QImage of the effect at time t (tests, galleries)."""
        from PySide6.QtGui import QImage, QPainter
        size = size or self.size()
        image = QImage(max(1, size.width()), max(1, size.height()), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            self.paint_frame(painter, t)
        finally:
            # Qt aborts the process if a device is destroyed mid-paint, so an
            # exception in paint_frame must still end the painter.
            painter.end()
        return image

    # -- for subclasses
    def paint_frame(self, painter, t: float) -> None:
        raise NotImplementedError

    def advance(self, t: float, dt: float) -> None:
        """Step any state to time t (dt seconds since the last tick, 0 on
        the first, capped at 0.1)."""

    def still_time(self) -> float:
        return 0.6

    # -- Qt
    def paintEvent(self, _event):
        from PySide6.QtGui import QPainter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            self.paint_frame(painter, self._t if self.animating() else self.still_time())
        finally:
            painter.end()

    def _tick(self, t: float) -> None:
        dt = 0.0 if self._last is None else min(0.1, max(0.0, t - self._last))
        self._last = t
        self._t = t
        self.advance(t, dt)
        self.update()

    def _on_switch(self, enabled: bool) -> None:
        if self._running and enabled:
            FxClock.instance().subscribe(self, self._tick, self.fps)
        elif not enabled:
            FxClock.instance().unsubscribe(self)
        self.update()


# ------------------------------------------------------------------ helpers
# Shared by the ports; the web originals use these CSS / JS curves.

def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def smoothstep(e0: float, e1: float, x: float) -> float:
    t = clamp01((x - e0) / (e1 - e0)) if e1 != e0 else (1.0 if x >= e1 else 0.0)
    return t * t * (3.0 - 2.0 * t)


def cubic_bezier(x1: float, y1: float, x2: float, y2: float):
    """CSS cubic-bezier(x1, y1, x2, y2) as a function of progress 0..1."""
    def sample(t, a, b):
        return ((1 - 3 * b + 3 * a) * t + (3 * b - 6 * a)) * t * t + 3 * a * t

    def solve(x):
        t = x
        for _ in range(8):                  # Newton, then bisection fallback
            err = sample(t, x1, x2) - x
            d = (3 * (1 - 3 * x2 + 3 * x1) * t + 2 * (3 * x2 - 6 * x1)) * t + 3 * x1
            if abs(err) < 1e-6:
                return t
            if abs(d) < 1e-6:
                break
            t -= err / d
        lo, hi = 0.0, 1.0
        t = x
        for _ in range(30):
            v = sample(t, x1, x2)
            if abs(v - x) < 1e-6:
                break
            lo, hi = (t, hi) if v < x else (lo, t)
            t = (lo + hi) / 2
        return t

    return lambda p: sample(solve(clamp01(p)), y1, y2)


EASE = cubic_bezier(0.25, 0.1, 0.25, 1.0)          # CSS "ease"
EASE_IN_OUT = cubic_bezier(0.42, 0.0, 0.58, 1.0)   # CSS "ease-in-out"


def ease_out_cubic(p: float) -> float:
    p = clamp01(p)
    return 1.0 - (1.0 - p) ** 3


def js_round(x: float) -> int:
    """JavaScript Math.round (halves go up); Python's round() goes to even."""
    return int(math.floor(x + 0.5))


def hash01(a: float, b: float) -> float:
    """The ports' shared hash: frac(sin(12.9898a + 78.233b) * 43758.5453)."""
    v = math.sin(12.9898 * a + 78.233 * b) * 43758.5453
    return v - math.floor(v)
