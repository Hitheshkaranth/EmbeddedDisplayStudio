"""ui/python/fx/avatar.py -- Bot Avatars: an animated agent face.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-C. Port of libdev
packages/bot-avatars (canvas 2D: draw.ts, engine.ts, shapes.ts, color.ts,
presets.ts; the React Native Skia port in ports/react-native maps nearly
1:1 onto QGradient). Shading: the 'smooth' mode (17 depth slices of the
outline, the multiply shadow and white highlight radial overlays) and
'crisp' -- NOT 'plastic', which needs per-texel numpy work the packaged
Studio does not ship. The face (eyes: open / shut / laugh / sleep lids,
blink, darts, gaze) and the engine's idle motion (wander, breathing, jelly,
blinks, the working-state hops, the sleeping nod) are ported; the pointer
follow is optional (enable with interactive=True, uses mouse tracking);
clicks call poke() (a hop). Canvas-to-Qt: an affine (a,b,c,d,e,f) is
QTransform(a,b,c,d,e,f); SVG endpoint arcs need a small converter (or
rebuild the shape from the generator formulas in scripts/gen-shapes.mjs).

The widget is square; the body occupies size / 1.5 of it (OVERSCAN 1.5, as
the source) so hops and spins stay inside.
"""
from __future__ import annotations

from PySide6.QtGui import QPainterPath

from ui.python.fx import FxWidget

# At least these seven shapes; the others are welcome.
SHAPES = ("clover", "flower", "circle", "blob", "square", "droid", "ghost")
AVATAR_STATES = ("default", "working", "sleeping")
PRESET_COLOURS = {"clover": "#35B8FF", "flower": "#2FCB7A", "circle": "#9A62FF",
                  "blob": "#2FCB7A", "square": "#35B8FF", "droid": "#D5DBEA",
                  "ghost": "#F4F2FA"}


def shape_path(shape: str) -> QPainterPath:
    """The body outline in the source's 100 x 100 design box (centre 50,50),
    filled with Qt.WindingFill. ValueError for an unknown shape."""
    raise NotImplementedError


class BotAvatar(FxWidget):
    """Args:
        shape: one of SHAPES (or any extra shape the port adds).
        size: the widget's side in px (the body is size / 1.5).
        state: one of AVATAR_STATES.
        color: body colour (None: the shape's preset colour).
        seed: 0..1, varies the idle motion between instances.
        interactive: follow the pointer (needs mouse tracking).
    The avatar animates while running (start/stop from FxWidget); its still
    frame is the rest pose of its state.
    """

    def __init__(self, parent=None, shape: str = "clover", size: int = 40,
                 state: str = "default", color=None, seed: float = 0.37,
                 interactive: bool = False):
        super().__init__(parent)
        raise NotImplementedError

    def state(self) -> str:
        raise NotImplementedError

    def set_state(self, state: str) -> None:
        """Blend to `state` over the source's durations (to default 1.2 s,
        working 0.7 s, sleeping 1.4 s; from sleeping 1.0 s). ValueError for
        an unknown state."""
        raise NotImplementedError

    def set_shape(self, shape: str) -> None:
        raise NotImplementedError

    def poke(self) -> None:
        """A click: a hop with a spin (ignored while one is under way)."""
        raise NotImplementedError

    def pose(self) -> dict:
        """The current pose fields (yaw, pitch, roll, x, y, sx, sy, eyeOpen,
        blink, lookX, lookY, breath, laugh, w) -- for tests."""
        raise NotImplementedError
