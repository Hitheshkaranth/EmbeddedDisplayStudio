"""
tools/hmi_deployer/ai_generator.py -- Parse AI output into DesignerProject widgets

Takes QML code or structured JSON from OpenDesign and converts it into
DesignerProject/DesignerWidget objects that integrate with the existing canvas.
"""
import re
import json
import logging
import copy
from typing import Optional

from PySide6.QtCore import Signal, QObject
from designer.model import DesignerAction, DesignerBinding, DesignerProject, DesignerPage, DesignerWidget
from designer.model.project import TAG_RE
from designer.palette.widget_registry import WidgetDefinition, WidgetRegistry, default_registry
from designer.layout.intake import loads_lenient, normalise_properties

logger = logging.getLogger(__name__)

def _open_object(properties: dict, required=()) -> dict:
    """A JSON-schema object that names its fields and still takes others."""
    schema = {"type": "object", "additionalProperties": True, "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


_FREE_OBJECT = {"type": "object", "additionalProperties": True}

#: One widget of a planned screen: only its type is required, so a terse
#: reply (a lamp with no properties) still validates.
_PLAN_WIDGET = _open_object({
    "type": {"type": "string"},
    "id": {"type": "string"},
    "size": {"type": "string"},
    "side": {"type": "string"},
    "properties": _FREE_OBJECT,
    "bindings": _FREE_OBJECT,
    "actions": _FREE_OBJECT,
}, required=("type",))

#: The plan build_plan_prompt asks for, as a JSON schema. A server that
#: guides its decoding with it (vLLM guided_json, OpenAI json_schema, Ollama
#: format) cannot return malformed JSON or a plan without pages. Every level
#: is open (additionalProperties) and only the load-bearing keys are
#: required, so the schema never rejects a plan the compiler would accept.
PLAN_SCHEMA = _open_object({
    "name": {"type": "string"},
    "section": _open_object({
        "index": {"type": "integer"},
        "complete": {"type": "boolean"},
        "label": {"type": "string"},
        "next": {"type": "string"},
    }),
    "pages": {"type": "array", "items": _open_object({
        "id": {"type": "string"},
        "name": {"type": "string"},
        "title": {"type": "string"},
        "header": {"type": "array", "items": _PLAN_WIDGET},
        "sections": {"type": "array", "items": _open_object({
            "title": {"type": "string"},
            "role": {"type": "string"},
            "size": {"type": "string"},
            # Only when the plan follows a reference picture: where on the
            # screen the section sits (compiler.REGIONS) and its colour.
            "region": {"type": "string"},
            "accent": {"type": "string"},
            "widgets": {"type": "array", "items": _PLAN_WIDGET},
        })},
    })},
}, required=("pages",))

#: A reply that keeps fewer than this share of the tags the design had bound
#: has dropped part of the screen (the canvas guard in mainwindow counts the
#: same thing: the design's required tags).
SHORTFALL_KEEP = 0.6


def plan_shortfall(project, previous=None) -> str:
    """Why an applied reply is not the whole design, or "" when it is.

    "the reply held no widgets" when the design is empty; "the reply dropped
    N of M tags" when ``previous`` (the design the reply replaced) had bound
    tags and fewer than 60 % of them are still bound. The AI tab sends the
    brief once more when this says something.
    """
    if project is None or not any(True for page in project.pages for _w in page.walk()):
        return "the reply held no widgets"
    if previous is None:
        return ""
    before = set(previous.required_tags())
    if not before:
        return ""
    kept = before & set(project.required_tags())
    if len(kept) < SHORTFALL_KEEP * len(before):
        return f"the reply dropped {len(before) - len(kept)} of {len(before)} tags the design had"
    return ""


# Regex to extract QML code blocks from markdown or plain text.
QML_BLOCK_RE = re.compile(r"```(?:qml|QML)?\s*\n(.*?)```", re.DOTALL)
# Regex to extract JSON design payloads.
JSON_DESIGN_RE = re.compile(r"\{[\s\S]*\"pages\"[\s\S]*\}")
# The keys of a widget entry that are structure, not properties.
_WIDGET_KEYS = frozenset(("type", "id", "geometry", "properties", "bindings", "actions",
                          "children", "role", "section"))
# A legal QML id: lowercase start, then word characters.
_QML_ID_RE = re.compile(r"[a-z_][A-Za-z0-9_]*")


def _coerce_tag(tag: str) -> str:
    """Bring a model-written tag name to CONTRACT 2.5's lowercase dotted form.

    The prompt says tags are lowercase; models still write "do.pumpA.run",
    which the Designer rejects and the daemon would never answer to. Case
    and stray characters are fixed; anything still not a tag afterwards is
    returned unchanged, so validation names it rather than a guess.
    """
    if tag == "*":  # ShAlarmTable's "every alarm"
        return tag
    fixed = re.sub(r"[^a-z0-9_.]", "_", str(tag).strip().lower())
    fixed = re.sub(r"\.{2,}", ".", fixed).strip(".")
    return fixed if TAG_RE.fullmatch(fixed) else tag
# Fenced ```json block -- what build_system_prompt() asks the model for.
JSON_BLOCK_RE = re.compile(r"```(?:json|JSON)\s*\n(.*?)```", re.DOTALL)


class GeneratorProgress(QObject):
    """Signals emitted during generation."""
    progress = Signal(str)  # status message
    completed = Signal(object)  # DesignerProject or error
    error = Signal(str)


# Mapping from generic component names in AI output to our registry types.
# The AI may output "Button" instead of "ShButton" or "Panel" instead of "ShCard".
_AI_TYPE_ALIASES = {
    # Basic
    "Button": "ShButton",
    "Label": "Text",
    "Input": "ShInput",
    "TextField": "ShInput",
    "Image": "Image",
    "Rect": "Rectangle",
    # Industrial
    "Gauge": "ShGauge",
    "ProgressBar": "ShProgress",
    "Slider": "ShSlider",
    "Toggle": "ShToggle",
    "Checkbox": "ShCheckbox",
    "ComboBox": "ShSelect",
    "Dropdown": "ShSelect",
    "ValueDisplay": "ShValueTile",
    "NumericInput": "ShNumInput",
    "NumericDisplay": "ShNumDisplay",
    "AlarmTable": "ShAlarmTable",
    "Alert": "ShAlert",
    "StatusDot": "ShStatDot",
    "TrendChart": "ShTrendChart",
    "AnalogDisplay": "ShAnalogDisplay",
    # Avionics
    "DataField": "ShDataField",
    "AttitudeIndicator": "ShAttitude",
    "Tape": "ShTape",
    "Compass": "ShCompass",
    "VSI": "ShVSI",
    "EngineGauge": "ShEngineGauge",
    "Annunciator": "ShAnnunciator",
    "FlightDirector": "ShFlightDirector",
    "TurnCoordinator": "ShTurnCoordinator",
    "EngineBar": "ShEngineBar",
    "FuelQuantity": "ShFuelQuantity",
    # Automotive
    "ClusterGauge": "ShClusterGauge",
    "Tachometer": "ShClusterGauge",
    "Speedometer": "ShClusterGauge",
    "GearIndicator": "ShGearIndicator",
    "LevelBar": "ShAutoLevel",
    "FuelGauge": "ShAutoLevel",
    "TemperatureBar": "ShAutoLevel",
    "Readout": "ShAutoReadout",
    "AutoReadout": "ShAutoReadout",
    "DriveMode": "ShDriveMode",
    "Telltale": "ShTelltale",
    "IndicatorLamp": "ShTelltale",
    "TripInfo": "ShTripInfo",
    "InfoTable": "ShTripInfo",
    "SegmentBar": "ShSegmentBar",
    "BatteryBar": "ShSegmentBar",
    "IconTile": "ShIconTile",
    "AppTile": "ShIconTile",
    "VehicleStatus": "ShVehicleStatus",
    "TirePressure": "ShVehicleStatus",
    # Containers
    "Card": "ShCard",
    "Panel": "ShCard",
    "Row": "Row",
    "Column": "Column",
    "Grid": "Grid",
    "Page": "Item",
    "TabContainer": "ShTabs",
    # Names a model reaches for that the kit spells differently.
    "Lamp": "ShStatDot",
    "Led": "ShStatDot",
    "LED": "ShStatDot",
    "Indicator": "ShStatDot",
    "StatusLamp": "ShStatDot",
    "StatusLight": "ShStatDot",
    "StatusIndicator": "ShStatDot",
    "Switch": "ShToggle",
    "Chart": "ShTrendChart",
    "LineChart": "ShTrendChart",
    "Trend": "ShTrendChart",
    "Table": "ShAlarmTable",
    "AlarmList": "ShAlarmTable",
    "Tile": "ShValueTile",
    "ValueTile": "ShValueTile",
    "Kpi": "ShValueTile",
    "KPI": "ShValueTile",
    "Metric": "ShValueTile",
    "Dial": "ShGauge",
    "BarGauge": "ShEngineBar",
}


# Words a model drops or adds around an enum ("TextRight" for
# Text.AlignRight, "center" for Text.AlignHCenter); stripped before matching.
_CHOICE_NOISE = ("text", "align", "qt", "image", "grid", "mode", "_", ".", " ", "-")


def _choice_key(value) -> str:
    key = str(value).lower()
    for noise in _CHOICE_NOISE:
        key = key.replace(noise, "")
    return key


def _coerce_choices(definition, properties: dict) -> dict:
    """Map a model's enum spellings onto the registry's declared choices.

    A value already in the choices is kept; one that matches a single
    choice once the boilerplate words are stripped is replaced by it; one
    that matches nothing is dropped so the widget's default applies rather
    than the panel failing to load the page.
    """
    for key, choices in (definition.choices or {}).items():
        if key not in properties or properties[key] in choices:
            continue
        wanted = _choice_key(properties[key])
        hits = [c for c in choices if _choice_key(c) == wanted]
        if not hits:
            hits = [c for c in choices if wanted and wanted in _choice_key(c)]
        if len(hits) == 1:
            properties[key] = hits[0]
        else:
            properties.pop(key)
    return properties


# ---------------------------------------------------------------------------
# Change reporting -- what a generation did to the canvas
# ---------------------------------------------------------------------------

def _widget_index(project) -> dict:
    """Flatten a project to ``{widget_id: widget}`` (all pages, all depths)."""
    if project is None:
        return {}
    return {w.id: w for w in project.all_widgets()}


def _widget_signature(widget) -> tuple:
    """Everything the canvas draws for a widget, in a comparable shape."""
    geometry = tuple(sorted((k, float(v)) for k, v in (widget.geometry or {}).items()))
    properties = json.dumps(widget.properties or {}, sort_keys=True, default=str)
    bindings = json.dumps(
        {k: getattr(v, "tag", v) for k, v in (widget.bindings or {}).items()},
        sort_keys=True, default=str,
    )
    return (widget.type, geometry, properties, bindings)


def diff_projects(old, new) -> dict:
    """Compare two DesignerProjects the way OpenDesign reports a file diff.

    Returns ``{"added": [...], "removed": [...], "changed": [...]}`` where each
    entry is ``{"id", "type"}``; a widget counts as changed when its type,
    geometry, properties or bindings differ.  Either side may be ``None``
    (first generation / nothing parsed).
    """
    before, after = _widget_index(old), _widget_index(new)
    added = [{"id": wid, "type": w.type} for wid, w in after.items() if wid not in before]
    removed = [{"id": wid, "type": w.type} for wid, w in before.items() if wid not in after]
    changed = [
        {"id": wid, "type": w.type}
        for wid, w in after.items()
        if wid in before and _widget_signature(before[wid]) != _widget_signature(w)
    ]
    return {"added": added, "removed": removed, "changed": changed}


def merge_project_section(base, section):
    """Merge one staged AI response into the live design by stable widget id.

    Sections are page-level slices. A repeated id replaces the earlier widget
    wherever it now is, which lets a later section deliberately correct an item
    without creating a duplicate -- including one that composing moved to
    another page (looked up on the incoming page only, the correction was
    added beside it as a second widget with the same id). New pages and
    widgets retain the order the model emitted.
    """
    if base is None:
        return copy.deepcopy(section)
    if section is None:
        return copy.deepcopy(base)
    merged = copy.deepcopy(base)
    if section.name:
        merged.name = section.name
    pages = {page.id: page for page in merged.pages}
    for incoming_page in section.pages:
        target = pages.get(incoming_page.id)
        if target is None:
            target = copy.deepcopy(incoming_page)
            merged.pages.append(target)
            pages[target.id] = target
            continue
        for widget in incoming_page.widgets:
            incoming = copy.deepcopy(widget)
            home = next((page for page in merged.pages
                         if any(w.id == incoming.id for w in page.widgets)), None)
            if home is None:
                target.widgets.append(incoming)
            else:
                index = next(i for i, w in enumerate(home.widgets) if w.id == incoming.id)
                home.widgets[index] = incoming
    return merged


def drop_dangling_navigation(project) -> list:
    """Remove navigate actions to pages the finished design never made.

    Run once the design is complete: in a sectioned run a later section may
    still add the page. See designer.model.project.drop_unrunnable_actions.
    """
    if project is None:
        return []
    from designer.model.project import drop_unrunnable_actions
    return drop_unrunnable_actions(project)


def summarize_widgets(project) -> str:
    """``7 widgets: ShGauge x2, ShButton x3, Text x2`` -- for the turn conclusion."""
    if project is None:
        return "no widgets"
    counts: dict[str, int] = {}
    for widget in project.all_widgets():
        counts[widget.type] = counts.get(widget.type, 0) + 1
    total = sum(counts.values())
    if not total:
        return "no widgets"
    parts = [f"{t} x{n}" if n > 1 else t
             for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return f"{total} widget{'s' if total != 1 else ''}: " + ", ".join(parts)


# Types worth quoting a design size for whatever the brief says: the ones a
# panel screen is mostly made of. Anything the brief actually names is added.
PROMPT_CORE_TYPES = ("Text", "ShButton", "ShCard", "ShGauge", "ShClusterGauge",
                     "ShNumDisplay", "ShTrendChart", "ShAlarmTable", "ShToggle")


def _design_sizes(registry, brief: str, limit: int = 14) -> str:
    """``ShClusterGauge 240x240, ShGauge 180x180`` -- the sizes the brief needs.

    A model given no sizes invents them, and a face at the wrong size is the
    defect no prompt wording fixes afterwards (the baseline's 864x100 fuel
    gauge). Deterministic: the brief's own words first, then the core types.
    """
    if registry is None:
        return ""
    try:
        definitions = list(registry.definitions())
    except Exception:
        return ""
    words = {w for w in re.split(r"[^a-z0-9]+", (brief or "").lower()) if len(w) >= 3}
    wanted, seen = [], set()
    for definition in sorted(definitions, key=lambda d: d.type):
        haystack = f"{definition.type} {definition.display_name}".lower()
        if any(word in haystack for word in words) and definition.type not in seen:
            seen.add(definition.type)
            wanted.append(definition)
    for name in PROMPT_CORE_TYPES:
        definition = registry.get(name)
        if definition is not None and name not in seen:
            seen.add(name)
            wanted.append(definition)
    return ", ".join(f"{d.type} {d.default_width}x{d.default_height}" for d in wanted[:limit])


def compose_section(registry, screen_width: int, screen_height: int, brief: str = "") -> str:
    """The composition half of the system prompt.

    Geometry the model invents is fixed afterwards by designer.layout.polish,
    but a draft that arrives composed needs less moving, so the prompt states
    the same rules the critic measures: the grid, no overlap, aligned edges,
    one hero, every widget near its type's design size, captions under faces.
    """
    try:
        from designer.layout import grid as grid_module
        grid = grid_module.grid_for(int(screen_width), int(screen_height))
        rhythm = (f"a {grid.margin} px safe margin at every edge, a {grid.gutter} px gutter "
                  f"between columns and between rows, and {grid.rows} rows")
    except Exception:          # the layout package is optional at import time
        rhythm = "a safe margin at every edge and one consistent gutter between columns and rows"
    sizes = _design_sizes(registry, brief)
    section = (
        "\n\nCompose the screen, do not scatter it across it. Lay it out on a 12-column grid with "
        + rhythm + ". Every x, y, width and height lands on that grid, so edges are aligned: "
        "widgets side by side share a top edge and a height, widgets stacked share a left edge "
        "and a width.\n"
        "Widgets must not overlap, not by one pixel, and nothing may sit in the margin band.\n"
        "Give the screen one hero -- the instrument the brief is really about, clearly the "
        "largest thing on it -- and arrange the rest around it in reading order; leave no band "
        "of the screen empty while another is crowded.\n"
    )
    if sizes:
        section += ("Size every widget near the size its type is designed for (width x height): "
                    + sizes + ". A dial is square; never stretch a face to fill a row.\n")
    section += ("Put a short Text caption under any face that shows no label of its own, and use "
                "the top band for the screen's title rather than leaving it empty.")
    return section


_RESOLUTION_RE = re.compile(r"\b(\d{3,4})\s*[x×X*]\s*(\d{3,4})\b")


def brief_resolution(brief: str):
    """The screen size a brief names ("1920x1080", "1920 × 1080"), or None."""
    match = _RESOLUTION_RE.search(str(brief or ""))
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    return (width, height) if 160 <= width <= 7680 and 120 <= height <= 4320 else None


def page_budget(screen_width: int, screen_height: int) -> int:
    """About how many widgets one page of this screen holds before they collide.

    Measured on a real 35-widget design at 1024x768: 16-17 widgets composed
    with no overlaps (designer/layout/fit.py, FILL_LIMIT). Scaled by area.
    """
    return max(6, int(16 * (screen_width * screen_height) / (1024 * 768)))


def build_system_prompt(registry: Optional[WidgetRegistry] = None,
                        screen_width: int = 1280, screen_height: int = 800,
                        brief: str = "") -> str:
    """System prompt that steers the model at the JSON payload we parse best.

    Lists the registry's real widget types so the model does not invent
    component names, and pins the screen size so geometry lands on glass.
    When *brief* matches a design preset, its rules and exemplar are appended.
    """
    types: list[str] = []
    if registry is not None:
        try:
            types = sorted(d.type for d in registry.definitions())
        except Exception:
            types = []
    if not types:
        types = sorted(set(_AI_TYPE_ALIASES.values()))
    prompt = (
        "You are an expert HMI designer for embedded panels built with the "
        "EmbeddedDisplay Studio widget set (Shadcn-styled). "
        f"The target screen is {screen_width}x{screen_height} px; place every widget "
        "inside it with absolute geometry. "
        f"One page of this screen holds about {page_budget(screen_width, screen_height)} widgets; "
        "when a brief asks for more, keep the most important on the first page and put the "
        "rest on further pages (one per engine, system or topic), each linked by a navigate "
        "button. Every gauge, bar or tape bound to a tag sets its range in the tag's own units "
        '("minimumValue": 0, "maximumValue": 110000 for an RPM), never as a 0..1 fraction.\n\n'
        "Build large designs in small, independently valid sections of at most 8 widgets. "
        "Return exactly one section per response; never start another section in the same response. "
        "A container and all of its children count as one section and must stay together.\n\n"
        "Reply with ONE fenced ```json block containing a design section of the form:\n"
        '{"name": "<short name>", "section": {"index": 1, "complete": false, '
        '"label": "Header and status", "next": "Primary instruments"}, '
        '"pages": [{"id": "main", "name": "Main", "widgets": ['
        '{"type": "<WidgetType>", "id": "<camelCaseId>", '
        '"geometry": {"x": 0, "y": 0, "width": 200, "height": 60}, '
        '"properties": {"text": "..."}, '
        '"bindings": {"value": {"tag": "plc.tag.name", "unit": "V", "warning": "> 2.5", "critical": "> 3.0"}}, '
        '"actions": {"clicked": {"kind": "write", "tag": "do.relay1", "value": true}}}]}]}\n\n'
        "Allowed widget types: " + ", ".join(types) + ".\n"
        "Use bindings for any live value that should come from a PLC/telemetry tag; "
        "tags are lowercase dotted names (ai.pot, di.estop, do.relay1, mb.line_speed). "
        "A binding may carry \"warning\" and \"critical\" thresholds written as "
        "\"> 80\", \">= 80\", \"< 10\" or a bare number; they colour the widget and raise a panel alarm. "
        "Bind ShTrendChart.data and ShAlarmTable.alarms (tag \"*\") for history and alarm lists.\n"
        "Controls act through \"actions\", keyed by the widget's signal: "
        "ShButton clicked; ShToggle toggled; ShCheckbox checkedChanged; ShSlider and ShNumInput valueChanged; "
        "ShSelect activated; ShAlarmTable alarmActivated. "
        "Action kinds: {\"kind\": \"write\", \"tag\": \"do.x\", \"value\": true} sends a value "
        "(omit value to send the control's own state, e.g. a toggle's checked); "
        "{\"kind\": \"pulse\", \"tag\": \"do.x\", \"ms\": 250} pulses an output; "
        "{\"kind\": \"navigate\", \"page\": \"settings\"} shows another page by id. "
        "Give every start/stop/reset button an action. "
        "Keep ids unique across every section. Set section.complete=true and section.next=\"\" "
        "when the requested design is finished. Before the JSON block, write at most one sentence; "
        "after it, nothing. If asked to continue, return only the next section and do not repeat "
        "widgets already emitted."
    )
    prompt += compose_section(registry, screen_width, screen_height, brief)
    if brief:
        # The exemplar is an enhancement: a preset whose template cannot
        # be read (a packaged build that did not ship designer/templates)
        # must cost the run its exemplar, never the run itself.
        try:
            from tools.hmi_deployer.design_presets import match_preset, prompt_section
            preset = match_preset(brief)
            if preset is not None:
                prompt += "\n\n" + prompt_section(preset, screen_width, screen_height)
        except Exception as exc:
            logger.warning("design preset skipped for this brief: %s", exc)
    return prompt


# The widgets a planned screen is built from, by what they are for. Each is
# quoted with the properties that matter, so the model writes the spelling the
# widget takes (designer/layout/intake.py maps the rest).
PLAN_CATALOGUE = (
    ("hero dial (the one value the screen is about)", ("ShClusterGauge",)),
    ("dials", ("ShGauge", "ShEngineGauge")),
    ("levels and bars", ("ShEngineBar", "ShAutoLevel", "ShTape", "ShSegmentBar")),
    ("value tiles and readouts", ("ShValueTile", "ShNumDisplay", "ShAutoReadout", "ShDataField",
                                  "ShTripInfo", "ShGearIndicator")),
    ("trend", ("ShTrendChart",)),
    ("alarms", ("ShAlarmTable",)),
    ("status lamps", ("ShStatDot", "ShAnnunciator", "ShTelltale")),
    ("controls", ("ShButton", "ShToggle", "ShSlider", "ShSelect", "ShNumInput")),
    ("rail cab displays (metro, train, tram)", ("ShSpeedArc", "ShTractionBar", "ShStationLine",
                                                "ShTrainConsist", "ShStatusCard")),
    ("moving picture (a .gif the user supplies)", ("ShAnimatedImage",)),
)

_RAIL_WORDS = re.compile(r"\b(metro|train|rail|railway|cab|tram|locomotive|subway|underground|"
                         r"rolling stock|driver'?s desk)\b", re.IGNORECASE)


def is_rail_brief(brief: str) -> bool:
    """A brief for a train's cab display (designer/layout/cab.py lays it out)."""
    return bool(_RAIL_WORDS.search(brief or ""))


RAIL_PLAN_GUIDE = (
    "This is a train's driver cab display. Plan it as drivers expect, and the compiler lays it "
    "out the standard way (line and train across the top; speed left; route middle; the train "
    "right):\n"
    "- \"title\": the line's name, e.g. \"Purple Line\" (its colour becomes the accent).\n"
    "- \"header\": the train's identity and modes as ShDataField(label, value) -- train id, "
    "obstacle detection, signalling mode, door state (4 at most) -- and a Text with id "
    "\"clock\" bound to <area>.clock for the time of day.\n"
    "- a \"Drive\" section: one ShSpeedArc (value, target, maximumValue, unit) bound to the speed "
    "and the ATP/ATO target speed, one ShTractionBar (value -100..100: + traction, - braking), "
    "and two ShValueTile readings such as line voltage and ATC mode.\n"
    "- a \"Route\" section: one ShStationLine whose \"stations\" (comma separated, six at most) "
    "are the stations the brief names, in the order the train runs, ending with the line's "
    "terminus; never invent a list of the whole line. \"details\": one short note per station "
    "(COMPLETED, the train id, NEXT · 1.1 km, UPCOMING · 2.3 km, the terminus); \"current\": "
    "the index of the station the train is at or just left; bind current and details.\n"
    "- a \"Next station\" section: a ShValueTile for the next station's name (value = the name), "
    "one for the estimated arrival and one for the distance to go, and one ShProgress for "
    "this hop.\n"
    "- a \"Train\" section: ALWAYS one ShTrainConsist (cars, doorsLeft, doorsRight; the doors "
    "are shown on it, never on a status card), one ShStatusCard per on-board system the brief "
    "names (HVAC, PA, passenger emergency alarm; 3 at most: icon, title, status in words, "
    "state ok), and one ShTelltale for the platform callout (label \"Stop Marking Aligned\").\n"
    "Bind every live value to a train.* tag (train.speed, train.target_speed, "
    "train.traction_pct, train.station_index, train.station_details, train.next_station, "
    "train.eta, train.distance_to_go, train.segment_progress, train.doors_left, "
    "train.doors_right, train.doors, train.hvac_status, train.pa_status, train.pea_state, "
    "train.clock).\n\n"
)
_PLAN_SKIP_PROPERTIES = {"opacity", "visible", "value", "enabled", "backgroundColor", "textColor",
                         "borderColor", "borderWidth", "cornerRadius", "normalColor",
                         "warningColor", "faultColor", "trackColor", "lineColor", "fillColor",
                         "handleRadius", "size", "sweep", "showInnerDial", "readout"}


def _plan_catalogue(registry) -> str:
    lines = []
    for purpose, names in PLAN_CATALOGUE:
        entries = []
        for name in names:
            definition = registry.get(name) if registry is not None else None
            if definition is None:
                continue
            props = [p for p in definition.properties if p not in _PLAN_SKIP_PROPERTIES][:9]
            entries.append(f"{name}({', '.join(props)})")
        if entries:
            lines.append(f"- {purpose}: " + "; ".join(entries))
    return "\n".join(lines)


def _plan_brand(brand: Optional[dict]) -> str:
    """What the brand contributes to the prompt: its logos and accent.

    The logos the designer dropped and the accent it set are the only
    personalisation the generator carries, so the model is told to use
    exactly those: the logos as header Image widgets, the accent as the one
    brand colour every other colour falls back to.
    """
    if not brand:
        return ""
    logos = brand.get("logos") or []
    accent = (brand.get("accent") or "").strip()
    lines = []
    if logos:
        lines.append("Brand: use these logos as header Image widgets (at most two), "
                     "each placed left or right: " + ", ".join(logos) + ".")
    if accent:
        lines.append("Brand: its accent is " + accent + ". The title, the header "
                     "separators and the primary button use it; every other element "
                     "stays neutral.")
    if not lines:
        return ""
    return "You are building this screen to a brand.\n" + " ".join(lines) + "\n\n"


# Reference mode (a picture is attached): the widgets a reproduction is built
# from, by what the picture shows. Each is quoted with its properties and,
# apart, the colour properties it declares, which this mode lets the model
# fill with the picture's colours.
REFERENCE_CATALOGUE = (
    ("status strip", ("ShTelltale", "ShStatDot", "ShDataField", "Text")),
    ("gear selector", ("ShGearIndicator",)),
    ("speed", ("ShSpeedArc",)),
    ("round dials", ("ShClusterGauge", "ShGauge", "ShEngineGauge")),
    ("heading and attitude", ("ShCompass", "ShAttitude")),
    ("tyres", ("ShVehicleStatus",)),
    ("bars and levels", ("ShEngineBar", "ShSegmentBar", "ShAutoLevel", "ShTape")),
    ("readouts", ("ShDataField", "ShValueTile", "ShTripInfo", "ShNumDisplay")),
    ("pictures", ("Image", "ShAnimatedImage")),
    ("trend, alarms, controls", ("ShTrendChart", "ShAlarmTable", "ShButton", "ShToggle")),
)
_REFERENCE_SKIP_PROPERTIES = {"opacity", "visible", "enabled", "handleRadius", "size",
                              "pixelsPerDegree", "smooth", "fillMode"}

# What sits in each region, as designer.layout.compiler.REGIONS defines them.
REFERENCE_REGION_GUIDE = {
    "top": "the status strip across the top (clock, connectivity, weather). Write it as the "
           "page's \"header\", never as a section",
    "rail": "a narrow column at the left edge (a gear selector, mode lamps)",
    "left": "the left column of the body (a speed dial, the dials beside the hero)",
    "center": "the middle of the body -- the hero: a picture of the machine, the main dial",
    "right": "a column of cards at the right edge (one card per titled block, top to bottom)",
    "bottom": "a row along the bottom, under left and center: every dial or bar in the lower "
              "part of the picture, below the speed and the hero, side by side -- a dial under "
              "the speed arc is \"bottom\", not \"left\"",
}


def _reference_catalogue(registry) -> str:
    lines = []
    for purpose, names in REFERENCE_CATALOGUE:
        entries = []
        for name in names:
            definition = registry.get(name) if registry is not None else None
            if definition is None:
                continue
            colours = tuple(definition.color_properties)
            props = [p for p in definition.properties
                     if p not in _REFERENCE_SKIP_PROPERTIES and p not in colours][:11]
            entry = f"{name}({', '.join(props)}"
            if colours:
                entry += "; colours: " + ", ".join(colours)
            entries.append(entry + ")")
        if entries:
            lines.append(f"- {purpose}: " + "; ".join(entries))
    return "\n".join(lines)


def _reference_regions() -> str:
    try:
        from designer.layout.compiler import REGIONS
    except Exception:
        REGIONS = tuple(REFERENCE_REGION_GUIDE)
    return "\n".join(f"- \"{region}\": {REFERENCE_REGION_GUIDE.get(region, region)}."
                     for region in REGIONS)


def build_reference_plan_prompt(registry: Optional[WidgetRegistry] = None,
                                screen_width: int = 1280, screen_height: int = 800,
                                brief: str = "", brand: Optional[dict] = None) -> str:
    """System prompt for a plan that reproduces an attached picture.

    The plain plan prompt keeps the model to a title and a few generic cards,
    which is how a reference picture used to come back as a card grid: here
    the model inventories the picture's blocks, gives each a section with the
    region it sits in (compiler.REGIONS) and the widget that shows it, and
    keeps the picture's colours on the widgets' colour properties. Geometry
    still belongs to the layout compiler.
    """
    registry = registry or default_registry()
    try:
        types = sorted(d.type for d in registry.definitions())
    except Exception:
        types = sorted(set(_AI_TYPE_ALIASES.values()))
    try:
        from designer.layout.intake import kit_icons
        icons = ", ".join(sorted(kit_icons()))
    except Exception:
        icons = ""
    picture = "Image"
    if registry.get("ShAnimatedImage") is not None:
        picture = "Image (or ShAnimatedImage for a moving picture)"
    prompt = (
        "You are an expert HMI designer for embedded touch panels built with the EmbeddedDisplay "
        f"Studio widget set. The target screen is {screen_width}x{screen_height} px.\n\n"
        "REFERENCE MODE: the user attached a picture of the screen they want. Reproduce that "
        "picture: the same blocks in the same places, the same kinds of widgets, the same "
        "labels, sample values and colours. Do not fall back to a generic title-and-card-grid "
        "dashboard, and do not drop blocks to keep the page short.\n\n"
        "You decide WHAT each block shows and WHERE in the picture it sits (its region); the "
        "Studio's layout compiler turns the regions into the layout. Do not write x, y, width, "
        "height or font sizes.\n\n"
        "Step 1 -- inventory. Look at the picture region by region (the top strip, the rail at "
        "the left edge, the left column, the middle, the right column, the bottom row) and "
        "list every visual block in it: every dial, arc, bar group, card, picture, selector "
        "and readout, and in the top strip every icon, the clock, the weather, check marks and "
        "any name badge. Do this silently or in a few short lines before the JSON.\n"
        "Step 2 -- plan. Each block becomes one section of the page (10 sections at most), in "
        "reading order within its region (top to bottom, then left to right). Never merge two "
        "blocks into one section and never leave one out; a titled card in the picture is one "
        "section with that title, and it holds one widget for EVERY instrument drawn in it (a "
        "card with a compass and a pitch/roll scale is a ShCompass and a ShAttitude).\n\n"
        "Regions -- every section carries \"region\", one of:\n" + _reference_regions() + "\n"
        "A section may also carry \"accent\": that block's main colour sampled from the picture, "
        "as hex (\"#f97316\").\n\n"
        "The top strip is the page \"header\" (8 items at most, in the picture's order); it "
        "takes everything around the clock, a name badge hanging under it included:\n"
        "- connectivity and status icons (LTE, GPS, WiFi, Bluetooth, a lock) -> ShTelltale with "
        "an \"icon\" from the icon list below, \"label\" the word beside it, \"lit\": true, and "
        "\"side\": \"left\";\n"
        "- the time of day -> a Text with id \"clock\", \"text\" the time shown, bound to "
        "<area>.clock;\n"
        "- weather or outside temperature, and the driver or operator's name (a name badge, "
        "often under the clock) -> ShDataField with \"label\" what it is (\"Outside\", "
        "\"Driver\") and \"value\" what it shows (\"24°C\", \"J. Smith\");\n"
        "- a healthy check mark -> ShStatDot with \"state\": \"ok\".\n\n"
        "What the picture shows -> the widget for it:\n"
        "- a gear selector (P R N D L) -> ShGearIndicator, \"gears\": \"P,R,N,D,L\", \"gear\" the "
        "lit one, \"orientation\": \"vertical\" when the gears stand in a column; region \"rail\".\n"
        "- a speed arc or speedometer -> ShSpeedArc(value, maximumValue, unit) with outerColor "
        "and innerColor the arc's colours; \"showTarget\": false unless a target is shown.\n"
        "- an engine-speed dial reads in thousands: minimumValue 0, maximumValue the top of its "
        "scale in thousands (3 for a 3000 rpm diesel), redlineFrom in thousands, a running "
        "value such as 1.6, label \"x1000\"; never a raw 0..5000 scale under an x1000 label. "
        "A dial's caption is what it measures (\"RPM\", \"Payload\"), never decorative text "
        "printed in the picture.\n"
        "- words printed on or beside an instrument (its name, \"x1000\", \"7350 t max\", a "
        "unit) go into that widget's own caption, label, unit or title properties, never into "
        "separate Text widgets; leave out taglines and decoration (\"Active level telemetry "
        "arcs\"). A section holds instruments, not their labels.\n"
        "- round dials (RPM, payload, load, pressure) -> one ShClusterGauge each (caption, label, "
        "minimumValue, maximumValue, majorStep, redlineFrom), \"accentColor\" the dial's colour; "
        "one section per dial.\n"
        "- a compass or heading (N E S W) -> ShCompass(heading), never a ShClusterGauge.\n"
        "- pitch and roll, incline, tilt drawn as a scale, a horizon or a level -> "
        "ShAttitude(pitch, roll); a ShDataField pair (Pitch, Roll) only for bare numbers, such "
        "as readouts drawn over the picture of the machine.\n"
        "- tyre pressures -> ShVehicleStatus(frontLeft, frontRight, rearLeft, rearRight, unit, "
        "warnBelow). Count the tyres drawn: six tyres (three rows of two) MUST set \"axles\": 3 "
        "and give midLeft and midRight too; four tyres leave axles out.\n"
        "- temperature or health bars -> one ShEngineBar per bar (\"orientation\": "
        "\"horizontal\", label, units, value, maximumValue, cautionValue, warningValue), "
        "\"barColor\" the bar's colour.\n"
        "- a fuel or battery bar -> ShSegmentBar(label, value, showPercent) with \"barColor\", "
        "or ShAutoLevel.\n"
        "- warning or status lamps -> ShTelltale(icon, color, label) or ShStatDot(state).\n"
        f"- a picture in the reference (the machine, a vehicle, an illustration) also carries "
        f"\"crop\": [left, top, right, bottom], where it sits in the reference image on a "
        f"0..1000 scale of the image's width and height, tight around the picture: the Studio "
        f"cuts that part of the reference out and shows it in the {picture}.\n"
        f"- a picture of the machine (a truck, a pump, a vehicle) -> {picture} with "
        "\"source\": \"\" and its \"crop\" (the Studio fills the picture from the crop), in a "
        "\"center\" section with role "
        "\"hero\"; live readouts drawn over the picture go in the same section. A drawing, "
        "render or photo of the machine is always a block of its own: never leave it out.\n"
        "- text readouts (a number with a label) -> ShDataField(label, value, units) or "
        "ShValueTile(title, value, unit).\n"
        "- a trend line -> ShTrendChart; an alarm list -> ShAlarmTable; buttons -> ShButton.\n\n"
        "Colours ARE part of the reproduction in this mode: keep the picture's colours. Write "
        "them as hex (\"#3b82f6\") on the colour properties each widget declares (after "
        "\"colours:\" in the list below, and accentColor/barColor where named above) and as the "
        "section's \"accent\". Leave a colour out where the picture shows none.\n\n"
        "Reply with ONE fenced ```json block and nothing after it:\n"
        '{"name": "<short name>", "section": {"index": 1, "complete": true, "label": "", "next": ""}, '
        '"pages": [{"id": "main", "name": "Main", "title": "<screen title, 2-5 words>", '
        '"header": [{"type": "ShTelltale", "id": "wifi", "side": "left", "properties": '
        '{"icon": "wifi", "label": "WiFi", "lit": true}}, {"type": "Text", "id": "clock", '
        '"properties": {"text": "<the time shown>"}, "bindings": {"text": {"tag": "<area>.clock"}}}, '
        '{"type": "ShDataField", "id": "driver", "properties": {"label": "Driver", "value": '
        '"<the name on the badge>"}}, <the rest of the top strip: weather, the status check>], '
        '"sections": [{"title": "Gear", "role": "status", "region": "rail", "widgets": ['
        '{"type": "ShGearIndicator", "id": "gear", "properties": {"gears": "P,R,N,D", "gear": "D", '
        '"orientation": "vertical"}, "bindings": {"gear": {"tag": "<area>.gear"}}}]}, '
        '{"title": "", "role": "hero", "region": "left", "accent": "#<hex>", "widgets": ['
        '{"type": "ShSpeedArc", "id": "speed", "properties": {"value": <shown>, "maximumValue": '
        '<full scale>, "unit": "km/h", "outerColor": "#<hex>", "innerColor": "#<hex>"}, '
        '"bindings": {"value": {"tag": "<area>.speed", "unit": "km/h"}}}]}, '
        '<one section per remaining block of the picture, each with its "region">]}]}\n'
        "The <...> are placeholders: fill every one from the picture and the brief, with real "
        "JSON numbers. <area> is one lowercase word naming the machine (truck, loader, pump) and "
        "every tag starts with it (truck.clock, truck.speed); never write \"<area>\" or "
        "\"area\" itself.\n\n"
        "Section roles: hero (the picture of the machine, the main dial), instruments (dials, "
        "arcs, bars), readings (tiles and readouts), status (lamps), trend, alarms, controls. "
        "A section's \"title\" is the label the picture gives the block (\"Incline\", "
        "\"Tires\", \"Fuel\"); \"\" when the picture shows none. A section may carry \"size\": "
        "\"compact\", \"normal\" or \"large\" when the block is clearly small or large in the "
        "picture.\n\n"
        "Widgets by what they show, with the properties they take:\n"
        + _reference_catalogue(registry) + "\n"
        + _plan_brand(brand) +
        "Other allowed types: " + ", ".join(types) + ".\n\n"
        "Every widget states what it is: the label the picture shows (Title-case, at most 18 "
        "characters) in the property its type uses for it, and its unit. Ranges are in "
        "engineering units with warning and critical thresholds where the process has them.\n"
        "Every reading carries the value the picture shows as its sample \"value\" (a gauge "
        "reading 342 t has \"value\": 342); a healthy lamp gets \"state\": \"ok\".\n"
        "Bindings: live values bind to lowercase dotted tags named for the machine "
        "(truck.speed, truck.gear, truck.tire_fl, truck.coolant_c); a binding may carry "
        "\"unit\", \"warning\" and \"critical\" (\"> 80\", \"< 10\").\n"
        "Actions, keyed by the widget's signal: ShButton clicked; ShToggle toggled. Kinds: "
        "{\"kind\": \"write\", \"tag\": \"do.x\", \"value\": true}, "
        "{\"kind\": \"navigate\", \"page\": \"<page id>\"}.\n"
    )
    if icons:
        prompt += ("Icons (ShTelltale, ShAutoReadout, ShIconTile) must be one of: " + icons
                   + ". Pick the nearest one (LTE -> wifi or link, GPS -> road, a lock -> lock).\n")
    prompt += ("Ids are unique camelCase (coolantTemp, never coolant_temp). Return the whole "
               "design in this one reply with section.complete=true.")
    return prompt


def build_plan_prompt(registry: Optional[WidgetRegistry] = None,
                      screen_width: int = 1280, screen_height: int = 800,
                      brief: str = "", brand: Optional[dict] = None,
                      reference: bool = False) -> str:
    """System prompt for planned screens: content and structure, no geometry.

    The model says what the screen holds -- a title, and sections with a role
    and the widgets in them -- and designer.layout.compiler builds the layout
    (header, titled cards, bands, spacing, type scale) deterministically.
    Geometry was the part of the old payload the model was worst at and the
    longest part of its reply; leaving it out makes the reply shorter, the
    JSON less likely to break, and the result composed every time.

    ``reference``: the run carries a picture of the screen wanted, and the
    prompt asks for a reproduction of it (build_reference_plan_prompt).
    """
    if reference:
        return build_reference_plan_prompt(registry, screen_width, screen_height,
                                           brief=brief, brand=brand)
    registry = registry or default_registry()
    try:
        types = sorted(d.type for d in registry.definitions())
    except Exception:
        types = sorted(set(_AI_TYPE_ALIASES.values()))
    budget = page_budget(screen_width, screen_height)
    try:
        from designer.layout.intake import kit_icons
        icons = ", ".join(sorted(kit_icons()))
    except Exception:
        icons = ""
    prompt = (
        "You are an expert HMI designer for embedded touch panels built with the EmbeddedDisplay "
        f"Studio widget set. The target screen is {screen_width}x{screen_height} px.\n\n"
        "You decide WHAT the screen shows and how it is grouped; the Studio's layout compiler "
        "decides WHERE. Never write x, y, width, height or any geometry, colours or font sizes: "
        "the compiler draws a header with the title, one titled card per section, and lays out "
        "each card from its widgets on the panel's grid.\n\n"
        "Reply with ONE fenced ```json block and nothing after it:\n"
        '{"name": "<short name>", "section": {"index": 1, "complete": true, "label": "", "next": ""}, '
        '"pages": [{"id": "main", "name": "Main", "title": "<screen title, 2-5 words>", '
        '"header": [<optional: up to 4 status lamps or navigate buttons for the header, and '
        'a logo for each image file the brief names (two at most): {"type": "Image", "id": '
        '"<camelCaseId>", "side": "left" or "right", "properties": {"source": "assets/<file>"}}>], '
        '"sections": [{"title": "<card title, 1-3 words>", "role": "hero", "widgets": ['
        '{"type": "ShClusterGauge", "id": "<camelCaseId>", '
        '"properties": {"caption": "<what it measures>", "minimumValue": 0, '
        '"maximumValue": <full scale>, "majorStep": <scale step>, "redlineFrom": <limit>}, '
        '"bindings": {"value": {"tag": "<area.signal>", "unit": "<unit>", "warning": "> <n>", '
        '"critical": "> <n>"}}}]}, '
        '{"title": "<card title>", "role": "controls", "widgets": ['
        '{"type": "ShButton", "id": "<camelCaseId>", "properties": {"text": "<Verb>"}, '
        '"actions": {"clicked": {"kind": "write", "tag": "do.<signal>", "value": true}}}]}, '
        '<more sections: instruments, readings, trend, alarms, status ...>]}]}\n'
        "The <...> are placeholders: fill every one from the brief, with real JSON numbers.\n\n"
        "Section roles (use each at most once per page unless the brief needs two of a kind):\n"
        "- hero: exactly one per page, holding ONE widget -- the value the brief is really about, "
        "usually a big dial (ShClusterGauge) or a trend. It gets the largest card.\n"
        "- instruments: 2-4 related dials or bars (e.g. \"Pressures\": suction and discharge).\n"
        "- readings: 2-6 value tiles or readouts that share a topic.\n"
        "- trend: one ShTrendChart. alarms: one ShAlarmTable (bind alarms to tag \"*\").\n"
        "- status: lamps (ShStatDot with a \"label\" property, ShAnnunciator, ShTelltale).\n"
        "- controls: buttons, toggles, sliders, selects that act on the process.\n"
        "Size: a section or a widget may carry \"size\": \"compact\", \"normal\" or \"large\" "
        "when the brief implies it (a compact status strip, a large hero, small secondary "
        "dials); the compiler scales widgets down on its own when the screen is crowded.\n"
        "Group by meaning, not by widget type; name every card for what it shows "
        "(\"Discharge\", \"Motor\", \"Tank\"), never \"Section 1\" or \"Widgets\". "
        f"A page has 3-6 sections and about {budget} widgets at most; when the brief asks for more, "
        "add pages (one per system) and put a navigate ShButton for each in the main page's header.\n\n"
+ (RAIL_PLAN_GUIDE if is_rail_brief(brief) else "") +
         "Widgets by purpose, with the properties they take:\n" + _plan_catalogue(registry) + "\n"
         + _plan_brand(brand) +
        "Other allowed types: " + ", ".join(types) + ".\n\n"
        "Every widget states what it is: a short Title-case label (at most 18 characters) in the "
        "property its type uses for it, and its unit. Ranges are in the tag's engineering units "
        "(0..16 bar, 0..3000 rpm), never 0..1, with warning and critical thresholds where the "
        "process has them. Buttons say what they do in one or two words (\"Start\", \"Stop\", "
        "\"Reset\", \"E-Stop\").\n"
        "Every reading also carries a realistic sample \"value\" in its properties: what the "
        "screen shows in the designer and before live data arrives, a plausible running value "
        "inside its range (a pump at 72 % load, a train at 64 km/h), never 0 and never the "
        "maximum. A reading that is a name gets the name itself (\"value\": \"Indiranagar\"); a "
        "status lamp that is healthy gets \"state\": \"ok\". Add a logo only for an image file "
        "the brief names.\n"
        "Bindings: live values bind to PLC/telemetry tags, lowercase dotted names (ai.pot, "
        "di.estop, do.relay1, mb.line_speed); a binding may carry \"unit\", \"warning\" and "
        "\"critical\" (\"> 80\", \"< 10\"). Bind ShTrendChart.data to the tag it plots.\n"
        "Actions, keyed by the widget's signal: ShButton clicked; ShToggle toggled; "
        "ShSlider/ShNumInput valueChanged; ShSelect activated. Kinds: "
        "{\"kind\": \"write\", \"tag\": \"do.x\", \"value\": true}, "
        "{\"kind\": \"pulse\", \"tag\": \"do.x\", \"ms\": 250}, "
        "{\"kind\": \"navigate\", \"page\": \"<page id>\"}. Every start/stop/reset button has one.\n"
    )
    if icons:
        prompt += "Icons (ShTelltale, ShAutoReadout, ShIconTile) must be one of: " + icons + ".\n"
    prompt += ("Ids are unique camelCase across all pages. Before the JSON block write at most one "
               "sentence. Return the whole design in this one reply with section.complete=true.")
    return prompt


def _fold_stray_sections(pages_data: list) -> list:
    """Pages, with any section that landed among them put back in its page.

    One misplaced bracket in a long reply (bindings written beside a
    section's widgets instead of inside them) closes the page early, and every
    later section then parses as a page with no sections -- and was lost.
    """
    pages = []
    for entry in pages_data:
        if not isinstance(entry, dict):
            continue
        spilled = entry.get("__spill__")
        if isinstance(spilled, list):
            # A section whose opening brace became `],` landed in the page's
            # own keys (see designer.layout.intake._pairs): put it back.
            entry = {k: v for k, v in entry.items() if k != "__spill__"}
            extra = [d for d in spilled if isinstance(d, dict) and ("role" in d or "widgets" in d)]
            if extra:
                entry["sections"] = list(entry.get("sections") or []) + extra
        stray = "sections" not in entry and ("role" in entry or (
            pages and "widgets" in entry and "id" not in entry))
        if stray and pages:
            pages[-1] = dict(pages[-1])
            pages[-1]["sections"] = list(pages[-1].get("sections") or []) + [entry]
            continue
        pages.append(entry)
    return pages


_RANGE_KEYS = (("minimum", "maximum"), ("minimumValue", "maximumValue"), ("minValue", "maxValue"))


def _plausible_samples(widgets, registry) -> None:
    """A dial with no sample reading of its own shows one inside its range.

    The kit's defaults (a cluster gauge at 4.2 on a 0..100 km/h dial) read
    as a broken screen in the designer and in every preview until live data
    arrives; a reading two thirds up its own scale reads as a running one.
    """
    for widget in widgets:
        definition = registry.get(widget.type) if registry is not None else None
        if definition is not None and "value" in definition.properties:
            keys = next(((lo, hi) for lo, hi in _RANGE_KEYS
                         if lo in definition.properties and hi in definition.properties), None)
            if keys:
                try:
                    lo = float(widget.properties.get(keys[0], definition.defaults.get(keys[0])))
                    hi = float(widget.properties.get(keys[1], definition.defaults.get(keys[1])))
                    value = widget.properties.get("value")
                    stale = value is None or value == definition.defaults.get("value") \
                        or not lo <= float(value) <= hi
                except (TypeError, ValueError):
                    lo = hi = 0.0
                    stale = False
                if stale and hi > lo:
                    sample = lo + 0.62 * (hi - lo)
                    widget.properties["value"] = round(sample) if hi - lo >= 20 else round(sample, 1)
        _plausible_samples(widget.children, registry)


def _names_on_text_tiles(widgets, registry) -> None:
    """A reading whose value is a name ("Indiranagar") on a numeric readout
    draws as 0; a value tile shows text, so the reading moves onto one with
    its label, unit and binding."""
    for widget in widgets:
        definition = registry.get(widget.type) if registry is not None else None
        value = widget.properties.get("value")
        if definition is not None and isinstance(definition.defaults.get("value"), (int, float)) \
                and isinstance(value, str) and value.strip():
            try:
                float(value)
            except ValueError:
                label = next((widget.properties.get(k) for k in ("label", "title", "caption")
                              if widget.properties.get(k)), "")
                kept = {k: v for k, v in widget.properties.items() if k.startswith("_")}
                widget.type = "ShValueTile"
                widget.properties = {**kept, "title": label or "Value", "value": value.strip(),
                                     "unit": widget.properties.get("unit", ""), "state": "ok"}
        _names_on_text_tiles(widget.children, registry)


def _named_logos_only(header, brief: str) -> list:
    """Header images whose file the request names; an invented logo has no
    file behind it and draws as an empty plate."""
    words = (brief or "").lower()
    if not words:
        return header
    kept = []
    for widget in header:
        source = str(widget.properties.get("source") or "").replace("\\", "/")
        if widget.type == "Image" and source.rsplit("/", 1)[-1].lower() not in words:
            continue
        kept.append(widget)
    return kept


def _merge_small_plan(pages_data: list, width: int, height: int) -> list:
    """One page when the whole plan fits on one.

    A model told it may add pages sometimes gives every section a page of
    its own: seven screens of one card each, linked by buttons. When the
    widgets fit the screen's budget they belong together, and the navigate
    buttons between the merged pages go with them.
    """
    pages = _fold_stray_sections(pages_data)
    if len(pages) < 2:
        return pages

    def count(page):
        return sum(len(s.get("widgets") or []) for s in page.get("sections") or []
                   if isinstance(s, dict))

    if sum(count(p) for p in pages) > page_budget(width, height):
        return pages
    merged_ids = {str(p.get("id") or "") for p in pages[1:]}

    def keeps(widget):
        actions = widget.get("actions") if isinstance(widget, dict) else None
        if not isinstance(actions, dict):
            return True
        for action in actions.values():
            if isinstance(action, dict) and action.get("kind") == "navigate" \
                    and str(action.get("page") or "") in merged_ids:
                return False
        return True

    first = dict(pages[0])
    sections = []
    for page in pages:
        for section in page.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section = dict(section)
            section["widgets"] = [w for w in section.get("widgets") or [] if keeps(w)]
            if section["widgets"]:
                sections.append(section)
    first["sections"] = sections
    header = [w for p in pages for w in (p.get("header") or []) if keeps(w)]
    # Up to four lamps or buttons, and logos beside them that do not count
    # against them: a fourth lamp must not push the customer's logo out.
    # Two logos at most: the operator's and the integrator's.
    logos = [w for w in header if isinstance(w, dict) and str(w.get("type", "")).endswith("Image")]
    # A cab display's header also carries the train's fields and a clock.
    fields = [w for w in header if isinstance(w, dict) and w not in logos
              and str(w.get("type", "")) in ("ShDataField", "Text", "ShValueTile")]
    rest = [w for w in header if w not in logos and w not in fields]
    first["header"] = rest[:4] + fields[:5] + logos[:2]
    return [first]


def _geometry_number(value, default):
    """A geometry value from model output as a number: 12, 12.5, "12",
    "12px". Anything else (null, "auto", NaN) takes the default -- layout
    does arithmetic on these, and one null used to fail the whole design."""
    if isinstance(value, str):
        value = value.strip().lower().removesuffix("px").strip()
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return int(number) if number.is_integer() else number


class AIDesignGenerator:
    """Parse AI output (QML code or JSON design spec) into DesignerProject."""

    def __init__(self, registry: Optional[WidgetRegistry] = None):
        # Not an empty WidgetRegistry(): with no types in it every per-type
        # safeguard below (unknown properties, bindings, actions, layout
        # rules) silently does nothing.
        self.registry = registry or default_registry()
        self.progress = GeneratorProgress()
        # The studio's brand (logos, accent) the generator carries across to
        # what it produces, over the kit's own colours.
        self.brand = {}
        # Every parsed section goes through designer.layout.polish before it is
        # returned, so what reaches the canvas is composed, not a draft.
        # False (tests, a caller that polishes itself) returns it raw.
        self.polish_enabled = True
        self.last_polish = None      # the PolishReport of the last generate()
        self.last_fit_notes = []     # what compose() moved to other pages, and why
        # The brief the section was asked for, when the caller knows it: it
        # picks the composition archetype. Empty is fine -- the widget count
        # then decides.
        self.brief = ""
        self.renderer = None         # a NativeRenderer for the critic's pixel axes
        # How a parsed design is laid out. "auto": a planned payload (pages
        # with sections, see build_plan_prompt) is compiled by
        # designer.layout.compiler and a geometry payload is polished as
        # before; "compile" compiles both; "polish" polishes both.
        self.layout_mode = "auto"
        self.last_compile = []       # CompileReport per page of the last compose()

    def generate(self, ai_output: str, screen_width: int = 1280, screen_height: int = 800) -> Optional[DesignerProject]:
        """Generate a DesignerProject from AI output.

        Tries three parsing strategies in order:
        1. JSON design payload ({"pages": [...]})
        2. Markdown-wrapped QML code blocks
        3. Plain QML code

        Returns DesignerProject or None on failure. Unless `polish_enabled`
        is False the parsed design is composed by designer.layout.polish
        before it is returned, and the PolishReport is kept in `last_polish`.
        """
        project = self._parse_output(ai_output, screen_width, screen_height)
        if self.brand:
            project.brand = dict(self.brand)
        self.last_polish = None
        if project is None or not self.polish_enabled:
            return project
        return self.compose(project)

    def compose(self, project):
        """Lay out every page of `project` in place; returns it.

        Also run on a sectioned design after each section is merged: every
        section is composed as if it had the screen to itself, so merging
        them put each section's hero in the same slot -- an RPM gauge, a
        coolant gauge and a status lamp stacked in the middle of the panel.
        """
        self.last_polish = None
        self.last_fit_notes = []
        self.last_compile = []
        if project is None or not self.polish_enabled:
            return project
        if self._should_compile(project):
            return self._compile(project)
        try:
            from designer.layout.fit import compose_project
            from designer.layout.polish import polish
            self.progress.progress.emit("Composing the design...")
            # Fit first (pages for what the screen cannot hold), then polish,
            # then move whatever still overlaps: see designer/layout/fit.py.
            self.last_polish, self.last_fit_notes = compose_project(
                project, self.registry, polish,
                brief=self.brief or project.name, renderer=self.renderer)
            # A model reuses an id for a new widget; unique ids are a
            # precondition of a design that validates.
            from designer.model.project import ensure_unique_ids
            self.last_fit_notes += ensure_unique_ids(project)
        except Exception as exc:
            # A design in a draft's clothes beats no design at all: whatever
            # the layout pipeline did, the model's work reaches the canvas.
            logger.warning("Polish failed, returning the unpolished design: %s", exc)
            self.last_polish = None
        return project

    def _should_compile(self, project) -> bool:
        if self.layout_mode == "compile":
            return True
        if self.layout_mode == "polish":
            return False
        from designer.layout.compiler import is_planned
        return any(is_planned(page) for page in project.pages)

    def _compile(self, project):
        """Lay out every page with designer.layout.compiler; returns it."""
        try:
            from designer.layout.compiler import compile_page
            from designer.layout.critic import critique
            from designer.layout.polish import PolishReport
            from designer.model.project import ensure_unique_ids
            self.progress.progress.emit("Compiling the layout...")
            # The first page is the one the run log reports on, as polish does.
            before = critique(project, project.pages[0], self.registry) if project.pages else None
            for page in project.pages:
                report = compile_page(project, page, self.registry)
                self.last_compile.append(report)
                self.last_fit_notes += [n for n in report.notes if "dropped" in n or "moved" in n]
            # A cab display's readings name each other (the next station, the
            # line, the distance to go): they are sampled from one moment of
            # the bench's journey so the canvas never contradicts itself. A
            # card screen keeps the compiler's running readings -- the bench
            # flies a flight under tags it does not know, and a pump's flow
            # read off a climb is no better a sample than two thirds up its
            # own scale.
            try:
                from designer.layout.samples import coherent_samples, runs_a_journey
                if runs_a_journey(project):
                    n = coherent_samples(project)
                    if n:
                        self.last_fit_notes.append(
                            f"samples: {n} reading(s) set from one moment of the journey")
            except Exception as exc:
                logger.warning("Coherent samples skipped: %s", exc)
            self.last_fit_notes += ensure_unique_ids(project)
            if before is not None:
                after = critique(project, project.pages[0], self.registry)
                self.last_polish = PolishReport(
                    before=before, after=after,
                    archetype=f"compiled {self.last_compile[0].layout}".strip())
        except Exception as exc:
            logger.warning("Layout compile failed, falling back to polish: %s", exc)
            self.layout_mode, mode = "polish", self.layout_mode
            try:
                return self.compose(project)
            finally:
                self.layout_mode = mode
        return project

    def _parse_output(self, ai_output: str, screen_width: int = 1280,
                      screen_height: int = 800) -> Optional[DesignerProject]:
        """Everything generate() does before the design is composed."""
        self.progress.progress.emit("Parsing AI output...")

        # Strategy 1: JSON design payload -- a fenced ```json block first (that
        # is what the system prompt asks for), then any bare {"pages": …}.
        for candidate in self._json_candidates(ai_output):
            # Lenient: one missing quote in a long payload used to cost the
            # whole design (designer/layout/intake.py).
            try:
                design = loads_lenient(candidate)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.debug("JSON parsing failed: %s", exc)
                continue
            if isinstance(design, dict) and ("pages" in design or "widgets" in design):
                project = self._from_json_design(design, screen_width, screen_height)
                if candidate == self._unterminated_json(ai_output):
                    # Closed by the lenient loader, not by the model: the
                    # reply was cut off, and the run should ask for the rest.
                    project._truncated = True
                return project

        # Strategy 2: QML code blocks
        qml_block_match = QML_BLOCK_RE.search(ai_output)
        if qml_block_match:
            qml_code = qml_block_match.group(1)
            widgets = self._parse_qml_to_widgets(qml_code)
            if widgets:
                return self._build_project(widgets, "AI Design", screen_width, screen_height)

        # Strategy 3: Try to extract a JSON array of widget descriptions from the text
        try:
            widgets = self._parse_widget_descriptions(ai_output)
            if widgets:
                return self._build_project(widgets, "AI Design", screen_width, screen_height)
        except Exception as exc:
            logger.debug("Widget description parsing failed: %s", exc)

        # Strategy 4: Plain QML code (no markdown blocks)
        widgets = self._parse_qml_to_widgets(ai_output)
        if widgets:
            return self._build_project(widgets, "AI Design", screen_width, screen_height)

        # Strategy 5: Salvage partial widgets from truncated output.
        # When the model hits the token limit the JSON block is incomplete,
        # but every widget type mentioned in the text (in the reasoning block,
        # or in the partial JSON) tells us what the model was trying to build.
        try:
            partial = self._extract_partial_widgets(ai_output, screen_width, screen_height)
            if partial:
                return partial
        except Exception:
            pass

        self.progress.error.emit("Unable to parse AI output. Try rephrasing the prompt.")
        return None

    @staticmethod
    def _json_candidates(ai_output: str) -> list:
        """Substrings of the output that might be a design payload, best first."""
        candidates = [m.group(1).strip() for m in JSON_BLOCK_RE.finditer(ai_output)]
        bare = JSON_DESIGN_RE.search(ai_output)
        if bare:
            candidates.append(bare.group())
        # A reply cut off by max_tokens has no closing fence; the lenient
        # loader can still close what was written.
        opened = AIDesignGenerator._unterminated_json(ai_output)
        if opened:
            candidates.append(opened)
        return candidates

    @staticmethod
    def _unterminated_json(ai_output: str) -> str:
        """The payload after a ```json fence that never closes, or ''."""
        opened = re.search(r"```json\s*(\{[\s\S]*)$", ai_output)
        if opened and "```" not in opened.group(1):
            return opened.group(1).strip()
        return ""

    def _from_json_design(self, design: dict, width: int, height: int) -> DesignerProject:
        """Convert a JSON design payload (pages, widgets) to DesignerProject."""
        widgets = []
        pages_data = design.get("pages", [])
        if isinstance(pages_data, list) and any(isinstance(p, dict) and p.get("sections")
                                                for p in pages_data):
            project = self._from_plan(design, width, height)
            self._read_section_meta(project, design)
            return project
        if pages_data:
            for page_data in pages_data:
                page_widgets = page_data.get("widgets", [])
                widgets.extend(self._convert_widgets(page_widgets))
        else:
            widgets = self._convert_widgets(design.get("widgets", []))

        project = self._build_project(widgets, design.get("name", "AI Design"), width, height)
        self._read_section_meta(project, design)
        return project

    def _read_section_meta(self, project, design: dict) -> None:
        section = design.get("section") or {}
        if isinstance(section, dict):
            try:
                project._section_index = max(1, int(section.get("index", 1) or 1))
            except (TypeError, ValueError):
                project._section_index = 1
            complete = section.get("complete", True)
            if isinstance(complete, str):
                complete = complete.strip().lower() not in ("false", "no", "0", "pending")
            project._section_complete = bool(complete)
            project._section_label = str(section.get("label", "")).strip()
            project._next_section = str(section.get("next", section.get("nextSection", ""))).strip()

    def _from_plan(self, design: dict, width: int, height: int) -> DesignerProject:
        """A planned payload: real pages, each widget marked with its section.

        The marks (compiler.SECTION_MARK) are what compose() compiles from, so
        they survive a sectioned run's merge and a later "Tidy up".
        """
        from designer.layout.compiler import REGION_MARK, SECTION_ID_MARK, SECTION_MARK, sections_from_plan
        from designer.model import DesignerScreen
        pages, taken = [], set()
        for index, page_data in enumerate(_merge_small_plan(design.get("pages") or [], width, height)):
            if not isinstance(page_data, dict):
                continue
            title, sections, header = sections_from_plan(page_data, self._convert_widgets)
            header = _named_logos_only(header, self.brief)
            for section in sections:
                _names_on_text_tiles(section.widgets, self.registry)
                _plausible_samples(section.widgets, self.registry)
            loose = self._convert_widgets([w for w in page_data.get("widgets") or []
                                           if isinstance(w, dict)])
            widgets = []
            if title:
                widgets.append(DesignerWidget(type="Text", id="screenTitle", geometry={},
                                              properties={"text": title, SECTION_MARK: "|title"}))
            for widget in header:
                widget.properties[SECTION_MARK] = "|header"
                widgets.append(widget)
            for number, section in enumerate(sections, 1):
                for widget in section.widgets:
                    widget.properties[SECTION_MARK] = f"{section.title}|{section.role}"
                    if section.region:
                        widget.properties[REGION_MARK] = section.region
                        widget.properties[SECTION_ID_MARK] = number
                    widgets.append(widget)
            widgets.extend(loose)
            page_id = str(page_data.get("id") or ("main" if index == 0 else f"page{index + 1}"))
            page_id = re.sub(r"[^A-Za-z0-9_]", "_", page_id) or f"page{index + 1}"
            while page_id in taken:
                page_id += "_"
            taken.add(page_id)
            pages.append(DesignerPage(id=page_id, name=str(page_data.get("name") or title or page_id),
                                      widgets=widgets))
        if not pages:
            pages = [DesignerPage(id="main", name="Main", widgets=[])]
        project = DesignerProject(version=1, name=design.get("name", "AI Design"),
                                  screen=DesignerScreen(width=width, height=height), pages=pages)
        from designer.model.project import ensure_unique_ids
        ensure_unique_ids(project)
        return project

    def _convert_widgets(self, widget_list: list) -> list:
        """Convert a list of widget dicts to DesignerWidget objects."""
        result = []
        seen_ids: set = set()
        for i, wdata in enumerate(widget_list):
            # Model output: an entry that is not an object ("oops", null) is
            # dropped rather than failing the whole section.
            if not isinstance(wdata, dict):
                continue
            widget_type = wdata.get("type", "Rectangle")
            # Resolve aliases (e.g. "Button" -> "ShButton"), and a kit-style
            # name the kit does not have ("ShLamp") through its bare name.
            aliased = _AI_TYPE_ALIASES.get(widget_type, widget_type)
            if isinstance(widget_type, str) and not self.registry.get(aliased)                     and widget_type.startswith("Sh"):
                aliased = _AI_TYPE_ALIASES.get(widget_type[2:], aliased)
            # Check if aliased type exists in registry; fall back to Rectangle
            if aliased not in (_AI_TYPE_ALIASES.get(v, v) for v in _AI_TYPE_ALIASES.values()):
                if not self.registry.get(aliased):
                    # Double-check original type
                    if not self.registry.get(widget_type):
                        aliased = "Rectangle"
            geometry = wdata.get("geometry")
            if not isinstance(geometry, dict):
                geometry = {}
            x = _geometry_number(geometry.get("x"), i * 20 % 1000)
            y = _geometry_number(geometry.get("y"), i * 20 % 800)
            w = _geometry_number(geometry.get("width"), 140)
            h = _geometry_number(geometry.get("height"), 40)
            properties = dict(wdata.get("properties") or {})
            # A model invents properties freely ("active" on a status dot);
            # one unknown key makes the generated QML fail to load on the
            # panel. Keep only what the registry declares for this type.
            definition = self.registry.get(aliased)
            # Properties written beside "properties" rather than in it (a
            # planned widget's shorthands, or a model that dropped the
            # "properties": { wrapper): scalars only, the filter below decides.
            for key, value in wdata.items():
                if key in _WIDGET_KEYS or key in properties or isinstance(value, (dict, list)):
                    continue
                properties[key] = value
            if definition is not None and "label" not in definition.properties:
                # A lamp has no label of its own, but the words the model gave
                # it are what the compiler writes beside it.
                words = next((properties.get(k) for k in ("label", "text", "title")
                              if isinstance(properties.get(k), str) and properties.get(k).strip()), None)
                if words and aliased in ("ShStatDot",):
                    properties["_lampLabel"] = words.strip()
            if definition is not None and definition.properties:
                # The model spells a property the way another widget does
                # (minimumValue on an ShGauge, label on an ShValueTile); map
                # it onto this type's own spelling before the filter drops it.
                properties, _renamed = normalise_properties(definition, properties)
                properties = {k: v for k, v in properties.items()
                              if k in definition.properties or k == "_lampLabel"}
                properties = _coerce_choices(definition, properties)
            # Bindings are what the prompt asks for ("value" -> plc tag); keep
            # every one that has a tag, in the model's own DesignerBinding type.
            bindings = {}
            for prop, value in (wdata.get("bindings") or {}).items():
                try:
                    binding = DesignerBinding.from_data(value)
                except (ValueError, TypeError):
                    continue
                if binding.tag:
                    binding.tag = _coerce_tag(binding.tag)
                    prop = str(prop)
                    # A model binds the name it guesses ("data" on an alarm
                    # table, "value" on an annunciator). Where the widget
                    # takes exactly one bound property, that is what it meant.
                    if definition is not None:
                        declared = set(definition.properties) | set(definition.bindable_properties)
                        only = definition.bindable_properties
                        if prop not in declared and len(only) == 1 and only[0] not in bindings:
                            prop = only[0]
                    bindings[prop] = binding

            children = []
            for child_data in wdata.get("children", []):
                child = self._convert_widgets([child_data])[0] if child_data else None
                if child:
                    children.append(child)

            # Actions ride along in the model's own type; a malformed one is
            # dropped rather than failing the section, like a bad binding.
            actions = {}
            for signal, value in (wdata.get("actions") or {}).items():
                try:
                    action = DesignerAction.from_data(value)
                except (ValueError, TypeError):
                    continue
                # A signal the widget cannot emit ("clicked" on an ShAlert)
                # can never run the action, and validation then refused the
                # whole design at deploy.
                if definition is not None and str(signal) not in definition.action_signals:
                    continue
                if action.kind in ("write", "pulse", "navigate"):
                    if action.tag:
                        action.tag = _coerce_tag(action.tag)
                    actions[str(signal)] = action

            # Keep the model's own id when it is a legal QML id: stable ids
            # are what make "changed" (vs added/removed) meaningful between
            # two generations of the same screen.
            wid = str(wdata.get("id") or "")
            if not _QML_ID_RE.fullmatch(wid):
                wid = self._make_widget_id(aliased, i)
            base, n = wid, 2
            while wid in seen_ids:
                wid, n = f"{base}{n}", n + 1
            seen_ids.add(wid)
            result.append(DesignerWidget(
                type=aliased,
                id=wid,
                geometry={"x": x, "y": y, "width": w, "height": h},
                properties=properties,
                bindings=bindings,
                children=children,
                actions=actions,
            ))
        return result

    def _parse_qml_to_widgets(self, qml_code: str) -> list:
        """Extract widget definitions from QML code.

        This is a heuristic parser that looks for component instantiations
        with id, x, y, width, height, and property assignments.
        """
        widgets = []
        component_re = re.compile(
            r"(\w+)\s*{\s*"  # component type
            r"id:\s*(\w+)"  # id
        )
        
        # Find each component start, then match to its closing brace
        for match in component_re.finditer(qml_code):
            comp_type = match.group(1)
            widget_id = match.group(2)
            start = match.start()
            
            # Find the matching closing brace (handle nesting)
            brace_count = 0
            end = -1
            for i in range(start, len(qml_code)):
                if qml_code[i] == '{':
                    brace_count += 1
                elif qml_code[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i
                        break
            
            if end == -1:
                continue
                
            block = qml_code[start:end+1]
            
            # Extract geometry
            x_match = re.search(r"x:\s*(-?\d+)", block)
            y_match = re.search(r"y:\s*(-?\d+)", block)
            w_match = re.search(r"width:\s*(-?\d+)", block)
            h_match = re.search(r"height:\s*(-?\d+)", block)
            
            x = int(x_match.group(1)) if x_match else 0
            y = int(y_match.group(1)) if y_match else 0
            w = int(w_match.group(1)) if w_match else 140
            h = int(h_match.group(1)) if h_match else 40

            # Skip containers without children for now
            if comp_type in ("Rectangle", "Item"):
                continue

            # Extract properties
            properties = {}
            for prop_match in re.finditer(r"(\w+):\s*[\"']?([^\"'\n;]+)[\"']?", block):
                prop_name = prop_match.group(1)
                prop_value = prop_match.group(2).strip().rstrip(",")
                if prop_name in ("id", "x", "y", "width", "height", "z", "visible", "opacity"):
                    continue
                properties[prop_name] = prop_value

            widgets.append(DesignerWidget(
                type=comp_type,
                id=widget_id,
                geometry={"x": x, "y": y, "width": w, "height": h},
                properties=properties,
            ))

        return widgets

    def _parse_widget_descriptions(self, text: str) -> list:
        """Try to extract widget descriptions from natural language in the AI output.

        Looks for patterns like:
        - "Create a Button with text 'Start'"
        - "Add a Gauge for engine speed"
        """
        widgets = []
        widget_re = re.compile(
            r"(?:create|add|insert|place)\s+(?:a|an)\s+(\w+)",
            re.IGNORECASE
        )
        text_match = re.compile(r"text['\"]?\s*[=:]\s*['\"](.*?)['\"]", re.IGNORECASE)
        value_match = re.compile(r"value['\"]?\s*[=:]\s*['\"](.*?)['\"]", re.IGNORECASE)
        title_match = re.compile(r"title['\"]?\s*[=:]\s*['\"](.*?)['\"]", re.IGNORECASE)

        matches = list(widget_re.finditer(text))
        if not matches:
            return []

        for i, match in enumerate(matches):
            raw_type = match.group(1).capitalize()
            aliased = _AI_TYPE_ALIASES.get(raw_type, raw_type)
            # Find properties in the following context (next 200 chars)
            context = text[match.start():match.start() + 200]
            text_m = text_match.search(context)
            value_m = value_match.search(context)
            title_m = title_match.search(context)

            properties = {}
            if text_m:
                properties["text"] = text_m.group(1)
            if value_m:
                properties["value"] = value_m.group(1)
            if title_m:
                properties["title"] = title_m.group(1)

            widgets.append(DesignerWidget(
                type=aliased,
                id=self._make_widget_id(aliased, i),
                geometry={"x": 100 + i * 200, "y": 100 + i * 100, "width": 140, "height": 40},
                properties=properties,
            ))

        return widgets

    def _extract_partial_widgets(self, text: str, width: int, height: int) -> Optional[DesignerProject]:
        """Salvage widgets from truncated AI output.

        When the model hits the token limit the JSON block is incomplete but the
        model has often listed or described the widgets it intended to create
        in the reasoning block or in the partial JSON.  This scans for widget
        type names (from the registry / aliases) and builds a minimal project
        so the user can see *what* the model was trying to add.

        Two extraction strategies, tried in order:
        1. ``"type": "Value"`` inside partial JSON fragments
        2. Whole-word matching of known widget types in the full text
        """
        widget_types: dict[str, int] = {}  # type -> position

        # Strategy 1: Parse "type": "Value" from partial JSON fragments.
        # Handles both quoted and unquoted values since truncation can split quotes.
        for m in re.finditer(r'(?:\"type\"|type)\s*:\s*\"?([A-Za-z_]\w*)\"?', text):
            raw_type = m.group(1)
            aliased = _AI_TYPE_ALIASES.get(raw_type, raw_type)
            if aliased not in widget_types:
                widget_types[aliased] = m.start()

        # Strategy 2: Also scan full text for any known widget type name
        # (the model often names widgets in prose/reasoning even if JSON is incomplete).
        known_types: set = set(_AI_TYPE_ALIASES.keys()) | set(_AI_TYPE_ALIASES.values())
        try:
            known_types |= {d.type for d in self.registry.definitions()}
        except Exception:
            pass

        for t in known_types:
            for m in re.finditer(rf"\b{re.escape(t)}\b", text):
                aliased = _AI_TYPE_ALIASES.get(t, t)
                if aliased not in widget_types:
                    widget_types[aliased] = m.start()

        if not widget_types:
            return None

        widgets: list[DesignerWidget] = []
        idx = 0
        for widget_type, _pos in sorted(widget_types.items(), key=lambda kv: kv[1]):
            wid = f"partial_{widget_type.lower()}{idx}"
            widgets.append(DesignerWidget(
                type=widget_type,
                id=wid,
                geometry={"x": 20 + idx * 160, "y": 20 + (idx // 4) * 120, "width": 140, "height": 60},
                properties={},
            ))
            idx += 1

        if not widgets:
            return None

        project = self._build_project(widgets, "AI Design (partial)", width, height)
        project._truncated = True  # flag used by the UI to show extra context
        return project

    def _build_project(self, widgets: list, name: str, width: int, height: int) -> DesignerProject:
        """Wrap widgets into a DesignerProject."""
        page = DesignerPage(id="main", name="Main", widgets=widgets)
        from designer.model import DesignerScreen
        screen = DesignerScreen(width=width, height=height)
        return DesignerProject(version=1, name=name, screen=screen, pages=[page])

    def _make_widget_id(self, widget_type: str, index: int) -> str:
        """Generate a unique widget ID."""
        base = widget_type[:8].replace("Sh", "")
        return f"{base}{index}"


class AIDesignAgent:
    """Orchestrates the design flow: brief → generate → refine → commit.

    Flow:
    1. User provides a brief (natural language description)
    2. Send brief to OpenDesign connector for generation
    3. Parse AI output into DesignerProject
    4. Display in canvas
    5. User can iterate: "make the gauge bigger", "add a button here", etc.
    """

    def __init__(self, connector, registry=None):
        self.connector = connector
        self.registry = registry or WidgetRegistry()
        self.generator = AIDesignGenerator(self.registry)
        self.project: Optional[DesignerProject] = None
        self.conversation_history = []

    def run(self, brief: str, screen_width: int = 1280, screen_height: int = 800):
        """Execute one generation cycle.

        Yields status updates as strings.
        """
        yield "Sending brief to AI..."
        self.conversation_history.append({"role": "user", "content": brief})

        # Stream generation from connector
        full_text = ""
        for delta in self.connector.generate(brief):
            full_text += delta
            yield f"Generating... ({len(full_text)} chars)"

        self.conversation_history.append({"role": "assistant", "content": full_text})
        yield "Parsing design..."

        # Parse AI output
        self.project = self.generator.generate(full_text, screen_width, screen_height)
        if self.project:
            yield f"Design generated: {len(self.project.pages[0].widgets)} widgets"
        else:
            yield "Failed to parse AI output"

    def refine(self, instruction: str):
        """Refine the current design based on user feedback."""
        self.conversation_history.append({"role": "user", "content": f"Refinement: {instruction}"})
        context = "\n".join(
            f"{m['role']}: {m['content']}" for m in self.conversation_history[-4:]
        )
        brief = f"Refine this design. Context:\n{context}\n\nInstruction: {instruction}"
        return brief

    def get_project(self) -> Optional[DesignerProject]:
        """Return the current generated project."""
        return self.project
