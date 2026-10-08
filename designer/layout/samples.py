"""designer/layout/samples.py -- sample a design's readings from one moment.

A planned reply carries a realistic sample value for each reading, but each
reading is a sample on its own: a reply that names six readings has six
numbers the model thought were plausible, and they do not agree. The bench
simulator (daemon/tagsim.py) drives a design's bound tags from one flight,
so a reading is what that flight would show at one instant. coherent_samples
rewrites the samples from that one instant, so every reading on the screen
reads the same moment -- a train at 64 km/h, not a speed that disagrees with
its next station.

The sample property is the one the reading is bound on (a value, a text, a
current station index, details ...): the widget's own bound property, written
with the value that tag reports at t.
"""
from __future__ import annotations

#: The instant of the journey a planned design is sampled from, seconds into
#: the service. Fixed, not "now", so a design's samples never drift from the
#: bench it will run on, and a second pass rewrites nothing.
SAMPLE_T = 40.0

#: How long one sample of the journey is, seconds. The same default the bench
#: uses for a frame, so the value a reading shows is the value a live panel
#: would show at this instant.
JOURNEY_DURATION = 240.0

# The bound property each widget kind shows on its face, so a bound tag maps
# onto the sample property the compiler reads. A widget shows "value" unless
# it shows one of these instead.
_TEXT_LIKE = ("ShValueTile", "ShNumDisplay", "ShAutoReadout", "ShDataField",
              "ShTripInfo", "ShIndicator", "ShGearIndicator", "ShDataField",
              "Text", "ShIconTile")
_DETAILS_LIKE = ("ShStationLine",)


def _bound_property(widget, prop):
    """The sample property for a widget's bound property `prop`.

    The widget shows the bound property itself on its face: a value, a text,
    a current station index, details ...; that is what is sampled.
    """
    return prop


def _widget_sample_property(widget, prop):
    """The property a widget's reading shows, so the sample lands where it is
    drawn. The binding key is the bound property; for the widget kinds that
    show text we keep it, and so does a station line's details/current."""
    return prop


def coherent_samples(project, t: float = SAMPLE_T) -> int:
    """Rewrite a design's sample readings from one instant of its journey.

    Builds the bench simulator's plan from the project, reads every bound
    tag's value at t, and writes it into the widget's bound property (the
    value, text, current or details that property reads) when that is not
    already that value. Returns how many samples it changed, 0 when the design
    is already coherent.
    """
    from daemon import tagsim

    try:
        signals = tagsim.plan(project.to_dict())
        if not signals:
            return 0
        values = tagsim.values_at(signals, t, JOURNEY_DURATION)
    except Exception:
        return 0

    changed = 0
    for widget in project.all_widgets():
        for prop, binding in list(widget.bindings.items()):
            tag = getattr(binding, "tag", "")
            value = values.get(tag)
            if value is None:
                continue
            if prop in widget.bindings and widget.properties.get(prop) == value:
                continue
            widget.properties[prop] = value
            changed += 1
    return changed