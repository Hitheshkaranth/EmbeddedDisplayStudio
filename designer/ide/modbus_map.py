"""designer/ide/modbus_map.py -- a deterministic Modbus map from a design.

A design's bindings name tags like ``train.speed``; the panel's daemon speaks
Modbus and those tags must become ``mb.`` registers. This module derives, from
every bound value, the Modbus register it maps to (kind, type, address, and an
``enum`` when the value is a station's name), rebinds the widgets to the new
``mb.`` names, and writes the daemon's ``hwd.json`` so the panel runs the map.

    generate_map(project, host, port, unit_id) -> the map to apply + write.
    apply_map(project, mapping)               -> how many values were rebound.
    write_hwd(bundle_dir, mapping, template)  -> the hwd.json path written.

Every register of a given kind is assigned a distinct 0-based address, so two
tags never collide; 32-bit types take two. This is a generator, not a network
client: it never talks to a PLC. ("Test against PLC" in the Backend tab runs
the daemon and a sim over that map; see tag_panel.py.)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

if __package__ in (None, ""):
    # Run as a script from a project folder (the Code agent does): put the
    # repository this file lives in on the path for the imports below.
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from designer.ide.agent_context import RULES  # noqa: E402,F401

from designer.palette.widget_registry import default_registry  # noqa: E402

# The registry tells whether a property is a finite selector (doors "open"/
# "closed", a status "ok"/"warn" ...): such a value is read as a discrete
# bit, never a number.
_REGISTRY = default_registry()

# The daemon's Modbus section, as the Studio writes it: host/port/..., then
# one tag per bound value.
_MODBUS_KEYS = ("modbus", "host", "port", "unit_id", "poll_interval_ms",
                "reconnect_s", "timeout_s", "tags")

# The pattern a station name reads like: "Halasuru", "Whitefield (Kadugodi)",
# "Trinity". A leading capital letter, then letters, spaces, apostrophes,
# hyphens, parentheses.
_STATION_RE = re.compile(r"^\s*[A-Z]")

# What kind of register a binding's value becomes. A value "written by an
# action or a control" (a write action / a writable binding) is a coil or
# holding register; a value only read is a discrete or input register.
#   written  -> coil (bool) / holding (number)
#   lamps, toggles, consist doors, state/doors -> discrete
#   station name -> input uint16 with the stations, in route order, as its enum
#   other numbers -> input float32 (int16 for a whole-number index)
#   other text   -> input uint16


def generate_map(project, host: str, port: int = 502, unit_id: int = 1):
    """Derive a Modbus map from ``project``'s bound values.

    Args:
        project: the ``DesignerProject`` being wired to a PLC.
        host:    the PLC's Modbus TCP host.
        port:    the Modbus TCP port (default 502).
        unit_id: the Modbus unit id (default 1).

    Returns:
        ``{"modbus": {...tags...}, "rebind": {old_tag: "mb.<old_tag>"}}``. The
        modbus block carries host/port/unit_id, the poll/reconnect/timeout
        defaults and one tag object per bound value; rebind maps each pre-map
        tag to its post-map ``mb.`` name.
    """
    # Every bound value: (widget, prop, binding). Only a tag (not the
    # alarm table's "*" wildcard) is bound to something to map.
    bounds = []
    for page in getattr(project, "pages", []) or []:
        for widget in page.walk():
            for prop, binding in widget.bindings.items():
                tag = getattr(binding, "tag", "") or ""
                if tag and tag != "*":
                    bounds.append((widget, prop, binding, tag))

    # Station names: collect the union of every stations list on a station
    # line, so a name is enum-mapped when it is one of them.
    stations = _collect_stations(project)

    tags: dict[str, dict] = {}
    rebind: dict[str, str] = {}

    # Per-kind address counters, starting at 0, as CONTRACT 2.5 requires.
    used: dict[bool, set] = {True: set(), False: set()}

    # A tag bound by several widgets is one register: the first binding that
    # says what the value is (a number, a name, a flag) decides it.
    seen: dict[str, tuple] = {}
    for widget, prop, binding, tag in bounds:
        found = _classify(widget, prop, binding, tag, stations, project)
        if tag not in seen or (seen[tag] == ("input", "uint16", None) and found != seen[tag]):
            seen[tag] = found

    for tag, (kind, type_name, enum) in seen.items():
        new_name = f"mb.{tag}"
        rebind[tag] = new_name
        span2 = type_name in ("int32", "uint32", "float32")
        address, _ = _assign(used, kind, span2)  # 32-bit types take two
        tags[new_name] = {
            "kind": kind,
            "address": address,
            "type": type_name,
        }
        if enum is not None:
            tags[new_name]["enum"] = list(enum)

    return {
        "modbus": {
            "host": host,
            "port": port,
            "unit_id": unit_id,
            "poll_interval_ms": 200,
            "reconnect_s": 5,
            "timeout_s": 1,
            "tags": tags,
        },
        "rebind": rebind,
    }


def _classify(widget, prop, binding, tag, stations, project):
    """The register a binding's value becomes.

    A binding that writes a tag (a write action, or the control's own state
    bound to it) is written: a coil when the value is a bool, a holding
    register (number) otherwise. A read-only value is discrete (a lamp, a
    toggle, a consist door, a state/doors readout) or an input register: a
    station's name is an input uint16 whose enum is the line's stations (in
    route order), a number is an input float32 (int16 for a whole-number
    index; a text like "1.1 km" counts as a number), anything else is an
    input uint16. A widget's value is its own, else the registry's default.
    """
    # A tag a control or an action writes: a write/pulse action on it, or the
    # control's own state bound (bindable prop). Written values are coil (bool)
    # or holding (number).
    if _is_written(tag, project):
        if _widget_bool(widget, prop):
            return "coil", "bool", None
        value = _widget_value(widget, prop)
        return "holding", "float32" if isinstance(value, float) else "uint16", None

    # Read-only: a station's name is an enum over the line's stations, a
    # finite selector (doors "open"/"closed", a lit/toggle) is a discrete bit,
    # a number is an input float32 (int16 for a whole-number index).
    value = _widget_value(widget, prop)
    if _looks_like_station(tag, prop, value, stations):
        return "input", "uint16", stations
    if _is_selector(widget, prop):
        return "discrete", "bool", None
    if _is_number(value):
        if isinstance(value, int) and not re.search(r"pct|percent|speed|temp|volt|current_a|power", tag, re.I):
            return "input", "int16", None
        return "input", "float32", None
    if isinstance(value, str) and re.match(r"^\s*-?\d+(\.\d+)?\s*[A-Za-z%/]*\s*$", value):
        return "input", "float32", None                       # "1.1 km": a number with its unit
    return "input", "uint16", None


def _is_selector(widget, prop):
    """The property is a finite selector (doors, status, lit): read as a bit.
    A value with registry choices, or a door/state readout, is discrete."""
    definition = _REGISTRY.get(getattr(widget, "type", ""))
    choices = getattr(definition, "choices", {}) if definition else {}
    if prop in choices:
        return True
    # Doors, state and lit/severity readouts are state flags, not numbers.
    return bool(re.search(r"door|state|lit|severity", prop, re.I))


def _widget_bool(widget, prop):
    """The widget's value for `prop` is a bool (a lamp, a toggle)."""
    value = (getattr(widget, "properties", {}) or {}).get(prop)
    return isinstance(value, bool)


def _widget_value(widget, prop):
    """The value `prop` shows: the widget's own, else the registry's default
    (a bound property is often stored without one)."""
    value = (getattr(widget, "properties", {}) or {}).get(prop)
    if value is None:
        definition = _REGISTRY.get(getattr(widget, "type", ""))
        value = (getattr(definition, "defaults", {}) or {}).get(prop) if definition else None
    return value


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _widget_number(widget, prop):
    """The widget's value for `prop` is a number (a speed, voltage, index)."""
    return _is_number(_widget_value(widget, prop))


def _looks_like_station(tag, prop, value, stations):
    """True when the value is one station's name: a text readout whose tag
    says station (next_station, current_station) or whose text is one of the
    line's stations. An index (a number) or a list (the line's details) is
    not a name."""
    if not stations or not isinstance(value, str) or "," in value:
        return False
    if value.strip() in stations:
        return True
    return bool(re.search(r"station", tag, re.I)) and not re.search(r"index|details|count|list", tag, re.I)


def _is_written(tag, project):
    """Whether any widget writes `tag` -- a write/pulse action or a
    writable binding; such a value becomes a coil/holding register."""
    for page in getattr(project, "pages", []) or []:
        for widget in page.walk():
            for prop, action in widget.actions.items():
                for act in action.all():
                    if act.kind in ("write", "pulse") and act.tag == tag:
                        return True
    return False


def _collect_stations(project):
    """Every station on the design's station lines, in the order the train
    runs them (the first line's order, then any names only a later line has)."""
    stations: list[str] = []
    for page in getattr(project, "pages", []) or []:
        for widget in page.walk():
            value = getattr(widget, "properties", {}).get("stations")
            if isinstance(value, str):
                for part in value.split(","):
                    part = part.strip()
                    if part and part not in stations:
                        stations.append(part)
    return stations


def _assign(used, kind, is_32bit):
    """The next free address for `kind` (True = boolean kind: coil/discrete),
    counting up from 0; a 32-bit type reserves two, so the next tag starts
    past it. Returns (address, is_free) where is_free is True on first use."""
    kinds = used[kind in ("coil", "discrete")]
    span = 2 if is_32bit else 1
    addr = 0
    while any(addr + i in kinds for i in range(span)):
        addr += 1
    for i in range(span):
        kinds.add(addr + i)
    return addr, (addr == 0)


def apply_map(project, mapping) -> int:
    """Rebind every bound value in ``project`` to its ``mb.`` name.

    Sets each binding's ``tag`` to the mapping's rebind target (unless it was
    the alarm table's "*"), and returns how many values were rebound.
    """
    rebind = mapping.get("rebind", {})
    count = 0
    for page in getattr(project, "pages", []) or []:
        for widget in page.walk():
            for prop, binding in widget.bindings.items():
                tag = getattr(binding, "tag", "") or ""
                if tag and tag != "*" and tag in rebind:
                    binding.tag = rebind[tag]
                    count += 1
    return count


def write_hwd(bundle_dir, mapping, template="daemon/hwd.json"):
    """Write ``<bundle_dir>/hwd.json`` from the template, with the modbus
    section replaced by ``mapping``.

    The template carries daemon/gpio/adc; the map supplies modbus. Returns the
    path written (``<bundle_dir>/hwd.json``).
    """
    dest = os.path.join(bundle_dir, "hwd.json")
    if os.path.isfile(template):
        shutil.copyfile(template, dest)
    else:
        dest_data = {
            "daemon": {"poll_interval_ms": 100},
            "gpio": {},
            "adc": {},
        }
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(dest_data, fh, indent=2)
    with open(dest, encoding="utf-8") as fh:
        data = json.load(fh)
    data["modbus"] = mapping["modbus"]
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return dest


# ---------------------------------------------------------------------------
# The Backend tab's "Generate Modbus map..." entry
# ---------------------------------------------------------------------------

# The daemon source (template + selftest), so the panel can run the sim.
_TEMPLATE_HINT = "daemon/hwd.json"


def generate_from_project(project, host, port=502, unit_id=1):
    """``generate_map`` plus the rebind: rebinds the widgets in place and
    returns the map. The Backend tab calls this, applies it as one undo step,
    and shows the table."""
    mapping = generate_map(project, host=host, port=port, unit_id=unit_id)
    apply_map(project, mapping)
    return mapping


def hwd_path(bundle_dir):
    """Where the map is written inside a bundle."""
    return os.path.join(bundle_dir, "hwd.json")


def template_path():
    """The template hwd.json the map is written from, when present."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    path = os.path.join(repo, "daemon", "hwd.json")
    return path if os.path.isfile(path) else ""


def daemon_sim_path():
    """``daemon/plc_sim.py`` — the sim "Test against PLC" starts. Empty when
    the Wave A sim has not been added to a checkout, so the button can be
    disabled rather than offer a command that does not run."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    path = os.path.join(repo, "daemon", "plc_sim.py")
    return path if os.path.isfile(path) else ""


def daemon_main_path():
    """The daemon's main entry (``daemon/hmi_hwd.py``)."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    return os.path.join(repo, "daemon", "hmi_hwd.py")


def ask_host(parent=None):
    """Ask for the PLC's Modbus TCP host (QInputDialog.getText). Returns
    (host, True) when the user accepts, or ("", False) when cancelled."""
    from PySide6.QtWidgets import QInputDialog
    host, ok = QInputDialog.getText(parent, "Modbus",
                                    "PLC host (e.g. 172.16.20.50):",
                                    text="172.16.20.50")
    return (host or "").strip(), ok


def test_command(bundle_dir, tmp_copy=None):
    """The command "Test against PLC" runs: the daemon over a copy of the map
    with ``--sim --modbus-live --selftest`` so the frame shows the map polled.
    Returns (command, True), or ("", False) when the sim is absent. The sim is
    started separately; this command is what the panel shows running."""
    sim = daemon_sim_path()
    if not sim:
        return "", False
    hwd = hwd_path(bundle_dir)
    config = tmp_copy or hwd
    command = [sys.executable, daemon_main_path(), "--config", config,
               "--sim", "--modbus-live", "--selftest"]
    return command, True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate a Modbus map for a project.")
    parser.add_argument("--project", required=True, help="path to project.edsui")
    parser.add_argument("--host", required=True, help="PLC Modbus TCP host")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--unit-id", type=int, default=1)
    parser.add_argument("--write", action="store_true",
                        help="rebind the design to the mb.* tags, save it, and write hwd.json beside it")
    args = parser.parse_args()
    from designer.model.project import DesignerProject
    project = DesignerProject.load(args.project)
    mapping = generate_map(project, host=args.host, port=args.port, unit_id=args.unit_id)
    if args.write:
        count = apply_map(project, mapping)
        project.save(args.project)
        path = write_hwd(os.path.dirname(os.path.abspath(args.project)), mapping)
        print(f"rebound {count} bindings; wrote {path}")
    print(json.dumps(mapping, indent=2))