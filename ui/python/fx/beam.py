"""ui/python/fx/beam.py -- Border Beam: a glow travelling a widget's border.

FROZEN CONTRACT (UI FX swarm, 2026-09-23). Owner: W-A. Public names,
signatures and docstrings are the contract; bodies and private helpers are
the worker's. Port of libdev packages/border-beam (spec/beam-spec.json holds
the tuned numbers; docs/UI_FX.md has the porting notes).

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

from ui.python.fx import FxWidget

SIZES = ("sm", "md", "line")
VARIANTS = ("colorful", "mono", "ocean", "sunset")
FADE_IN_S = 0.6
FADE_OUT_S = 0.5


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
        raise NotImplementedError

    def set_active(self, active: bool) -> None:
        """Fade the beam in (and animate) or out (and stop)."""
        raise NotImplementedError

    def is_active(self) -> bool:
        """The requested state (True from set_active(True) until
        set_active(False), fades included)."""
        raise NotImplementedError

    def fade(self) -> float:
        """The current fade value 0..1 (0 = invisible)."""
        raise NotImplementedError

    def set_radius(self, radius: float) -> None:
        raise NotImplementedError

    def set_variant(self, variant: str) -> None:
        raise NotImplementedError
