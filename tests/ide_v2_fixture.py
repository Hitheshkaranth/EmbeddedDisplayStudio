"""Shared fixture for the Code section v2 tests (FROZEN).

A two-page design exercising everything the index knows about: nested
widgets, bindings with thresholds, write/pulse/navigate actions, the alarm
table wildcard, an empty binding and a tag the manifest does not declare.
"""
from designer.model.project import (
    DesignerAction, DesignerBinding, DesignerPage, DesignerProject, DesignerWidget,
)

# manifest tags_required for the fixture: "ai.fuel" is declared but unused,
# "ai.oiltemp" is used but NOT declared.
DECLARED_TAGS = ["ai.rpm", "ai.fuel", "di.estop", "do.pump", "do.horn"]


def widget(type_, id_, x=0, y=0, w=100, h=40, bindings=None, actions=None, children=None, **props):
    return DesignerWidget(type=type_, id=id_, geometry={"x": x, "y": y, "width": w, "height": h},
                          properties=dict(props), bindings=dict(bindings or {}),
                          actions=dict(actions or {}), children=list(children or []))


def make_project() -> DesignerProject:
    main = DesignerPage("main", "Main", [
        widget("ShGauge", "rpm", 10, 10, 200, 200,
               bindings={"value": DesignerBinding("ai.rpm", unit="rpm", warning=">4000", critical=">5000")},
               label="Engine RPM"),
        widget("ShCard", "panel", 220, 10, 300, 200, children=[
            widget("ShToggle", "pump", 10, 10, 120, 40,
                   bindings={"checked": DesignerBinding("do.pump")},
                   actions={"toggled": DesignerAction(kind="write", tag="do.pump")}),
            widget("ShButton", "horn", 10, 60, 120, 40,
                   actions={"clicked": DesignerAction(kind="pulse", tag="do.horn", ms=500)}),
        ]),
        widget("ShButton", "next", 10, 220, 120, 40,
               actions={"clicked": DesignerAction(kind="navigate", page="alarms")}),
    ])
    alarms = DesignerPage("alarms", "Alarms", [
        widget("ShAlarmTable", "table", 0, 0, 600, 300, bindings={"alarms": DesignerBinding("*")}),
        widget("ShNumDisplay", "oil", 0, 310, 200, 60, bindings={"value": DesignerBinding("ai.oiltemp")}),
        widget("ShNumDisplay", "rpm2", 210, 310, 200, 60, bindings={"value": DesignerBinding("ai.rpm")}),
        widget("ShNumDisplay", "broken", 420, 310, 200, 60, bindings={"value": DesignerBinding("")}),
        widget("ShToggle", "estop", 0, 380, 120, 40, bindings={"checked": DesignerBinding("di.estop")}),
    ])
    project = DesignerProject(name="Fixture")
    project.pages = [main, alarms]
    return project


def edsui_text(project=None) -> str:
    """The fixture as project.edsui text (indent 2, like DesignerProject.save)."""
    import json
    return json.dumps((project or make_project()).to_dict(), indent=2)
