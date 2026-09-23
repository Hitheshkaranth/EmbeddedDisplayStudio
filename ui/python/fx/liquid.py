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

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainterPath
from PySide6.QtWidgets import QTabBar

SPRING_K, SPRING_C = 380.0, 18.0
TAIL_K, TAIL_C = 170.0, 22.0
SLIDE_MS = 250


class LiquidTabBar(QTabBar):
    """A QTabBar with the liquid selection pill. Animates through the fx
    clock only while the pill moves (it sleeps when settled: centre error
    < 0.05 px, speed < 1 px/s, tail radius < 0.3 px), and jumps without
    motion when animations are switched off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    def set_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        raise NotImplementedError

    def set_colors(self, pill: QColor, on_pill: QColor, label: QColor, track: QColor) -> None:
        """The pill fill, the selected label colour, other labels, the track."""
        raise NotImplementedError

    def pill_rect(self) -> QRectF:
        """Where the pill body is right now (before stretch), in px."""
        raise NotImplementedError

    def goo_path(self) -> QPainterPath:
        """The whole liquid shape drawn this frame (body + tail + necks)."""
        raise NotImplementedError

    def settled(self) -> bool:
        """True when the pill rests under the current tab."""
        raise NotImplementedError
