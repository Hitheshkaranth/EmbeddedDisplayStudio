"""Single metadata registry used by palette, inspector, canvas and generators."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WidgetDefinition:
    type: str
    display_name: str
    category: str
    qml_component: str
    default_width: int
    default_height: int
    properties: dict[str, type] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    bindable_properties: tuple[str, ...] = ()
    container: bool = False


class WidgetRegistry:
    def __init__(self):
        self._definitions: dict[str, WidgetDefinition] = {}

    def register(self, definition: WidgetDefinition) -> None:
        if definition.type in self._definitions:
            raise ValueError(f"widget type already registered: {definition.type}")
        self._definitions[definition.type] = definition

    def get(self, widget_type: str):
        return self._definitions.get(widget_type)

    def definitions(self):
        return tuple(self._definitions.values())

    def categories(self):
        return tuple(dict.fromkeys(item.category for item in self._definitions.values()))


def default_registry() -> WidgetRegistry:
    registry = WidgetRegistry()
    entries = [
        ("Text", "Text", "Basic", "Text", 140, 32, {"text": str, "fontSize": int, "color": str}, {"text": "Text", "fontSize": 18, "color": "#f4f4f5"}, ("text",), False),
        ("ShButton", "Button", "Basic", "ShButton", 120, 40, {"text": str, "enabled": bool, "variant": str}, {"text": "Button", "enabled": True, "variant": "default"}, (), False),
        ("Image", "Image", "Basic", "Image", 160, 120, {"source": str, "fillMode": str}, {"source": "", "fillMode": "Image.PreserveAspectFit"}, (), False),
        ("Rectangle", "Rectangle", "Basic", "Rectangle", 140, 90, {"color": str, "radius": int, "opacity": float, "visible": bool}, {"color": "#27272a", "radius": 6, "opacity": 1.0, "visible": True}, (), False),
        ("ShInput", "Input Field", "Basic", "ShInput", 180, 40, {"placeholderText": str, "text": str}, {"placeholderText": "Enter value", "text": ""}, ("text",), False),
        ("ShValueTile", "Value Tile", "Industrial", "ShValueTile", 220, 110, {"title": str, "value": str, "unit": str}, {"title": "Value", "value": "0.0", "unit": ""}, ("value",), False),
        ("ShGauge", "Gauge", "Industrial", "ShGauge", 180, 180, {"minimum": float, "maximum": float, "value": float, "unit": str, "label": str}, {"minimum": 0.0, "maximum": 100.0, "value": 0.0, "unit": "", "label": "Gauge"}, ("value",), False),
        ("ShStatDot", "Status Indicator", "Industrial", "ShStatDot", 36, 36, {"state": str, "size": int}, {"state": "idle", "size": 12}, ("state",), False),
        ("ShProgress", "Progress Bar", "Industrial", "ShProgress", 200, 24, {"value": float}, {"value": 0.0}, ("value",), False),
        ("ShAlert", "Alarm Indicator", "Industrial", "ShAlert", 260, 90, {"title": str, "description": str, "variant": str}, {"title": "Alarm", "description": "", "variant": "destructive"}, ("visible",), False),
        ("ShCard", "Card", "Containers", "ShCard", 260, 180, {"visible": bool}, {"visible": True}, (), True),
        ("Row", "Row", "Containers", "Row", 300, 80, {"spacing": int}, {"spacing": 8}, (), True),
        ("Column", "Column", "Containers", "Column", 180, 260, {"spacing": int}, {"spacing": 8}, (), True),
        ("Grid", "Grid", "Containers", "Grid", 320, 220, {"columns": int, "spacing": int}, {"columns": 2, "spacing": 8}, (), True),
        ("Item", "Page", "Navigation", "Item", 320, 240, {"visible": bool}, {"visible": True}, (), True),
        ("ShTabs", "Tab Container", "Navigation", "ShTabs", 360, 240, {"currentIndex": int}, {"currentIndex": 0}, (), True),
    ]
    for values in entries:
        registry.register(WidgetDefinition(*values))
    return registry
