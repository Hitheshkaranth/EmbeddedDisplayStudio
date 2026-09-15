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
    choices: dict[str, tuple[str, ...]] = field(default_factory=dict)
    color_properties: tuple[str, ...] = ()
    asset_properties: tuple[str, ...] = ()
    # Signals an action may be attached to, named as the QML kit declares
    # them (``clicked`` -> ``onClicked``). Property-change notifications count:
    # a control with no dedicated signal exposes ``<prop>Changed``.
    action_signals: tuple[str, ...] = ()
    # The property that holds the control's own state -- what a ``write``
    # action with no explicit value sends, and what a two-way binding targets.
    state_property: str = ""


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


# Which registry types can fire actions, and from which signal. ShButton and
# ShToggle declare real signals in the kit; ShCheckbox, ShSlider and
# ShNumInput do not, so their state property's change notification is the
# only hook -- which is also why a two-way binding on them goes through a
# ``Binding on`` element rather than a plain property binding (see the QML
# generator). ShSelect fires ``activated(index)`` on user choice only, which
# is exactly what a write wants: telemetry feeding ``currentIndex`` back does
# not re-trigger it.
ACTION_SIGNALS = {
    "ShButton": (("clicked",), ""),
    "ShToggle": (("toggled",), "checked"),
    "ShCheckbox": (("checkedChanged",), "checked"),
    "ShSlider": (("valueChanged",), "value"),
    "ShNumInput": (("valueChanged",), "value"),
    "ShSelect": (("activated",), "currentIndex"),
    "ShAlarmTable": (("alarmActivated",), ""),
}


def default_registry() -> WidgetRegistry:
    registry = WidgetRegistry()
    def add(*args, **kwargs):
        signals, state = ACTION_SIGNALS.get(args[0], ((), ""))
        registry.register(WidgetDefinition(*args, action_signals=signals,
                                           state_property=state, **kwargs))

    common = {"opacity": float, "visible": bool}
    common_defaults = {"opacity": 1.0, "visible": True}
    add("Text", "Text", "Basic", "Text", 140, 32,
        {"text": str, "fontSize": int, "bold": bool, "color": str,
         "horizontalAlignment": str, "verticalAlignment": str,
         "wrapMode": str, **common},
        {"text": "Text", "fontSize": 18, "bold": False, "color": "#f4f4f5",
         "horizontalAlignment": "Text.AlignLeft", "verticalAlignment": "Text.AlignTop",
         "wrapMode": "Text.NoWrap", **common_defaults}, ("text",), False,
        {"wrapMode": ("Text.NoWrap", "Text.WordWrap", "Text.WrapAnywhere", "Text.Wrap"),
         "horizontalAlignment": ("Text.AlignLeft", "Text.AlignHCenter",
                                 "Text.AlignRight", "Text.AlignJustify"),
         "verticalAlignment": ("Text.AlignTop", "Text.AlignVCenter",
                               "Text.AlignBottom")},
        ("color",))
    add("ShButton", "Button", "Basic", "ShButton", 120, 40,
        {"text": str, "variant": str, "size": str, "enabled": bool,
         "backgroundColor": str, "textColor": str, "borderColor": str,
         "borderWidth": int, "cornerRadius": int, **common},
        {"text": "Button", "variant": "default", "size": "default", "enabled": True,
         "backgroundColor": "", "textColor": "", "borderColor": "",
         "borderWidth": 0, "cornerRadius": 6, **common_defaults}, (), False,
        {"variant": ("default", "secondary", "destructive", "outline", "ghost", "link"),
         "size": ("default", "sm", "lg", "icon")},
        ("backgroundColor", "textColor", "borderColor"))
    add("Image", "Image", "Basic", "Image", 160, 120,
        {"source": str, "fillMode": str, "smooth": bool, **common},
        {"source": "", "fillMode": "Image.PreserveAspectFit", "smooth": True, **common_defaults}, (), False,
        {"fillMode": ("Image.PreserveAspectFit", "Image.PreserveAspectCrop", "Image.Stretch", "Image.Tile")},
        (), ("source",))
    add("Rectangle", "Rectangle", "Basic", "Rectangle", 140, 90,
        {"color": str, "borderColor": str, "borderWidth": int, "radius": int, **common},
        {"color": "#27272a", "borderColor": "#52525b", "borderWidth": 0,
         "radius": 6, **common_defaults}, (), False, {}, ("color", "borderColor"))
    add("ShInput", "Input Field", "Basic", "ShInput", 180, 40,
        {"placeholderText": str, "text": str, "enabled": bool, "readOnly": bool, **common},
        {"placeholderText": "Enter value", "text": "", "enabled": True,
         "readOnly": False, **common_defaults}, ("text",))
    add("ShValueTile", "Value Tile", "Industrial", "ShValueTile", 220, 110,
        {"title": str, "value": str, "unit": str, "state": str, **common},
        {"title": "Value", "value": "0.0", "unit": "", "state": "idle", **common_defaults},
        ("value",), False, {"state": ("idle", "ok", "warn", "fault")})
    add("ShGauge", "Gauge", "Industrial", "ShGauge", 180, 180,
        {"minimum": float, "maximum": float, "value": float, "unit": str, "label": str,
         "thresholdWarning": float, "thresholdFault": float, **common},
        {"minimum": 0.0, "maximum": 100.0, "value": 0.0, "unit": "", "label": "Gauge",
         "thresholdWarning": 70.0, "thresholdFault": 90.0, **common_defaults}, ("value",))
    add("ShStatDot", "Status Indicator", "Industrial", "ShStatDot", 36, 36,
        {"state": str, "size": int, **common},
        {"state": "idle", "size": 12, **common_defaults}, ("state",), False,
        {"state": ("idle", "ok", "warn", "fault")})
    add("ShProgress", "Progress Bar", "Industrial", "ShProgress", 200, 24,
        {"value": float, "indeterminate": bool, **common},
        {"value": 0.0, "indeterminate": False, **common_defaults}, ("value",))
    add("ShAlert", "Alarm Indicator", "Industrial", "ShAlert", 260, 90,
        {"title": str, "description": str, "variant": str, **common},
        {"title": "Alarm", "description": "", "variant": "destructive", **common_defaults},
        ("visible",), False, {"variant": ("default", "destructive")})
    # -- Avionics -------------------------------------------------------
    # Instrument colours do not follow the light/dark theme; they are the
    # conventions a crew is trained to read, so none of these expose colour
    # properties. What they expose is the reading, which is what gets bound
    # to a tag.
    add("ShDataField", "Data Field", "Avionics", "ShDataField", 150, 46,
        {"label": str, "value": str, "units": str, "severity": str,
         "stacked": bool, **common},
        {"label": "GROUND SPEED", "value": "130", "units": "KTS",
         "severity": "advisory", "stacked": True, **common_defaults},
        ("value", "severity"), False,
        {"severity": ("advisory", "caution", "warning")})
    add("ShAttitude", "Attitude Indicator", "Avionics", "ShAttitude", 220, 220,
        {"pitch": float, "roll": float, "pixelsPerDegree": float, **common},
        {"pitch": 0.0, "roll": 0.0, "pixelsPerDegree": 4.0, **common_defaults},
        ("pitch", "roll"))
    add("ShTape", "Airspeed / Altitude Tape", "Avionics", "ShTape", 80, 260,
        {"value": float, "minimumValue": float, "maximumValue": float,
         "step": float, "span": float, "label": str, "units": str,
         "side": str, **common},
        {"value": 127.0, "minimumValue": 0.0, "maximumValue": 250.0,
         "step": 10.0, "span": 60.0, "label": "IAS", "units": "KTS",
         "side": "left", **common_defaults},
        ("value",), False, {"side": ("left", "right")})
    add("ShCompass", "Heading Compass", "Avionics", "ShCompass", 220, 220,
        {"heading": float, "headingBug": float, "course": float, **common},
        {"heading": 359.0, "headingBug": 45.0, "course": -1.0, **common_defaults},
        ("heading", "headingBug"))
    add("ShVSI", "Vertical Speed", "Avionics", "ShVSI", 72, 220,
        {"value": float, "range": float, "units": str, **common},
        {"value": 0.0, "range": 2000.0, "units": "FPM", **common_defaults},
        ("value",))
    add("ShEngineGauge", "Engine Gauge", "Avionics", "ShEngineGauge", 140, 140,
        {"value": float, "minimumValue": float, "maximumValue": float,
         "greenLow": float, "greenHigh": float, "cautionHigh": float,
         "label": str, "units": str, **common},
        {"value": 55.0, "minimumValue": 0.0, "maximumValue": 100.0,
         "greenLow": 20.0, "greenHigh": 70.0, "cautionHigh": 85.0,
         "label": "OIL PRESS", "units": "PSI", **common_defaults},
        ("value",))
    add("ShAnnunciator", "Annunciator", "Avionics", "ShAnnunciator", 140, 38,
        {"text": str, "severity": str, "lit": bool, **common},
        {"text": "LOW FUEL", "severity": "caution", "lit": True, **common_defaults},
        ("lit", "severity"), False,
        {"severity": ("advisory", "caution", "warning")})
    # -- Industrial controls -------------------------------------------------
    add("ShSlider", "Slider", "Industrial", "ShSlider", 250, 64,
        {"value": float, "minValue": float, "maxValue": float, "step": float,
         "label": str, "unit": str, "valueWarning": float, "valueFault": float,
         "enabled": bool, "showTicks": bool, "tickCount": int, "showValue": bool,
         "handleRadius": float, **common},
        {"value": 50.0, "minValue": 0.0, "maxValue": 100.0, "step": 1.0,
         "label": "", "unit": "", "valueWarning": 0.0, "valueFault": 0.0,
         "enabled": True, "showTicks": True, "tickCount": 5, "showValue": True,
         "handleRadius": 12, **common_defaults}, ("value",))
    add("ShToggle", "Toggle", "Industrial", "ShToggle", 160, 40,
        {"checked": bool, "label": str, "onLabel": str, "offLabel": str,
         "enabled": bool, **common},
        {"checked": False, "label": "", "onLabel": "ON", "offLabel": "OFF",
         "enabled": True, **common_defaults}, ("checked",))
    add("ShCheckbox", "Checkbox", "Industrial", "ShCheckbox", 160, 32,
        {"checked": bool, "label": str, "enabled": bool, **common},
        {"checked": False, "label": "", "enabled": True, **common_defaults}, ("checked",))
    add("ShSelect", "Dropdown", "Industrial", "ShSelect", 200, 56,
        {"currentIndex": int, "placeholder": str, "label": str, "options": str,
         "enabled": bool, **common},
        {"currentIndex": 0, "placeholder": "Select...", "label": "",
         "options": "Auto, Manual, Service", "enabled": True, **common_defaults}, ("currentIndex",))
    add("ShNumInput", "Numeric Input", "Industrial", "ShNumInput", 240, 64,
        {"value": float, "minValue": float, "maxValue": float, "step": float,
         "unit": str, "label": str, "enabled": bool, "decimalPlaces": int,
         **common},
        {"value": 0.0, "minValue": 0.0, "maxValue": 1000.0, "step": 1.0,
         "unit": "", "label": "", "enabled": True, "decimalPlaces": 0,
         **common_defaults}, ("value",))
    add("ShNumDisplay", "Numeric Display", "Industrial", "ShNumDisplay", 180, 80,
        {"value": float, "unit": str, "label": str, "decimalPlaces": int,
         "warningLow": float, "warningHigh": float, "faultLow": float,
         "faultHigh": float, "normalColor": str, "warningColor": str,
         "faultColor": str, **common},
        {"value": 0.0, "unit": "", "label": "", "decimalPlaces": 2,
         "warningLow": 0.0, "warningHigh": 100.0, "faultLow": 0.0,
         "faultHigh": 1000.0, "normalColor": "#22c55e", "warningColor": "#f59e0b",
         "faultColor": "#ef4444", **common_defaults}, ("value",), False,
        {}, ("normalColor", "warningColor", "faultColor"))
    add("ShAnalogDisplay", "Analog Display", "Industrial", "ShAnalogDisplay", 240, 64,
        {"value": float, "minValue": float, "maxValue": float, "label": str,
         "unit": str, "normLow": float, "normHigh": float, "warnLow": float,
         "warnHigh": float, "normalColor": str, "warnColor": str,
         "faultColor": str, "trackColor": str, "vertical": bool, **common},
        {"value": 50.0, "minValue": 0.0, "maxValue": 100.0, "label": "",
         "unit": "", "normLow": 20.0, "normHigh": 80.0, "warnLow": 10.0,
         "warnHigh": 90.0, "normalColor": "#22c55e", "warnColor": "#f59e0b",
         "faultColor": "#ef4444", "trackColor": "#27272a", "vertical": False, **common_defaults},
        ("value",), False, {}, ("normalColor", "warnColor", "faultColor", "trackColor"))
    add("ShTrendChart", "Trend Chart", "Industrial", "ShTrendChart", 300, 180,
        {"minValue": float, "maxValue": float, "warningLow": float,
         "warningHigh": float, "maxPoints": int, "label": str, "unit": str,
         "lineColor": str, "fillColor": str, "lineWidth": float, **common},
        {"minValue": 0.0, "maxValue": 100.0, "warningLow": 20.0,
         "warningHigh": 80.0, "maxPoints": 100, "label": "", "unit": "",
         "lineColor": "#006fee", "fillColor": "#006fee", "lineWidth": 2.0,
         **common_defaults}, ("data",), False,
        {}, ("lineColor", "fillColor"))
    add("ShAlarmTable", "Alarm Table", "Industrial", "ShAlarmTable", 350, 216,
        {"maxVisible": int, "title": str, "showTimestamp": bool, "rowHeight": float,
         **common},
        {"maxVisible": 6, "title": "Active Alarms", "showTimestamp": True,
         "rowHeight": 30.0, **common_defaults}, ("alarms",))
    add("ShFlightDirector", "Flight Director", "Avionics", "ShFlightDirector", 180, 120,
        {"pitchCommand": float, "rollCommand": float, "pitchLimit": float,
         "rollLimit": float, "active": bool, "mode": str, **common},
        {"pitchCommand": 3.0, "rollCommand": -5.0, "pitchLimit": 15.0,
         "rollLimit": 30.0, "active": True, "mode": "FD", **common_defaults},
        ("pitchCommand", "rollCommand", "active", "mode"))
    add("ShTurnCoordinator", "Turn Coordinator", "Avionics", "ShTurnCoordinator", 180, 110,
        {"turnRate": float, "slip": float, "standardRate": float,
         "slipLimit": float, **common},
        {"turnRate": 0.0, "slip": 0.0, "standardRate": 3.0,
         "slipLimit": 1.0, **common_defaults}, ("turnRate", "slip"))
    add("ShEngineBar", "Engine Bar", "Avionics", "ShEngineBar", 76, 190,
        {"value": float, "minimumValue": float, "maximumValue": float,
         "cautionValue": float, "warningValue": float, "label": str,
         "units": str, **common},
        {"value": 68.0, "minimumValue": 0.0, "maximumValue": 100.0,
         "cautionValue": 80.0, "warningValue": 90.0, "label": "N1",
         "units": "%", **common_defaults}, ("value",))
    add("ShFuelQuantity", "Fuel Quantity", "Avionics", "ShFuelQuantity", 190, 130,
        {"leftValue": float, "rightValue": float, "capacity": float,
         "lowLevel": float, "units": str, **common},
        {"leftValue": 64.0, "rightValue": 61.0, "capacity": 100.0,
         "lowLevel": 15.0, "units": "KG", **common_defaults},
        ("leftValue", "rightValue"))

    add("ShCard", "Card", "Containers", "ShCard", 260, 180,
        {"color": str, "borderColor": str, "borderWidth": int, "radius": int, **common},
        {"color": "#18181b", "borderColor": "#27272a", "borderWidth": 1,
         "radius": 10, **common_defaults}, (), True, {}, ("color", "borderColor"))
    add("Row", "Row", "Containers", "Row", 300, 80,
        {"spacing": int, "layoutDirection": str, **common},
        {"spacing": 8, "layoutDirection": "Qt.LeftToRight", **common_defaults}, (), True,
        {"layoutDirection": ("Qt.LeftToRight", "Qt.RightToLeft")})
    add("Column", "Column", "Containers", "Column", 180, 260,
        {"spacing": int, **common}, {"spacing": 8, **common_defaults}, (), True)
    add("Grid", "Grid", "Containers", "Grid", 320, 220,
        {"columns": int, "rows": int, "spacing": int, "flow": str, **common},
        {"columns": 2, "rows": 0, "spacing": 8, "flow": "Grid.LeftToRight", **common_defaults}, (), True,
        {"flow": ("Grid.LeftToRight", "Grid.TopToBottom")})
    add("Item", "Page", "Navigation", "Item", 320, 240,
        {"clip": bool, **common}, {"clip": False, **common_defaults}, (), True)
    add("ShTabs", "Tab Container", "Navigation", "ShTabs", 360, 240,
        {"tabs": str, "currentIndex": int, **common},
        {"tabs": "Overview, Details", "currentIndex": 0, **common_defaults}, (), True)
    return registry
