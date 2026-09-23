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

from ui.python.fx import FxWidget

LOBE_COLOURS = ((255, 70, 120), (60, 190, 255), (175, 70, 255), (60, 220, 130),
                (255, 150, 40), (90, 100, 255), (40, 200, 190))
PASS_S = 1.1


class WorkingGlow(FxWidget):
    """Args: height -- the fixed height in px (the glow blooms upward
    within it)."""

    def __init__(self, parent=None, height: int = 6):
        super().__init__(parent)
        raise NotImplementedError

    def level(self) -> float:
        """The current glow level 0..~0.55 (0 when stopped and faded)."""
        raise NotImplementedError
