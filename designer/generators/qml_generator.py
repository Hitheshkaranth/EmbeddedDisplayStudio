"""Deterministic .edsui -> QML backend; independent of designer widgets."""
from __future__ import annotations
import json
import os
import re
from typing import Any


POSITIONERS = ("Row", "Column", "Grid")


class QmlGenerationError(ValueError):
    pass


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_literal(item) for item in value) + "]"
    text = str(value)
    if re.fullmatch(r"(?:Image\.|Qt\.|Text\.|Grid\.)[A-Za-z0-9_.]+", text):
        return text
    return json.dumps(text, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Simulation tag table
#
# Each entry maps a "sim.*" tag name to:
#   (lo, hi, phase_rad, slow, integer_only)
#
#   slow         – uses _ts (5× slower clock) for gradual variation.
#                  Good for altitude, fuel, baro, OAT.
#   integer_only – wraps result in Math.round() so no decimal is shown.
#
# Usage in project.edsui:
#   Store the tag name (e.g. "sim.pitch") as the property *value* string.
#   The generator detects any property value starting with "sim." and
#   replaces it with the corresponding osc() / osc_slow() QML expression.
#   This survives Studio round-trips because it lives in `properties`, not
#   in `bindings` (which the Studio UI does not currently expose).
#
# Altitude and ground_speed share phase 0.30 so they rise/fall together.
# ---------------------------------------------------------------------------
_SIM_TAGS: dict[str, tuple] = {
    # tag                   lo        hi      phase   slow   integer
    "sim.pitch":          (-20.0,    20.0,   0.00,  False, False),
    "sim.roll":           (-30.0,    30.0,   1.10,  False, False),
    "sim.ias":            ( 60.0,   200.0,   0.40,  False, False),
    "sim.ground_speed":   ( 80.0,   180.0,   0.30,  False, True ),  # integer only
    "sim.altitude":       (1000.0,  5000.0,  0.30,  True,  True ),  # slow + integer
    "sim.heading":        (  0.0,   359.0,   0.60,  True,  True ),  # slow + integer
    "sim.heading_bug":    (  0.0,   359.0,   0.90,  True,  False),
    "sim.vsi":            (-1500.0, 1500.0,  1.20,  False, False),
    "sim.fd_pitch":       (-10.0,    10.0,   0.20,  False, False),
    "sim.fd_roll":        (-15.0,    15.0,   0.80,  False, False),
    "sim.turn_rate":      ( -3.0,     3.0,   0.30,  True,  False),
    "sim.slip":           ( -1.0,     1.0,   1.70,  False, False),
    "sim.n1_eng1":        ( 50.0,    95.0,   0.00,  False, False),
    "sim.n1_eng2":        ( 50.0,    95.0,   0.70,  False, False),
    "sim.oil_press_eng1": ( 20.0,    80.0,   0.00,  False, False),
    "sim.oil_press_eng2": ( 20.0,    80.0,   1.50,  False, False),
    "sim.oil_temp_eng1":  ( 30.0,    90.0,   0.50,  False, False),
    "sim.oil_temp_eng2":  ( 30.0,    90.0,   1.00,  False, False),
    "sim.fuel_left":      ( 10.0,    90.0,   0.00,  True,  False),
    "sim.fuel_right":     ( 10.0,    90.0,   0.40,  True,  False),
    "sim.fuel2_left":     (  5.0,    80.0,   1.00,  True,  False),
    "sim.fuel2_right":    (  5.0,    80.0,   1.60,  True,  False),
    "sim.oat":            (-20.0,    40.0,   2.00,  True,  True ),
    "sim.wind_speed":     (  0.0,    50.0,   1.30,  False, True ),
    "sim.baro":           ( 29.50,   30.50,  0.90,  True,  True ),
    "sim.low_fuel":       (  0.0,     1.0,   2.50,  False, False),  # boolean flash
}

# Injected into the root Rectangle whenever any sim.* property value is found.
# _t  ticks at 20 Hz – fast oscillation (attitude, IAS, heading …).
# _ts ticks at  4 Hz – slow oscillation (altitude, fuel, baro, OAT …).
_SIM_CLOCK_BLOCK = """\

    // ── Simulation clock injected by qml_generator (sim.* property values) ──
    property real _t: 0.0
    property real _ts: 0.0

    Timer {
        id: _simClock
        interval: 50
        repeat: true
        running: true
        onTriggered: { root._t += 0.05; root._ts += 0.01 }
    }

    // Fast sweep – attitude, speeds, heading, VSI, engines …
    function osc(lo, hi, phase) {
        return lo + (hi - lo) * (0.5 + 0.5 * Math.sin(root._t + phase))
    }

    // Slow sweep – altitude, fuel quantity, baro, OAT (5x slower period).
    function osc_slow(lo, hi, phase) {
        return lo + (hi - lo) * (0.5 + 0.5 * Math.sin(root._ts + phase))
    }
    // ────────────────────────────────────────────────────────────────────────"""


def _sim_expression(tag: str) -> str:
    """Return the QML expression for a sim.* tag.

    Slow  → osc_slow()   (altitude, fuel, baro, OAT)
    Fast  → osc()        (everything else)
    Bool  → sign-cross   (low_fuel annunciator)
    Int   → Math.round() wrapper (ground_speed)
    """
    lo, hi, phase, slow, integer = _SIM_TAGS[tag]
    if tag == "sim.low_fuel":
        return f"(Math.sin(root._t + {phase}) > 0)"
    fn = "osc_slow" if slow else "osc"
    expr = f"{fn}({lo}, {hi}, {phase})"
    if integer:
        expr = f"Math.round({expr})"
    return expr


def _page_has_sim(page) -> bool:
    """Return True when any widget property value is a sim.* tag."""
    for widget in page.widgets:
        for w in widget.walk():
            # Check property values (primary path, survives Studio round-trips)
            for v in w.properties.values():
                if isinstance(v, str) and v in _SIM_TAGS:
                    return True
            # Also check bindings (legacy path, for hand-edited .edsui files)
            for b in w.bindings.values():
                if b.tag in _SIM_TAGS:
                    return True
    return False


class QmlGenerator:
    def __init__(self, registry):
        self.registry = registry

    def generate(self, project, project_dir: str = "", known_tags=None) -> dict[str, str]:
        issues = project.validate(self.registry, project_dir, known_tags)
        if issues:
            raise QmlGenerationError("\n".join(str(issue) for issue in issues))
        output = {}
        for page in project.pages:
            filename = f"{page.name.replace(' ', '') or page.id}.qml"
            output[filename] = self._page(project, page)
        return output

    def write(self, project, output_dir: str, project_dir: str = "", known_tags=None):
        generated = self.generate(project, project_dir, known_tags)
        os.makedirs(output_dir, exist_ok=True)
        for filename, content in generated.items():
            path = os.path.join(output_dir, filename)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        return [os.path.join(output_dir, name) for name in generated]

    def _page(self, project, page) -> str:
        lines = ["// Generated from .edsui; edit the source model, not this file.",
                 "import QtQuick 2.15", "import QtQuick.Controls 2.15",
                 "import QtQuick.Layouts 1.15", "import Shadcn 1.0", "",
                 "Rectangle {", "    id: root",
                 f"    width: {project.screen.width}",
                 f"    height: {project.screen.height}",
                 f"    color: {_literal(project.screen.background)}"]

        # Inject the simulation clock whenever any widget carries a sim.* value.
        if _page_has_sim(page):
            lines.append(_SIM_CLOCK_BLOCK)

        for widget in page.widgets:
            lines.extend(self._widget(widget, 1))
        lines.extend(["}", ""])
        return "\n".join(lines)

    def _widget(self, widget, depth, parent_type=""):
        definition = self.registry.get(widget.type)
        indent = "    " * depth
        lines = ["", f"{indent}{definition.qml_component} {{", f"{indent}    id: {widget.id}"]
        for key in ("x", "y", "width", "height"):
            if key in ("x", "y") and parent_type in POSITIONERS:
                continue
            value = widget.geometry[key]
            value = int(value) if float(value).is_integer() else value
            lines.append(f"{indent}    {key}: {value}")
        if widget.z:
            lines.append(f"{indent}    z: {widget.z}")
        aliases = {
            ("ShValueTile", "title"): "label",
            ("ShGauge", "minimum"): "minValue",
            ("ShGauge", "maximum"): "maxValue",
            ("Text", "fontSize"): "font.pixelSize",
            ("Text", "bold"): "font.bold",
            ("Rectangle", "borderColor"): "border.color",
            ("Rectangle", "borderWidth"): "border.width",
            ("ShCard", "borderColor"): "border.color",
            ("ShCard", "borderWidth"): "border.width",
            ("ShTabs", "tabs"): "model",
            ("ShSelect", "options"): "model",
            ("ShToggle", "onLabel"): "onText",
            ("ShToggle", "offLabel"): "offText",
        }
        for key, value in widget.properties.items():
            if key in widget.bindings or value == "":
                continue
            qml_key = aliases.get((widget.type, key), key)
            # Property value is a sim.* tag name → emit osc() expression.
            if isinstance(value, str) and value in _SIM_TAGS:
                lines.append(f"{indent}    {qml_key}: {_sim_expression(value)}")
                continue
            if key == "source" and isinstance(value, str) and value.startswith("assets/"):
                value = "../" + value
            if (widget.type, key) in (("ShTabs", "tabs"), ("ShSelect", "options")):
                value = [part.strip() for part in str(value).split(",") if part.strip()]
                if not value:
                    continue
            lines.append(f"{indent}    {qml_key}: {_literal(value)}")
        for key, binding in widget.bindings.items():
            qml_key = aliases.get((widget.type, key), key)
            if binding.tag in _SIM_TAGS:
                expression = _sim_expression(binding.tag)
            else:
                expression = f'Bus.value({_literal(binding.tag)}, 0)'
                if binding.multiplier != 1.0:
                    expression = f"({expression} * {binding.multiplier})"
                if binding.offset:
                    expression = f"({expression} + {binding.offset})"
                if binding.format:
                    expression = f'{_literal(binding.format)}.arg({expression})'
            lines.append(f"{indent}    {qml_key}: {expression}")
        for child in widget.children:
            lines.extend(self._widget(child, depth + 1, widget.type))
        lines.append(f"{indent}}}")
        return lines
