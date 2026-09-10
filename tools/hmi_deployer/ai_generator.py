"""
tools/hmi_deployer/ai_generator.py -- Parse AI output into DesignerProject widgets

Takes QML code or structured JSON from OpenDesign and converts it into
DesignerProject/DesignerWidget objects that integrate with the existing canvas.
"""
import re
import json
import logging
from typing import Optional

from PySide6.QtCore import Signal, QObject
from designer.model import DesignerProject, DesignerPage, DesignerWidget
from designer.palette.widget_registry import WidgetDefinition, WidgetRegistry

logger = logging.getLogger(__name__)

# Regex to extract QML code blocks from markdown or plain text.
QML_BLOCK_RE = re.compile(r"```(?:qml|QML)?\s*\n(.*?)```", re.DOTALL)
# Regex to extract JSON design payloads.
JSON_DESIGN_RE = re.compile(r"\{[\s\S]*\"pages\"[\s\S]*\}")


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
    # Containers
    "Card": "ShCard",
    "Panel": "ShCard",
    "Row": "Row",
    "Column": "Column",
    "Grid": "Grid",
    "Page": "Item",
    "TabContainer": "ShTabs",
}


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

        # Strategy 1: JSON design payload
        try:
            json_match = JSON_DESIGN_RE.search(ai_output)
            if json_match:
                design = json.loads(json_match.group())
                return self._from_json_design(design, screen_width, screen_height)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.debug("JSON parsing failed: %s", exc)

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

        self.progress.error.emit("Unable to parse AI output. Try rephrasing the prompt.")
        return None

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

        return self._build_project(widgets, design.get("name", "AI Design"), width, height)

    def _convert_widgets(self, widget_list: list) -> list:
        """Convert a list of widget dicts to DesignerWidget objects."""
        result = []
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
            bindings = {k: {"tag": v.get("tag", "")} for k, v in wdata.get("bindings", {}).items()}

            children = []
            for child_data in wdata.get("children", []):
                child = self._convert_widgets([child_data])[0] if child_data else None
                if child:
                    children.append(child)

            result.append(DesignerWidget(
                type=aliased,
                id=self._make_widget_id(aliased, i),
                geometry={"x": x, "y": y, "width": w, "height": h},
                properties=properties,
                children=children,
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