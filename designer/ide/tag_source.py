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
        self._poll = QTimer(self)
        self._poll.setInterval(self.POLL_MS)
        self._poll.timeout.connect(self.valuesChanged.emit)
        self._online = False
        if engine is not None:
            self._engine.onlineChanged.connect(self._handle_online)

    def _handle_online(self):
        self._online = self.is_online()
        self.onlineChanged.emit(self._online)

    def is_online(self) -> bool:
        if self._engine is None:
            return False
        try:
            return bool(self._engine.get_online())
        except Exception:
            return False

    def name(self) -> str:
        return "Panel"

    def engine(self):
        """The wrapped TagEngine (or None)."""
        return self._engine

    def value(self, tag: str):
        if self._engine is None:
            return None
        try:
            return self._engine.value(tag, None)
        except Exception:
            return None

    def can_write(self) -> bool:
        return self._engine is not None

    def write(self, tag: str, value) -> bool:
        if isinstance(value, bool):
            pass
        elif isinstance(value, (int, float)):
            pass
        else:
            return False
        if self._engine is None:
            return False
        try:
            self._engine.write(tag, value)
            return True
        except Exception:
            return False

    def start(self) -> None:
        if self._poll.isActive():
            return
        self._poll.start()
        if self.is_online():
            self._online = True
            self.onlineChanged.emit(True)

    def stop(self) -> None:
        stopped_poll = self._poll.isActive()
        if not stopped_poll:
            if self._online:
                self._online = False
                self.onlineChanged.emit(False)
            return
        self._poll.stop()
        if self._engine is not None:
            try:
                self._engine.onlineChanged.disconnect(self._handle_online)
            except (TypeError, RuntimeError):
                pass
        self._online = False
        self._poll.stop()


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
        self._tags = list(tags)
        self._overrides = {}
        self._ranges = {}
        self._start = None
        self._timer = QTimer(self)
        self._timer.setInterval(SIM_PERIOD_MS)
        self._timer.timeout.connect(self.valuesChanged.emit)
        self._online = False

    def set_tags(self, tags) -> None:
        self._tags = list(tags)
        self._ranges = {}

    def name(self) -> str:
        return "Simulator"

    def tags(self) -> list:
        return sorted(self._tags)

    def set_range(self, tag: str, lo: float, hi: float) -> None:
        self._ranges[tag] = (float(lo), float(hi))

    def sample(self, tag: str, t: float):
        if tag in self._overrides:
            return self._overrides[tag]
        low = tag[:3]
        if low == "sys":
            if tag == "sys.uptime":
                return round(t, 3)
            return 0
        if low == "di." or low == "do.":
            h = zlib.crc32(tag.encode())
            period = 2 + (h % 5)
            return t % period < period * 0.5
        if tag not in self._tags:
            return None
        h = zlib.crc32(tag.encode())
        period = 4 + (h % 7)
        phase = math.radians(h % 360)
        raw = 50 + 40 * math.sin(2 * math.pi * t / period + phase)
        if tag in self._ranges:
            lo, hi = self._ranges[tag]
            raw = lo + ((raw - 10) / 100) * (hi - lo)
        return round(raw, 3)

    def clear_overrides(self) -> None:
        self._overrides = {}

    def value(self, tag: str):
        if tag not in self._tags:
            return None
        t = self._clock()
        if self._start is not None:
            t -= self._start
        return self.sample(tag, t)

    def is_online(self) -> bool:
        return self._online

    def can_write(self) -> bool:
        return True

    def write(self, tag: str, value) -> bool:
        if tag not in self._tags:
            return False
        self._overrides[tag] = value
        self.valuesChanged.emit()
        return True

    def start(self) -> None:
        if self._online:
            return
        self._online = True
        self._start = self._clock()
        self._timer.start()
        self.onlineChanged.emit(True)

    def stop(self) -> None:
        if not self._online:
            return
        self._online = False
        self._start = None
        self._timer.stop()
        self.onlineChanged.emit(False)


def ranges_from_index(index) -> dict:
    """{tag: (lo, hi)} for SimulatedTagSource.set_range, from the design:
    for each tag read by a widget whose properties carry a numeric range
    ("minimum"/"maximum", else "minValue"/"maxValue", else "min"/"max"), the
    first such widget in design order wins. Needs index.project (the
    DesignerProject) to read properties; widgets without a finite range with
    lo < hi are skipped."""
    project = getattr(index, "project", None)
    if project is None:
        return {}
    ranges = {}
    widgets = index.widgets() if hasattr(index, "widgets") else []

    def as_finite(prop):
        if prop not in properties:
            return None
        value = properties[prop]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    for widget in widgets:
        properties = {}
        for page_index, pg in enumerate(getattr(project, "pages", []) or []):
            for w in list(pg.walk()):
                if w.id == widget.id:
                    properties = getattr(w, "properties", {}) or {}
                    break
            if properties:
                break
        pairs = (("minimum", "maximum"), ("minValue", "maxValue"), ("min", "max"))
        lo = hi = None
        for low, high in pairs:
            if low in properties and high in properties:
                lo = as_finite(low)
                hi = as_finite(high)
                break
        if lo is None or hi is None or not (lo < hi):
            continue
        for tag in widget.tags_read():
            if tag not in ranges:
                ranges[tag] = (lo, hi)
    return ranges


__all__ = ["TagSource", "EngineTagSource", "SimulatedTagSource", "ranges_from_index", "SIM_PERIOD_MS"]

# Imported for the implementation; keeps the skeleton's import list stable.
_ = (math, zlib, QTimer)
