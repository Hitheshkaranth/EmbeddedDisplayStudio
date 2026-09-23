#!/usr/bin/env python3
"""tagsim -- fly the bench panel: one flight, read by every instrument.

`hmi-hwd --sim` fakes the *hardware* channels (ai.pot, di.button): the tags
a wiring loom would provide. A Studio design binds whatever tags its author
invented -- nav.pitch, eng1.egt, fuel.left.qty -- and nothing on the bench
produces those, so every instrument on the glass sits at zero.

This speaks the same link as hmi-hwd (CONTRACT section 2: UDP, subscribe,
{"t":"tags"} frames) and fills those tags from a *single flight*. There is
one aeroplane: it taxis, rotates, climbs, cruises, turns, descends, lands,
and starts again. Altitude, vertical speed, pitch, airspeed, Mach, N1, EGT,
fuel, heading and bank all come from that one state, so the screen agrees
with itself -- the nose is up while the altimeter climbs, the wing is down
while the heading changes, fuel only ever falls.

The profile is a table of keyframes interpolated linearly, so every value
varies linearly between the points of the flight, which is what makes a
needle look driven rather than eased.

Each tag is matched to a quantity by what its name measures, then mapped
onto the scale of the widget that draws it, so a needle sweeps the dial it
is actually drawn on instead of pegging against the end of it. If the
altimeter should read real feet rather than a fraction of its tape, give
the tape that range in the Designer: the design's own scale always wins.

    python3 tagsim.py --project /opt/hmi_apps/current/project.edsui --port 5010

Then point the runtime at it (/etc/default/hmi-ui):

    HMI_UI_EXTRA_ARGS=--daemon-port 5010

which leaves hmi-hwd running on 5000 for the real inputs.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import time

logger = logging.getLogger("tagsim")

# ---------------------------------------------------------------------------
# The flight
# ---------------------------------------------------------------------------

#: One flight, as fractions of its duration. Everything between two rows is
#: a straight line. alt ft, ias kt, vs ft/min, pitch deg, hdg deg, n1 %,
#: flaps notches, gear 1 = down, ap 1 = engaged.
KEYFRAMES = (
    (0.00, {"alt": 0,     "ias": 0,   "vs": 0,     "pitch": 0,  "hdg": 90,  "n1": 22, "flaps": 2, "gear": 1, "ap": 0}),
    (0.05, {"alt": 0,     "ias": 25,  "vs": 0,     "pitch": 0,  "hdg": 90,  "n1": 28, "flaps": 2, "gear": 1, "ap": 0}),
    (0.08, {"alt": 0,     "ias": 155, "vs": 0,     "pitch": 2,  "hdg": 90,  "n1": 98, "flaps": 2, "gear": 1, "ap": 0}),
    (0.10, {"alt": 800,   "ias": 175, "vs": 2600,  "pitch": 14, "hdg": 90,  "n1": 97, "flaps": 2, "gear": 1, "ap": 0}),
    (0.13, {"alt": 3500,  "ias": 210, "vs": 2400,  "pitch": 12, "hdg": 96,  "n1": 95, "flaps": 1, "gear": 0, "ap": 0}),
    (0.18, {"alt": 11000, "ias": 280, "vs": 2100,  "pitch": 9,  "hdg": 132, "n1": 93, "flaps": 0, "gear": 0, "ap": 1}),
    (0.28, {"alt": 24000, "ias": 300, "vs": 1600,  "pitch": 6,  "hdg": 145, "n1": 91, "flaps": 0, "gear": 0, "ap": 1}),
    (0.36, {"alt": 35000, "ias": 295, "vs": 700,   "pitch": 4,  "hdg": 145, "n1": 88, "flaps": 0, "gear": 0, "ap": 1}),
    (0.40, {"alt": 37000, "ias": 288, "vs": 0,     "pitch": 2,  "hdg": 145, "n1": 84, "flaps": 0, "gear": 0, "ap": 1}),
    (0.52, {"alt": 37000, "ias": 288, "vs": 0,     "pitch": 2,  "hdg": 188, "n1": 84, "flaps": 0, "gear": 0, "ap": 1}),
    (0.62, {"alt": 37000, "ias": 286, "vs": 0,     "pitch": 2,  "hdg": 205, "n1": 83, "flaps": 0, "gear": 0, "ap": 1}),
    # The nose comes down before the aeroplane does: without this the
    # altimeter would already be unwinding while the pitch read up.
    (0.64, {"alt": 36200, "ias": 289, "vs": -800,  "pitch": -1, "hdg": 205, "n1": 68, "flaps": 0, "gear": 0, "ap": 1}),
    (0.68, {"alt": 31000, "ias": 290, "vs": -1700, "pitch": -2, "hdg": 205, "n1": 55, "flaps": 0, "gear": 0, "ap": 1}),
    (0.80, {"alt": 16000, "ias": 280, "vs": -1900, "pitch": -2, "hdg": 238, "n1": 48, "flaps": 0, "gear": 0, "ap": 1}),
    (0.88, {"alt": 6000,  "ias": 230, "vs": -1500, "pitch": -3, "hdg": 265, "n1": 46, "flaps": 1, "gear": 0, "ap": 1}),
    (0.93, {"alt": 2200,  "ias": 175, "vs": -900,  "pitch": -2, "hdg": 270, "n1": 52, "flaps": 3, "gear": 1, "ap": 1}),
    (0.97, {"alt": 400,   "ias": 145, "vs": -650,  "pitch": 0,  "hdg": 270, "n1": 55, "flaps": 4, "gear": 1, "ap": 0}),
    (0.99, {"alt": 0,     "ias": 120, "vs": 0,     "pitch": 3,  "hdg": 270, "n1": 30, "flaps": 4, "gear": 1, "ap": 0}),
    (1.00, {"alt": 0,     "ias": 0,   "vs": 0,     "pitch": 0,  "hdg": 270, "n1": 22, "flaps": 2, "gear": 1, "ap": 0}),
)

#: Fuel in each tank at the start and at the end of a flight, kg.
FUEL_FULL, FUEL_RESERVE = 78.0, 24.0

#: Degrees of bank per degree-per-second of turn, and the most a wing drops.
BANK_PER_TURN_RATE, BANK_LIMIT = 4.5, 27.0


def _interpolate(fraction: float) -> dict:
    """The keyframed quantities at this point of the flight."""
    fraction = min(max(fraction, 0.0), 1.0)
    previous = KEYFRAMES[0]
    for point in KEYFRAMES:
        if point[0] >= fraction:
            lo_f, lo = previous
            hi_f, hi = point
            span = (hi_f - lo_f) or 1.0
            k = (fraction - lo_f) / span
            return {name: lo[name] + (hi[name] - lo[name]) * k for name in lo}
        previous = point
    return dict(KEYFRAMES[-1][1])


def _distance_nm(fraction: float) -> float:
    """Track miles flown by this point: the area under the speed profile.

    Closed form rather than an integrator, because every value here must be
    a pure function of the time -- a restarted simulator picks the flight up
    exactly where the old one left it.
    """
    total = 0.0
    previous = KEYFRAMES[0]
    for point in KEYFRAMES:
        lo_f, lo = previous
        hi_f, hi = point
        if hi_f <= 0:
            previous = point
            continue
        upper = min(fraction, hi_f)
        if upper > lo_f:
            k = (upper - lo_f) / ((hi_f - lo_f) or 1.0)
            speed_at_upper = lo["ias"] + (hi["ias"] - lo["ias"]) * k
            total += 0.5 * (lo["ias"] + speed_at_upper) * (upper - lo_f)
        if fraction <= hi_f:
            break
        previous = point
    return total


def state_at(t: float, duration: float) -> dict:
    """Everything about the aeroplane at t seconds, as one dict.

    The flight loops: t beyond the duration is the next trip round.
    """
    fraction = (t / duration) % 1.0
    base = _interpolate(fraction)

    altitude = base["alt"]
    ias = base["ias"]
    # True airspeed grows with altitude; Mach follows from it. Both stay
    # consistent with the indicated speed the profile states.
    tas = ias * (1.0 + altitude / 1000.0 * 0.02)
    mach = tas / 573.0

    # Bank follows the turn: the wing is down exactly while the heading
    # changes, which is the part that makes a screen read as one aeroplane.
    step = max(duration * 0.002, 0.05)
    ahead = _interpolate(((t + step) / duration) % 1.0)
    turn = ahead["hdg"] - base["hdg"]
    turn = (turn + 180.0) % 360.0 - 180.0
    turn_rate = turn / step                      # degrees per second
    roll = max(-BANK_LIMIT, min(BANK_LIMIT, turn_rate * BANK_PER_TURN_RATE))

    # The ball stays centred in a coordinated turn; it is rolling in and out
    # that throws it, so slip follows the change in bank, not the bank.
    later = _interpolate(((t + 2 * step) / duration) % 1.0)
    turn_later = (later["hdg"] - ahead["hdg"] + 180.0) % 360.0 - 180.0
    roll_rate = (turn_later / step - turn_rate) * BANK_PER_TURN_RATE
    slip = max(-1.0, min(1.0, -roll_rate * 0.12))

    # Thrust drives the hot end; the oil pressure follows the shaft.
    n1 = base["n1"]
    egt = 300.0 + (n1 - 20.0) / 85.0 * 560.0
    oil_press = 18.0 + n1 / 100.0 * 68.0

    # Standard lapse rate, floored at the tropopause.
    oat = max(15.0 - altitude / 1000.0 * 1.98, -57.0)

    burnt = (FUEL_FULL - FUEL_RESERVE) * fraction
    distance_nm = _distance_nm(fraction)

    return {
        "altitude": altitude,
        "vertical_speed": base["vs"],
        "pitch": base["pitch"],
        "roll": roll,
        "turn_rate": turn_rate,
        "slip": slip,
        "heading": base["hdg"] % 360.0,
        "airspeed": ias,
        "tas": tas,
        "mach": mach,
        "n1": n1,
        "egt": egt,
        "oil_press": oil_press,
        "oat": oat,
        "flaps": base["flaps"],
        "trim": base["pitch"] * 0.4,
        "fuel_left": FUEL_FULL - burnt,
        "fuel_right": FUEL_FULL - burnt * 1.02,      # one tank feeds harder
        "distance": distance_nm * 1.852,             # km, as the trip panel reads
        "elapsed": fraction * duration / 60.0,       # minutes into the flight
        "gear_down": base["gear"] > 0.5,
        "autopilot": base["ap"] > 0.5,
        "progress": fraction,
        "climbing": base["vs"] > 100.0,
    }


# ---------------------------------------------------------------------------
# Alarms
# ---------------------------------------------------------------------------

def load_alarms(project_path: str) -> list:
    """The alarm limits the design declares, from the manifest beside it.

    A cockpit's master warning is not a lamp with a mind of its own: it
    lights because something is out of limits. Reading the same alarm list
    the panel evaluates lets the simulated lamps agree with the alarm table
    instead of blinking to their own tune.
    """
    manifest = os.path.join(os.path.dirname(project_path) or ".", "manifest.json")
    try:
        with open(manifest, encoding="utf-8") as handle:
            return list(json.load(handle).get("alarms") or [])
    except (OSError, ValueError) as exc:
        logger.info("no alarm limits to read (%s)", exc)
        return []


_OPS = {
    ">": lambda v, t: v > t, ">=": lambda v, t: v >= t,
    "<": lambda v, t: v < t, "<=": lambda v, t: v <= t,
    "==": lambda v, t: v == t, "!=": lambda v, t: v != t,
}


def _breached(limit, value) -> bool:
    if not isinstance(limit, dict) or not isinstance(value, (int, float)):
        return False
    op = _OPS.get(str(limit.get("op") or ">"))
    threshold = limit.get("value")
    if op is None or not isinstance(threshold, (int, float)):
        return False
    return op(float(value), float(threshold))


def active_alarms(alarms: list, values: dict) -> list:
    """Which of the design's alarms these values are currently breaching."""
    out = []
    for alarm in alarms:
        value = values.get(alarm.get("tag"))
        if _breached(alarm.get("critical"), value):
            out.append((alarm.get("label") or alarm.get("tag"), "critical"))
        elif _breached(alarm.get("warning"), value):
            out.append((alarm.get("label") or alarm.get("tag"), "warning"))
    return out


#: What each quantity naturally spans, for mapping onto a widget's dial.
QUANTITY_RANGE = {
    "altitude": (0.0, 38000.0), "vertical_speed": (-2600.0, 2600.0),
    "pitch": (-15.0, 15.0), "roll": (-BANK_LIMIT, BANK_LIMIT),
    "turn_rate": (-6.0, 6.0), "slip": (-1.0, 1.0),
    "heading": (0.0, 360.0), "airspeed": (0.0, 320.0), "tas": (0.0, 520.0),
    "mach": (0.0, 0.92), "n1": (20.0, 100.0), "egt": (300.0, 860.0),
    "oil_press": (18.0, 86.0), "oat": (-57.0, 15.0), "flaps": (0.0, 4.0),
    "trim": (-6.0, 6.0), "fuel_left": (0.0, FUEL_FULL),
    "fuel_right": (0.0, FUEL_FULL), "distance": (0.0, 1400.0),
    "elapsed": (0.0, 90.0), "progress": (0.0, 1.0),
}

#: Tag leaf -> quantity. The leaf is the part after the last dot.
LEAF_QUANTITY = {
    "alt": "altitude", "altitude": "altitude", "current": "altitude",
    "height": "altitude",
    "rate": "vertical_speed", "vs": "vertical_speed", "vsi": "vertical_speed",
    "climb": "vertical_speed",
    "pitch": "pitch", "roll": "roll", "bank": "roll",
    "turn": "turn_rate", "turn_rate": "turn_rate", "rate_of_turn": "turn_rate",
    "slip": "slip", "skid": "slip", "ball": "slip",
    "heading": "heading", "hdg": "heading", "track": "heading",
    "ias": "airspeed", "speed": "airspeed", "airspeed": "airspeed",
    "tas": "tas", "gs": "tas", "mach": "mach",
    "n1": "n1", "n2": "n1", "rpm": "n1", "thrust": "n1", "power": "n1",
    "egt": "egt", "temp": "egt", "temperature": "egt", "itt": "egt",
    "oat": "oat", "sat": "oat",
    "press": "oil_press", "pressure": "oil_press", "oil_press": "oil_press",
    "flaps": "flaps", "flaps_pos": "flaps", "pos": "flaps",
    "trim": "trim", "stab_trim": "trim",
    "qty": "fuel_left", "quantity": "fuel_left", "fuel": "fuel_left",
    "dist": "distance", "trip_dist": "distance", "distance": "distance",
    "time": "elapsed", "trip_time": "elapsed", "hours": "elapsed",
}

#: Per-widget-type scales, mirroring the registry's defaults (the panel has
#: no designer package to ask). tests/test_tagsim.py keeps these honest.
TYPE_RANGES = {
    "ShGauge":         {"value": (0.0, 100.0)},
    "ShTape":          {"value": (0.0, 250.0)},
    "ShEngineBar":     {"value": (0.0, 100.0)},
    "ShSegmentBar":    {"value": (0.0, 100.0)},
    "ShAutoLevel":     {"value": (0.0, 100.0)},
    "ShAnalogDisplay": {"value": (0.0, 100.0)},
    "ShProgress":      {"value": (0.0, 100.0)},
    "ShSlider":        {"value": (0.0, 100.0)},
    # No min/max in the kit: these carry their meaning in the instrument.
    "ShVSI":           {"value": (-2000.0, 2000.0)},
    "ShAttitude":      {"pitch": (-20.0, 20.0), "roll": (-45.0, 45.0)},
    "ShFuelQuantity":  {"leftValue": (0.0, 80.0), "rightValue": (0.0, 80.0),
                        "value": (0.0, 80.0)},
    "ShCompass":       {"value": (0.0, 360.0)},
    "ShTurnCoordinator": {"turnRate": (-6.0, 6.0), "slip": (-1.0, 1.0),
                          "value": (-6.0, 6.0)},
}

#: Widget types whose bound value is a lamp, not a number.
BOOLEAN_TYPES = {"ShStatDot", "ShTelltale", "ShAnnunciator", "ShToggle",
                 "ShCheckbox", "ShAlert", "ShLamp"}

#: Widget types that want text.
TEXT_TYPES = {"ShTripInfo", "ShDataField", "Text", "ShValueTile"}

#: Lamps that report a system is well: lit through the flight.
HEALTHY_WORDS = ("ok", "fix", "healthy", "ready", "valid", "avail", "good",
                 "norm", "on")
#: Lamps that report trouble: dark, because nothing is going wrong today.
FAULT_WORDS = ("warn", "fire", "fault", "alarm", "alert", "fail", "required",
               "caution", "overspeed", "err", "smoke", "ice")
#: The backdrop fades from ground to sky as the aeroplane climbs away from
#: it. Same two colours the attitude indicator paints with (efisGround,
#: efisSky), so a screen-wide backdrop and the horizon agree.
GROUND_COLOUR, SKY_COLOUR = (0x7a, 0x52, 0x30), (0x2b, 0x6f, 0xb5)
SKY_FULL_FT = 8000.0

#: Lamps that summarise the alarm state rather than report one thing.
MASTER_WORDS = ("master_warning", "master_caution", "masterwarn", "master_alarm",
                "annunciator", "alarm_active")


def _leaf(tag: str) -> str:
    return tag.rsplit(".", 1)[-1].lower()


def _explicit_range(props: dict, prop: str):
    """A range the design itself states, in any of the kit's spellings."""
    for lo_key, hi_key in (("minimumValue", "maximumValue"),
                           ("minValue", "maxValue"),
                           ("minimum", "maximum"),
                           ("warningLow", "warningHigh")):
        lo, hi = props.get(lo_key), props.get(hi_key)
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and hi > lo:
            return float(lo), float(hi)
    return None


def quantity_for(tag: str, prop: str) -> str:
    """Which part of the flight this tag reports."""
    lowered = tag.lower()
    leaf = _leaf(tag)
    if prop.lower() in ("pitch", "roll", "slip"):
        return prop.lower()
    if prop == "turnRate":
        return "turn_rate"
    if leaf in LEAF_QUANTITY:
        quantity = LEAF_QUANTITY[leaf]
        # Left and right tanks come from the same leaf ("qty"); the side is
        # in the namespace.
        if quantity == "fuel_left" and "right" in lowered:
            return "fuel_right"
        return quantity
    for word, quantity in LEAF_QUANTITY.items():
        if word in lowered:
            return quantity
    return "progress"          # unknown: still rise and fall with the flight


class Signal:
    """One tag: the part of the flight it reports, on the dial that draws it."""

    __slots__ = ("tag", "kind", "quantity", "lo", "hi", "decimals", "state_key")

    def __init__(self, tag, kind, quantity="progress", lo=0.0, hi=1.0,
                 decimals=1, state_key=""):
        self.tag, self.kind, self.quantity = tag, kind, quantity
        self.lo, self.hi = lo, hi
        self.decimals, self.state_key = decimals, state_key

    def at(self, state: dict):
        """This tag's value for the aeroplane's current state."""
        if self.kind == "bool":
            # No state key means a lamp that reports trouble: nothing is
            # going wrong on this flight, so it stays dark.
            return bool(state[self.state_key]) if self.state_key else False
        raw = float(state[self.quantity])
        if self.kind == "colour":
            span = (self.hi - self.lo) or 1.0
            unit = min(max((raw - self.lo) / span, 0.0), 1.0)
            return "#%02x%02x%02x" % tuple(
                int(round(g + (sk - g) * unit))
                for g, sk in zip(GROUND_COLOUR, SKY_COLOUR))
        if self.kind == "text":
            return format(int(round(raw)), ",d").replace(",", " ")
        q_lo, q_hi = QUANTITY_RANGE.get(self.quantity, (0.0, 1.0))
        span = (q_hi - q_lo) or 1.0
        unit = min(max((raw - q_lo) / span, 0.0), 1.0)
        return round(self.lo + unit * (self.hi - self.lo), self.decimals)


def signal_for(tag: str, widget_type: str, prop: str, props: dict) -> Signal:
    """Decide what one bound tag reports and how far its needle swings.

    The widget's own scale wins, then the kit's default for its type, then
    the quantity's natural range. The point is that a needle sweeps the dial
    it is drawn on, whatever the design asked for.
    """
    lowered = tag.lower()
    if widget_type in BOOLEAN_TYPES:
        if "gear" in lowered:
            return Signal(tag, "bool", state_key="gear_down")
        if "autopilot" in lowered or lowered.endswith(".ap"):
            return Signal(tag, "bool", state_key="autopilot")
        if any(word in lowered for word in MASTER_WORDS):
            # Lit exactly while one of the design's own alarms is breached.
            return Signal(tag, "bool", state_key="alarm_active")
        leaf = _leaf(tag)
        if any(word in leaf for word in FAULT_WORDS):
            return Signal(tag, "bool", state_key="")           # steady dark
        if any(word in leaf for word in HEALTHY_WORDS):
            return Signal(tag, "bool", state_key="engaged_true")
        return Signal(tag, "bool", state_key="climbing")

    if prop.lower() in ("color", "colour", "bordercolor", "backgroundcolor"):
        # The property decides the type: a bound colour is a colour, and a
        # backdrop's colour is about how far off the ground it is.
        quantity = quantity_for(tag, prop)
        if quantity == "progress":
            quantity = "altitude"
        return Signal(tag, "colour", quantity, 0.0, SKY_FULL_FT)

    quantity = quantity_for(tag, prop)
    span = (_explicit_range(props, prop)
            or TYPE_RANGES.get(widget_type, {}).get(prop)
            or TYPE_RANGES.get(widget_type, {}).get("value")
            or QUANTITY_RANGE.get(quantity)
            or (0.0, 100.0))
    lo, hi = span
    if widget_type in TEXT_TYPES:
        return Signal(tag, "text", quantity, lo, hi, 0)
    width = hi - lo
    decimals = 0 if width > 400 else (3 if width <= 2 else (1 if width <= 200 else 1))
    return Signal(tag, "number", quantity, lo, hi, decimals)


def plan(project: dict) -> dict:
    """Every bound tag in a design, with the part of the flight it reports.

    Reads project.edsui as plain JSON: this runs on the panel, where the
    Studio's Python is not installed.
    """
    signals = {}

    def walk(container):
        for widget in container.get("widgets") or []:
            props = widget.get("properties") or {}
            for prop, spec in (widget.get("bindings") or {}).items():
                tag = spec.get("tag") if isinstance(spec, dict) else spec
                if not isinstance(tag, str) or not tag or tag == "*":
                    continue          # "*" is the alarm table, not a value
                if tag not in signals:
                    signals[tag] = signal_for(tag, widget.get("type", ""), prop, props)
            walk(widget)

    for page in project.get("pages") or []:
        walk(page)
    return signals


def values_at(signals: dict, t: float, duration: float, alarms: list = None) -> dict:
    """Every tag's value at one instant of one flight.

    Two passes, because a master warning lamp reports on the other tags: the
    readings are produced first, the design's alarm limits are evaluated
    against exactly what is about to be sent, and the summarising lamps are
    filled in from that.
    """
    state = dict(state_at(t, duration))
    state["engaged_true"] = True
    state["alarm_active"] = False

    summary = {tag: sig for tag, sig in signals.items() if sig.state_key == "alarm_active"}
    values = {tag: sig.at(state) for tag, sig in signals.items() if tag not in summary}
    if summary:
        state["alarm_active"] = bool(active_alarms(alarms or [], values))
        for tag, sig in summary.items():
            values[tag] = sig.at(state)
    return values


def frame(signals: dict, t: float, seq: int, duration: float = 240.0,
          alarms: list = None) -> bytes:
    """One telemetry datagram, in the daemon's wire format."""
    return json.dumps({"t": "tags", "seq": seq, "ts": round(time.time(), 3),
                       "src": "tagsim", "tags": values_at(signals, t, duration, alarms)},
                      separators=(",", ":")).encode("utf-8")


def serve(signals: dict, port: int, hz: float, host: str = "127.0.0.1",
          seconds: float = 0.0, duration: float = 240.0, alarms: list = None) -> int:
    """Answer subscribers and fly the panel until stopped.

    The runtime subscribes with a ttl and re-subscribes every 2 s; a
    subscriber that stops asking stops being sent to, so a restarted
    hmi-ui never leaves this shouting at a closed socket.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.setblocking(False)
    logger.info("tagsim on %s:%d, %d tags at %.0f Hz, %.0f s per flight",
                host, port, len(signals), hz, duration)

    subscribers = {}
    started = time.monotonic()
    interval = 1.0 / hz
    seq, next_send = 0, started

    try:
        while True:
            now = time.monotonic()
            if seconds and now - started >= seconds:
                return 0

            while True:                       # drain whatever has arrived
                try:
                    data, addr = sock.recvfrom(8192)
                except (BlockingIOError, OSError):
                    break
                try:
                    msg = json.loads(data.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                cmd = msg.get("cmd")
                if cmd in ("subscribe", "ping", "list"):
                    ttl = float(msg.get("ttl") or 5.0)
                    subscribers[addr] = now + max(ttl, 2.0)
                    if cmd != "subscribe":
                        ack = {"t": "ack", "id": msg.get("id"), "ok": True, "err": ""}
                        if cmd == "list":
                            ack["tags"] = sorted(signals)
                        sock.sendto(json.dumps(ack, separators=(",", ":")).encode(), addr)
                elif cmd == "unsubscribe":
                    subscribers.pop(addr, None)
                elif cmd in ("set", "pulse", "uart_tx"):
                    # Nothing here owns hardware; acknowledge so a button
                    # press on the glass does not look like a failure.
                    sock.sendto(json.dumps(
                        {"t": "ack", "id": msg.get("id"), "ok": True, "err": ""},
                        separators=(",", ":")).encode(), addr)

            if now >= next_send:
                next_send = now + interval
                payload = frame(signals, now - started, seq, duration, alarms)
                seq += 1
                for addr, expiry in list(subscribers.items()):
                    if expiry < now:
                        subscribers.pop(addr, None)
                        logger.info("subscriber %s:%d went quiet", addr[0], addr[1])
                        continue
                    try:
                        sock.sendto(payload, addr)
                    except OSError as exc:
                        logger.debug("send to %s failed: %s", addr, exc)

            time.sleep(min(interval, 0.02))
    except KeyboardInterrupt:
        return 0
    finally:
        sock.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default="/opt/hmi_apps/current/project.edsui",
                        help="the deployed design whose tags should fly")
    parser.add_argument("--port", type=int, default=5010,
                        help="UDP port to serve on (5000 replaces hmi-hwd)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hz", type=float, default=20.0, help="frames per second")
    parser.add_argument("--duration", type=float, default=240.0,
                        help="seconds for one taxi-to-landing flight")
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="stop after this long (0 = run until stopped)")
    parser.add_argument("--print-plan", action="store_true",
                        help="show what each tag reports, then exit")
    parser.add_argument("--print-flight", type=int, default=0, metavar="N",
                        help="print N samples of the flight, then exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.print_flight:
        print("%5s %7s %7s %6s %6s %6s %6s %6s %6s" % (
            "min", "alt", "vs", "pitch", "roll", "hdg", "ias", "n1", "fuelL"))
        for i in range(args.print_flight):
            t = args.duration * i / float(args.print_flight)
            s = state_at(t, args.duration)
            print("%5.1f %7.0f %7.0f %6.1f %6.1f %6.0f %6.0f %6.0f %6.1f" % (
                t / 60.0, s["altitude"], s["vertical_speed"], s["pitch"],
                s["roll"], s["heading"], s["airspeed"], s["n1"], s["fuel_left"]))
        return 0

    if not os.path.isfile(args.project):
        logger.error("no design at %s", args.project)
        return 2
    with open(args.project, encoding="utf-8") as handle:
        project = json.load(handle)

    signals = plan(project)
    if not signals:
        logger.error("%s binds no tags; nothing to fly", args.project)
        return 2

    if args.print_plan:
        for tag in sorted(signals):
            sig = signals[tag]
            if sig.kind == "bool":
                print("%-24s lamp        %s" % (tag, sig.state_key or "steady dark"))
            else:
                print("%-24s %-11s %-15s %9.2f .. %.2f" % (
                    tag, sig.kind, sig.quantity, sig.lo, sig.hi))
        return 0

    return serve(signals, args.port, args.hz, args.host, args.seconds,
                 args.duration, load_alarms(args.project))


if __name__ == "__main__":
    sys.exit(main())
