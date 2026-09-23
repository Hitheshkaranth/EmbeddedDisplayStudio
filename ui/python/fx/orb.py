"""ui/python/fx/orb.py -- Thinking Orbs: nine "thinking" states drawn from dots.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-B. Port of libdev
packages/thinking-orbs: engine/*.ts is pure maths (no DOM) and translates
line for line; presets.ts / profiles.ts (and spec/orbs-spec.json) hold the
tuned numbers per state and size. No physics: every state is a pure
function of time. Canvas 2D only (filled circles; straight lines for
'connecting'), so QPainter reproduces it exactly.

States -> engine modes:
    working->orbits  searching->globe  solving->rubik  listening->wave
    connecting->web  weaving->braid  composing->ribbon  breathing->ring
    shaping->morph
Sizes: the presets are tuned for 64, 32 and 20 px (32 interpolated in log
space between 64 and 20, as presets.ts does); other sizes use the nearest.
Ink is greyscale from each dot's `white` (dark theme: grey = (1-white)*255,
light theme: grey = white*255), or a tint colour (see ThinkingOrb.color).
Use JS rounding (fx.js_round) where the source uses Math.round.
"""
from __future__ import annotations

from dataclasses import dataclass

from ui.python.fx import FxWidget

STATES = ("working", "searching", "solving", "listening", "connecting",
          "weaving", "composing", "breathing", "shaping")
LABELS = {"working": "Working…", "searching": "Searching…", "solving": "Solving…",
          "listening": "Listening…", "connecting": "Connecting…", "weaving": "Weaving…",
          "composing": "Composing…", "breathing": "Thinking…", "shaping": "Shaping…"}
SIZES = (20, 32, 64)


@dataclass
class Dot:
    x: float
    y: float
    r: float
    white: float
    a: float = 1.0
    z: float = 0.0


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    w: float
    white: float
    a: float = 1.0


def frame(state: str, size: int, t: float) -> tuple[list[Dot], list[Line]]:
    """The geometry of `state` at orb time t (already multiplied by the
    preset speed) for an orb of `size` px, after finalizeFrame: dots with
    alpha < 0.02 dropped, r >= rMin, dots sorted far to near. Coordinates are
    in px within a size x size square. Pure and deterministic."""
    raise NotImplementedError


def preset_speed(state: str, size: int) -> float:
    """The preset time multiplier (e.g. working@64 = 1.885)."""
    raise NotImplementedError


class ThinkingOrb(FxWidget):
    """A size x size widget drawing `state`.

    Orb time is now() * preset_speed(state, size) * speed, so all orbs on
    screen stay in phase. The still frame (not running, or animations off)
    is t = 0.6 * preset speed, as the web version's reduced-motion frame.
    """

    def __init__(self, parent=None, state: str = "working", size: int = 20,
                 speed: float = 1.0, color=None):
        super().__init__(parent)
        raise NotImplementedError

    def state(self) -> str:
        raise NotImplementedError

    def set_state(self, state: str) -> None:
        """Switch mode (ValueError for an unknown state); repaints."""
        raise NotImplementedError

    def set_color(self, color) -> None:
        """A tint (QColor, '#rrggbb' or None for greyscale ink)."""
        raise NotImplementedError

    def label(self) -> str:
        """LABELS[state] -- the accessible name, also set as accessibleName."""
        raise NotImplementedError
