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
from designer.palette.widget_registry import WidgetDefinition, WidgetRegistry

logger = logging.getLogger(__name__)

# Regex to extract QML code blocks from markdown or plain text.
QML_BLOCK_RE = re.compile(r"```(?:qml|QML)?\s*\n(.*?)```", re.DOTALL)
# Regex to extract JSON design payloads.
JSON_DESIGN_RE = re.compile(r"\{[\s\S]*\"pages\"[\s\S]*\}")
# A legal QML id: lowercase start, then word characters.
_QML_ID_RE = re.compile(r"[a-z_][A-Za-z0-9_]*")
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
}


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

    Sections are page-level slices. A repeated id replaces the earlier widget,
    which lets a later section deliberately correct an item without creating a
    duplicate. New pages and widgets retain the order the model emitted.
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
        existing = {widget.id: index for index, widget in enumerate(target.widgets)}
        for widget in incoming_page.widgets:
            incoming = copy.deepcopy(widget)
            index = existing.get(incoming.id)
            if index is None:
                existing[incoming.id] = len(target.widgets)
                target.widgets.append(incoming)
            else:
                target.widgets[index] = incoming
    return merged


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


def build_system_prompt(registry: Optional[WidgetRegistry] = None,
                        screen_width: int = 1280, screen_height: int = 800) -> str:
    """System prompt that steers the model at the JSON payload we parse best.

    Lists the registry's real widget types so the model does not invent
    component names, and pins the screen size so geometry lands on glass.
    """
    types: list[str] = []
    if registry is not None:
        try:
            types = sorted(d.type for d in registry.definitions())
        except Exception:
            types = []
    if not types:
        types = sorted(set(_AI_TYPE_ALIASES.values()))
    return (
        "You are an expert HMI designer for embedded Qt/QML panels built with the "
        "EmbeddedDisplay Studio widget set (Shadcn-styled). "
        f"The target screen is {screen_width}x{screen_height} px; place every widget "
        "inside it with absolute geometry.\n\n"
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


class AIDesignGenerator:
    """Parse AI output (QML code or JSON design spec) into DesignerProject."""

    def __init__(self, registry: Optional[WidgetRegistry] = None):
        self.registry = registry or WidgetRegistry()
        self.progress = GeneratorProgress()

    def generate(self, ai_output: str, screen_width: int = 1280, screen_height: int = 800) -> Optional[DesignerProject]:
        """Generate a DesignerProject from AI output.

        Tries three parsing strategies in order:
        1. JSON design payload ({"pages": [...]})
        2. Markdown-wrapped QML code blocks
        3. Plain QML code

        Returns DesignerProject or None on failure.
        """
        self.progress.progress.emit("Parsing AI output...")

        # Strategy 1: JSON design payload -- a fenced ```json block first (that
        # is what the system prompt asks for), then any bare {"pages": …}.
        for candidate in self._json_candidates(ai_output):
            try:
                design = json.loads(candidate)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.debug("JSON parsing failed: %s", exc)
                continue
            if isinstance(design, dict) and ("pages" in design or "widgets" in design):
                return self._from_json_design(design, screen_width, screen_height)

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
        return candidates

    def _from_json_design(self, design: dict, width: int, height: int) -> DesignerProject:
        """Convert a JSON design payload (pages, widgets) to DesignerProject."""
        widgets = []
        pages_data = design.get("pages", [])
        if pages_data:
            for page_data in pages_data:
                page_widgets = page_data.get("widgets", [])
                widgets.extend(self._convert_widgets(page_widgets))
        else:
            widgets = self._convert_widgets(design.get("widgets", []))

        project = self._build_project(widgets, design.get("name", "AI Design"), width, height)
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
        return project

    def _convert_widgets(self, widget_list: list) -> list:
        """Convert a list of widget dicts to DesignerWidget objects."""
        result = []
        seen_ids: set = set()
        for i, wdata in enumerate(widget_list):
            widget_type = wdata.get("type", "Rectangle")
            # Resolve aliases (e.g. "Button" -> "ShButton")
            aliased = _AI_TYPE_ALIASES.get(widget_type, widget_type)
            # Check if aliased type exists in registry; fall back to Rectangle
            if aliased not in (_AI_TYPE_ALIASES.get(v, v) for v in _AI_TYPE_ALIASES.values()):
                if not self.registry.get(aliased):
                    # Double-check original type
                    if not self.registry.get(widget_type):
                        aliased = "Rectangle"
            geometry = wdata.get("geometry", {})
            x = geometry.get("x", i * 20 % 1000)
            y = geometry.get("y", i * 20 % 800)
            w = geometry.get("width", 140)
            h = geometry.get("height", 40)
            properties = wdata.get("properties", {})
            # Bindings are what the prompt asks for ("value" -> plc tag); keep
            # every one that has a tag, in the model's own DesignerBinding type.
            bindings = {}
            for prop, value in (wdata.get("bindings") or {}).items():
                try:
                    binding = DesignerBinding.from_data(value)
                except (ValueError, TypeError):
                    continue
                if binding.tag:
                    bindings[str(prop)] = binding

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
                if action.kind in ("write", "pulse", "navigate"):
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
    """Orchestrates the swarm: brief → generate → refine → commit.

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
