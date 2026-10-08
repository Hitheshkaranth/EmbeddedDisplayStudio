"""designer/layout/samples.py -- sample a design's readings from one moment.

A planned reply carries a realistic sample value for each reading, but each
reading is a sample on its own: a reply that names six readings has six
numbers the model thought were plausible, and they do not agree -- a next
station the station line has already passed, a train at 64 km/h one second
from the platform. The bench simulator (daemon/tagsim.py) drives a design's
bound tags from one flight or one train journey, so coherent_samples rewrites
each bound reading with what that tag reports at one instant, and every
reading on the canvas shows the same moment the bench will start from.

The sample property is the one the reading is bound on (value, text,
current, details, state ...): the widget's own bound property.
"""
from __future__ import annotations

#: The instant of the journey a planned design is sampled from, seconds into
#: the service. Fixed, not "now", so a design's samples never drift from the
#: bench it will run on, and a second pass rewrites nothing.
SAMPLE_T = 40.0

#: One flight on the bench, seconds (tagsim's default frame duration), so a
#: sample is the value a live bench would show at SAMPLE_T.
DURATION = 240.0

#: Journey parts a sample never takes:
#: - rail_clock is the wall clock, not a moment of the journey; a sample of it
#:   changes every time the pass runs.
#: - rail_progress is a hop bar's fraction; the plan's own (normalised from the
#:   model's percent by the cab) stays, the hop is told in metres beside it.
_NOT_SAMPLED = ("rail_clock", "rail_progress")

#: Bound properties that are not a reading a sample can stand in for.
_NOT_READINGS = ("data", "alarms", "series", "points", "model")


def _line(project):
    """The design's station line widget, or None."""
    return next((w for w in project.all_widgets() if w.type == "ShStationLine"), None)


def _start_where_the_train_is(project, signals) -> bool:
    """Start the line at the station the plan's train last left.

    The bench runs a journey from the line's first station, so at SAMPLE_T the
    train is always on the line's first hop. A plan whose train is further on
    (current 1, next "Indiranagar") is sampled from the hop it shows: the line
    starts at the station the train left, and the next station it names stays
    the next station. Returns True when the line changed.
    """
    line = _line(project)
    if line is None or not any(s.kind == "rail" for s in signals.values()):
        return False
    stations = [s.strip() for s in str(line.properties.get("stations") or "").split(",") if s.strip()]
    if len(stations) < 3:
        return False
    lowered = [s.lower() for s in stations]
    start = None
    # The station the plan names as next, wherever it is shown.
    for widget in project.all_widgets():
        for prop, binding in widget.bindings.items():
            sig = signals.get(getattr(binding, "tag", ""))
            if sig is None or sig.kind != "rail" or sig.state_key != "rail_next":
                continue
            name = str(widget.properties.get(prop) or "").strip().lower()
            if name in lowered and lowered.index(name) >= 1:
                start = lowered.index(name) - 1
    if start is None:
        try:
            start = int(line.properties.get("current") or 0)
        except (TypeError, ValueError):
            start = 0
    # Keep a hop and the terminus: the journey needs two stops and an end.
    start = max(0, min(start, len(stations) - 3))
    if start == 0:
        return False
    details = [s.strip() for s in str(line.properties.get("details") or "").split(",")]
    line.properties["stations"] = ",".join(stations[start:])
    if len(details) == len(stations):
        line.properties["details"] = ",".join(details[start:])
    return True


def runs_a_journey(project) -> bool:
    """True when the bench runs this design as a train journey (a cab display)."""
    from daemon import tagsim
    try:
        signals = tagsim.plan(project.to_dict())
    except Exception:
        return False
    return any(sig.kind == "rail" for sig in signals.values())


def coherent_samples(project, t: float = SAMPLE_T) -> int:
    """Rewrite a design's sample readings from one instant of its journey.

    Builds the bench simulator's plan from the project, reads every bound
    tag's value at t, and writes it into the widget's bound property when that
    is not already the value. Returns how many samples it changed, 0 when the
    design is already coherent (so a second pass changes nothing).
    """
    from daemon import tagsim

    try:
        signals = tagsim.plan(project.to_dict())
        if not signals:
            return 0
        changed = 0
        if _start_where_the_train_is(project, signals):
            changed += 1
            signals = tagsim.plan(project.to_dict())
        values = tagsim.values_at(signals, t, DURATION)
    except Exception:
        return 0

    for widget in project.all_widgets():
        for prop, binding in list(widget.bindings.items()):
            tag = getattr(binding, "tag", "")
            sig = signals.get(tag)
            if sig is None or tag not in values or prop in _NOT_READINGS:
                continue
            if sig.kind == "rail" and sig.state_key in _NOT_SAMPLED:
                continue
            value = values[tag]
            if widget.properties.get(prop) == value:
                continue
            widget.properties[prop] = value
            changed += 1
    return changed
