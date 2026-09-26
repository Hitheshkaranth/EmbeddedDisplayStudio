"""designer/ide/tag_source.py -- where the Code section's live tag values come from.

The Backend pane (designer/ide/tag_panel.py) shows each tag's current value.
It reads them through the small TagSource interface below, so the same pane
works against:

* EngineTagSource -- the Studio's one TagEngine (gui/hmi_loader/tagengine.py,
  built by DevicePanel.ensure_tag_engine), i.e. real telemetry from the
  panel, the Tag Lab, or the Studio's simulator, whichever drives UDP 5001.
* SimulatedTagSource -- no network at all: a value per tag computed from
  time alone, so a design shows moving numbers with no panel attached.

The pane polls (`snapshot`) on its own timer while it is visible; sources
also emit `valuesChanged` when they know new values arrived, which the pane
may use to refresh sooner. Values are JSON scalars (float, int, bool, str)
or None for "unknown / read failed" (CONTRACT 2.4 publishes a failed read
as null).

See docs/CODE_SECTION.md, "Widget visibility and backend".
"""
from __future__ import annotations

import math
import time
import zlib

from PySide6.QtCore import QObject, QTimer, Signal

# Simulator refresh period. 10 Hz matches the daemon's frame rate (CONTRACT
# 2.4, 100 ms), so a design looks the same against both.
SIM_PERIOD_MS = 100


class TagSource(QObject):
    """Interface. Subclasses override the methods marked "override".

    Signals:
        valuesChanged(): new values are available (may be emitted often;
            receivers throttle).
        onlineChanged(bool): the source started / stopped delivering.
    """

    valuesChanged = Signal()
    onlineChanged = Signal(bool)

    def name(self) -> str:
        """Short label for the pane's status line, e.g. "Panel", "Simulator"."""
        return "None"

    def is_online(self) -> bool:
        """True while values are live. override"""
        return False

    def value(self, tag: str):
        """The current value of `tag`, or None when unknown. override"""
        return None

    def snapshot(self, tags) -> dict:
        """{tag: value(tag)} for every tag in `tags` (value may be None)."""
        return {tag: self.value(tag) for tag in tags}

    def can_write(self) -> bool:
        """True when write() does something. override"""
        return False

    def write(self, tag: str, value) -> bool:
        """Asks the source to set `tag` to `value`; True when sent/applied.
        The base class refuses. override"""
        return False

    def start(self) -> None:
        """Begins delivering values (idempotent). override"""

    def stop(self) -> None:
        """Stops delivering values (idempotent); is_online() is then False. override"""


class EngineTagSource(TagSource):
    """Adapter over a TagEngine (gui/hmi_loader/tagengine.py).

    name()       -- "Panel".
    is_online()  -- engine.get_online(); False
                    when the engine is None.
    value(tag)   -- engine.value(tag, None); never raises (an engine error
                    reads as None).
    can_write()  -- True when the engine is not None.
    write(t, v)  -- engine.write(t, v) for bool/int/float values, True; False
                    for any other value type, or when the engine raised.
    start/stop   -- connect / disconnect the engine's onlineChanged (emit
                    our onlineChanged(is_online())) and start / stop a
                    250 ms QTimer that emits valuesChanged while online.
                    The engine itself is never started, stopped or closed:
                    the Studio owns it.
    """

    POLL_MS = 250

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        raise NotImplementedError  # W3

    def engine(self):
        """The wrapped TagEngine (or None)."""
        raise NotImplementedError  # W3


class SimulatedTagSource(TagSource):
    """Values from time alone; no sockets, no threads.

    name()      -- "Simulator".
    tags        -- the tags it answers for, set_tags() replaces them; any
                   other tag reads None.
    value(tag)  -- sample(tag, clock() - started):
        * a written override (write()) wins until clear_overrides();
        * "di." / "do." tags (bool): a square wave, period 2 s + (h % 5) s,
          True in the first half of each period;
        * "sys." tags: "sys.uptime" -> elapsed seconds (float), any other
          "sys." -> 0 (int);
        * every other tag (float): 50 + 40 * sin(2*pi*t / P + phase), where
          P = 4 s + (h % 7) s and phase = (h % 360) degrees in radians;
        h = zlib.crc32(tag.encode()) -- deterministic across runs (never use
        hash(), it is salted per process). Floats are rounded to 3 places.
    ranges      -- set_range(tag, lo, hi) rescales that tag's float wave
                   from 10..90 onto lo..hi (so a gauge's needle stays on its
                   dial); cleared by set_tags.
    is_online() -- True between start() and stop().
    can_write() -- True; write(tag, value) stores an override for a known
                   tag (True) and emits valuesChanged; unknown tag -> False.
    start()     -- records the start time, starts a SIM_PERIOD_MS QTimer
                   emitting valuesChanged, emits onlineChanged(True) (only on
                   an actual change). stop() is the reverse.
    clock       -- injectable monotonic clock (tests pass a fake).
    """

    def __init__(self, tags=(), clock=time.monotonic, parent=None):
        super().__init__(parent)
        self._clock = clock
        raise NotImplementedError  # W3

    def set_tags(self, tags) -> None:
        raise NotImplementedError  # W3

    def tags(self) -> list:
        """The tags answered for, sorted."""
        raise NotImplementedError  # W3

    def set_range(self, tag: str, lo: float, hi: float) -> None:
        raise NotImplementedError  # W3

    def sample(self, tag: str, t: float):
        """The value of `tag` at `t` seconds after start, ignoring overrides."""
        raise NotImplementedError  # W3

    def clear_overrides(self) -> None:
        raise NotImplementedError  # W3


def ranges_from_index(index) -> dict:
    """{tag: (lo, hi)} for SimulatedTagSource.set_range, from the design:
    for each tag read by a widget whose properties carry a numeric range
    ("minimum"/"maximum", else "minValue"/"maxValue", else "min"/"max"), the
    first such widget in design order wins. Needs index.project (the
    DesignerProject) to read properties; widgets without a finite range with
    lo < hi are skipped."""
    raise NotImplementedError  # W3


__all__ = ["TagSource", "EngineTagSource", "SimulatedTagSource", "ranges_from_index", "SIM_PERIOD_MS"]

# Imported for the implementation; keeps the skeleton's import list stable.
_ = (math, zlib, QTimer)
