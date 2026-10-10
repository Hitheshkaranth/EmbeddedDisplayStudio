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


# The floor for numeric properties that stop meaning anything below it. A
# font of 0 px is invisible and Qt says so on every repaint; a negative one
# (what a cleared spin box sends) takes the widget with it. The inspector
# refuses to go lower, the generator clamps what a project file carries,
# and an edit command is clamped before it lands in the model.
PROPERTY_MINIMUMS = {
    "fontSize": 1, "size": 1, "segments": 1, "maxPoints": 2, "maxVisible": 1,
    "decimals": 0, "decimalPlaces": 0, "tickCount": 0, "borderWidth": 0,
    "cornerRadius": 0, "radius": 0, "handleRadius": 1, "lineWidth": 0.5,
    "rowHeight": 8, "pixelsPerDegree": 0.1, "spacing": 0, "columns": 0,
    "rows": 0, "majorStep": 0.001, "sweep": 10, "redZoneSpan": 0, "step": 0,
    "speed": 1, "headerHeight": 0,
}

# Per-type exceptions to the floors above, keyed (type, property). A
# ShProcessValue's ``decimals`` of -1 means "show the value as given", so its
# floor is -1, not 0.
TYPE_PROPERTY_MINIMUMS = {
    ("ShProcessValue", "decimals"): -1,
    ("ShKpiTile", "decimals"): -1,
}


def property_minimum(name, widget_type=None):
    """The floor for ``name`` on ``widget_type``, or None when it has none."""
    if (widget_type, name) in TYPE_PROPERTY_MINIMUMS:
        return TYPE_PROPERTY_MINIMUMS[(widget_type, name)]
    return PROPERTY_MINIMUMS.get(name)


def clamp_property(name, value, widget_type=None):
    """``value`` raised to the property's floor when it has one."""
    floor = property_minimum(name, widget_type)
    if floor is None or isinstance(value, bool):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number < floor:
        return type(value)(floor) if isinstance(value, (int, float)) else floor
    return value


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
    # CONTRACT 13.5: the on-screen keyboard's OK.
    "ShInput": (("accepted",), "text"),
    # Automotive: the mode selector fires activated(index) on a tap like
    # ShSelect; the tile is a button with an icon.
    "ShDriveMode": (("activated",), "currentIndex"),
    "ShIconTile": (("clicked",), ""),
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
    # Style options, off by default: ``gradient`` shades the fill from 12 %
    # lighter at the top to 12 % darker at the bottom (a raised key);
    # ``glowColor`` puts a soft ~8 px glow of that colour around the button
    # (the active tab of a navigation row).
    add("ShButton", "Button", "Basic", "ShButton", 120, 40,
        {"text": str, "variant": str, "size": str, "enabled": bool,
         "backgroundColor": str, "textColor": str, "borderColor": str,
         "borderWidth": int, "cornerRadius": int, "gradient": bool, "glowColor": str,
         **common},
        {"text": "Button", "variant": "default", "size": "default", "enabled": True,
         "backgroundColor": "", "textColor": "", "borderColor": "",
         "borderWidth": 0, "cornerRadius": 6, "gradient": False, "glowColor": "",
         **common_defaults}, (), False,
        {"variant": ("default", "secondary", "destructive", "outline", "ghost", "link"),
         "size": ("default", "sm", "lg", "icon")},
        ("backgroundColor", "textColor", "borderColor", "glowColor"))
    add("Image", "Image", "Basic", "Image", 160, 120,
        {"source": str, "fillMode": str, "smooth": bool, **common},
        {"source": "", "fillMode": "Image.PreserveAspectFit", "smooth": True, **common_defaults}, (), False,
        {"fillMode": ("Image.PreserveAspectFit", "Image.PreserveAspectCrop", "Image.Stretch", "Image.Tile")},
        (), ("source",))
    # A moving picture: an animated GIF the user supplies, played by QtQuick's
    # AnimatedImage and by LVGL's lv_gif on the panel. ``speed`` is playback
    # speed in percent (100 = as the file says).
    add("ShAnimatedImage", "Animated image", "Basic", "ShAnimatedImage", 240, 160,
        {"source": str, "playing": bool, "speed": int, "fillMode": str, **common},
        {"source": "", "playing": True, "speed": 100, "fillMode": "Image.PreserveAspectFit",
         **common_defaults}, ("playing",), False,
        {"fillMode": ("Image.PreserveAspectFit", "Image.PreserveAspectCrop", "Image.Stretch")},
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
    # conventions a crew is trained to read, so they expose no colour
    # properties (ShEngineBar's optional barColor, for a vehicle's vitals row,
    # is the one exception). What they expose is the reading, which is what
    # gets bound to a tag.
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
    # ``litColor`` ("" = the severity's) is the lamp's colour, e.g. a SCADA
    # screen's bright green; ``glow`` adds a soft ~8 px glow of it when lit.
    add("ShAnnunciator", "Annunciator", "Avionics", "ShAnnunciator", 140, 38,
        {"text": str, "severity": str, "lit": bool, "litColor": str, "glow": bool, **common},
        {"text": "LOW FUEL", "severity": "caution", "lit": True, "litColor": "", "glow": False,
         **common_defaults},
        ("lit", "severity"), False,
        {"severity": ("advisory", "caution", "warning")}, ("litColor",))
    # -- Automotive ----------------------------------------------------------
    # Instrument cluster widgets after the two reference dashboards; colours
    # come from Theme.qml's auto* block. An accent override (accentColor,
    # barColor; "" keeps the theme's) is the only colour they expose.
    # ``style`` "neon" (the look of a glowing cockpit picture): no ticks,
    # numbers or needle; a dim track and a thick round-capped value arc
    # shaded along the scale from accentColor to ``accentColor2`` ("" = the
    # accent lighter), red past redlineFrom, with a soft glow; caption, a big
    # bold value, then unit and label in the centre.
    add("ShClusterGauge", "Cluster Gauge", "Automotive", "ShClusterGauge", 240, 240,
        {"value": float, "minimumValue": float, "maximumValue": float, "majorStep": float, "redlineFrom": float, "sweep": float, "readout": str, "readoutUnit": str, "caption": str, "label": str, "decimals": int, "showInnerDial": bool, "accentColor": str, "style": str, "accentColor2": str, **common},
        {"value": 4.2, "minimumValue": 0.0, "maximumValue": 8.0, "majorStep": 1.0, "redlineFrom": 7.0, "sweep": 240.0, "readout": '137', "readoutUnit": 'km/h', "caption": '', "label": 'x1000 RPM', "decimals": 0, "showInnerDial": True, "accentColor": "", "style": "classic", "accentColor2": "", **common_defaults},
        ('value', 'readout', 'caption'), False, {"style": ("classic", "neon")}, ("accentColor", "accentColor2"))
    add("ShGearIndicator", "Gear Indicator", "Automotive", "ShGearIndicator", 120, 70,
        {"gears": str, "gear": str, "modeNumber": int, "showAll": bool, "orientation": str, **common},
        {"gears": 'P,R,N,D', "gear": 'D', "modeNumber": 4, "showAll": True, "orientation": 'horizontal', **common_defaults},
        ('gear', 'modeNumber'), False, {'orientation': ('horizontal', 'vertical')})
    add("ShAutoLevel", "Level Bar", "Automotive", "ShAutoLevel", 90, 220,
        {"value": float, "minimumValue": float, "maximumValue": float, "topLabel": str, "midLabel": str, "bottomLabel": str, "redZone": str, "redZoneSpan": float, "icon": str, "curved": bool, "showTicks": bool, **common},
        {"value": 55.0, "minimumValue": 0.0, "maximumValue": 100.0, "topLabel": 'F', "midLabel": '1/2', "bottomLabel": 'E', "redZone": 'low', "redZoneSpan": 12.0, "icon": 'gas-station', "curved": True, "showTicks": True, **common_defaults},
        ('value',), False, {'redZone': ('low', 'high', 'none')})
    add("ShAutoReadout", "Readout", "Automotive", "ShAutoReadout", 150, 56,
        {"value": float, "unit": str, "icon": str, "iconSide": str, "decimals": int, "label": str, "warnBelow": float, "warnAbove": float, **common},
        {"value": 90.0, "unit": '°C', "icon": 'temperature', "iconSide": 'right', "decimals": 0, "label": '', "warnBelow": 0.0, "warnAbove": 0.0, **common_defaults},
        ('value',), False, {'iconSide': ('left', 'right')})
    add("ShDriveMode", "Drive Mode", "Automotive", "ShDriveMode", 180, 56,
        {"label": str, "modes": str, "currentIndex": int, "enabled": bool, **common},
        {"label": 'Drive mode', "modes": 'ECO,COMFORT,SPORT', "currentIndex": 2, "enabled": True, **common_defaults},
        ('currentIndex',))
    add("ShTelltale", "Telltale", "Automotive", "ShTelltale", 48, 48,
        {"icon": str, "color": str, "lit": bool, "blink": bool, "label": str, **common},
        {"icon": 'bulb', "color": 'amber', "lit": True, "blink": False, "label": '', **common_defaults},
        ('lit', 'blink', 'color'), False, {'color': ('amber', 'green', 'red', 'blue', 'white')})
    add("ShTripInfo", "Trip Info", "Automotive", "ShTripInfo", 200, 110,
        {"title": str, "row1Label": str, "row1Value": str, "row1Unit": str, "row2Label": str, "row2Value": str, "row2Unit": str, **common},
        {"title": 'Distance', "row1Label": 'Day', "row1Value": '352', "row1Unit": 'km', "row2Label": 'Total', "row2Value": '110 593', "row2Unit": 'km', **common_defaults},
        ('row1Value', 'row2Value'))
    # ``style`` "solid": one rounded bar filled in barColor (shaded along its
    # length, with a soft glow) instead of cells -- a glowing fuel gauge.
    add("ShSegmentBar", "Segment Bar", "Automotive", "ShSegmentBar", 320, 36,
        {"value": float, "minimumValue": float, "maximumValue": float, "segments": int, "label": str, "showPercent": bool, "lowLevel": float, "barColor": str, "style": str, **common},
        {"value": 60.0, "minimumValue": 0.0, "maximumValue": 100.0, "segments": 12, "label": 'SOC', "showPercent": True, "lowLevel": 20.0, "barColor": "", "style": "segments", **common_defaults},
        ('value',), False, {"style": ("segments", "solid")}, ("barColor",))
    add("ShIconTile", "Icon Tile", "Automotive", "ShIconTile", 100, 110,
        {"icon": str, "label": str, "enabled": bool, "active": bool, **common},
        {"icon": 'phone', "label": 'BT', "enabled": True, "active": False, **common_defaults},
        ('active',))
    add("ShVehicleStatus", "Vehicle Status", "Automotive", "ShVehicleStatus", 150, 190,
        {"frontLeft": float, "frontRight": float, "rearLeft": float, "rearRight": float, "unit": str, "warnBelow": float, "decimals": int, "label": str, "axles": int, "midLeft": float, "midRight": float, **common},
        {"frontLeft": 2.6, "frontRight": 2.5, "rearLeft": 1.6, "rearRight": 2.2, "unit": 'bar', "warnBelow": 1.8, "decimals": 1, "label": 'TPMS', "axles": 2, "midLeft": 2.4, "midRight": 2.4, **common_defaults},
        ('frontLeft', 'frontRight', 'rearLeft', 'rearRight', 'midLeft', 'midRight'))
    # -- Rail (metro cab and control-room faces) ---------------------------
    # ``style`` "neon": the value as three concentric thick arcs (outerColor
    # brightest and glowing outermost, dimmer and thinner inwards towards
    # innerColor), a big bold value with the unit under it, no needle.
    add("ShSpeedArc", "Speed Arc", "Rail", "ShSpeedArc", 420, 420,
        {"value": float, "maximumValue": float, "target": float, "showTarget": bool, "unit": str,
         "targetLabel": str, "decimals": int, "outerColor": str, "innerColor": str, "style": str,
         **common},
        {"value": 55.0, "maximumValue": 100.0, "target": 60.0, "showTarget": True, "unit": 'KM/H',
         "targetLabel": 'TARGET', "decimals": 0, "outerColor": '#22d3ee', "innerColor": '#a855f7',
         "style": "classic", **common_defaults},
        ('value', 'target'), False, {"style": ("classic", "neon")}, ('outerColor', 'innerColor'))
    add("ShTractionBar", "Traction / Brake", "Rail", "ShTractionBar", 140, 640,
        {"value": float, "title": str, "powerLabel": str, "brakeLabel": str,
         "propulsionText": str, "brakingText": str, **common},
        {"value": 30.0, "title": 'T/B', "powerLabel": 'POWER', "brakeLabel": 'BRAKING',
         "propulsionText": 'Propulsion', "brakingText": 'Braking', **common_defaults},
        ('value',))
    add("ShStationLine", "Station Line", "Rail", "ShStationLine", 520, 680,
        {"stations": str, "details": str, "current": int, "accent": str, **common},
        {"stations": 'Attiguppe,Vijayanagar,Hosahalli,Magadi Road,KSR Bengaluru',
         "details": 'COMPLETED,P-412,NEXT · 1.1 km,UPCOMING · 2.3 km,Majestic',
         "current": 1, "accent": '#a855f7', **common_defaults},
        ('current', 'details'), False, {}, ('accent',))
    add("ShTrainConsist", "Train Consist", "Rail", "ShTrainConsist", 300, 880,
        {"cars": str, "doorsLeft": str, "doorsRight": str, "leftLabel": str, "rightLabel": str,
         "accent": str, **common},
        {"cars": 'MC1,M1,T1,T2,M2,MC2', "doorsLeft": 'closed', "doorsRight": 'disabled',
         "leftLabel": 'DOORS L: CLOSED (SECURED)', "rightLabel": 'DOORS R: DISABLED',
         "accent": '#a855f7', **common_defaults},
        ('doorsLeft', 'doorsRight', 'leftLabel', 'rightLabel'), False,
        {"doorsLeft": ('closed', 'open', 'disabled'), "doorsRight": ('closed', 'open', 'disabled')},
        ('accent',))
    add("ShStatusCard", "Status Card", "Rail", "ShStatusCard", 240, 180,
        {"icon": str, "title": str, "status": str, "state": str, "iconColor": str, **common},
        {"icon": 'snowflake', "title": 'HVAC:', "status": 'ACTIVE (21°C)', "state": 'ok',
         "iconColor": '#38bdf8', **common_defaults},
        ('status', 'state'), False, {"state": ('ok', 'warn', 'fault', 'idle')}, ('iconColor',))
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
    # A SCADA reading row: "Hot Blast Temp  [~~]  [ 1185 ]  °C" -- a label, an
    # optional sparkline of the recent values, a dark inset box with bright
    # right-aligned digits, and a unit column. ``value`` is a number or a
    # string ("76,600"); ``decimals`` -1 shows it as given. warnAbove /
    # warnBelow of 0 are off, as on ShAutoReadout. ``bevel`` draws the boxes
    # inset (a dark line along the top, a light one along the bottom).
    add("ShProcessValue", "Process value", "Industrial", "ShProcessValue", 260, 30,
        {"label": str, "value": str, "decimals": int, "unit": str, "valueColor": str,
         "boxColor": str, "trend": bool, "trendColor": str, "warnAbove": float,
         "warnBelow": float, "bevel": bool, **common},
        {"label": "Value", "value": 0, "decimals": -1, "unit": "", "valueColor": "#3ee05a",
         "boxColor": "#0a0d0b", "trend": False, "trendColor": "#f5a524", "warnAbove": 0.0,
         "warnBelow": 0.0, "bevel": False, **common_defaults}, ("value",), False,
        {}, ("valueColor", "boxColor", "trendColor"))
    # One tile of a plant dashboard's KPI strip: an optional icon at the left,
    # the title, a big value with its unit beside it, a muted subtitle
    # ("Target 3,200 tpd") and a thin progress bar along the bottom
    # (``progress`` 0..100; negative hides it) with ``progressText`` ("94 %")
    # at its right end. ``value`` is a number or a string ("3,015");
    # ``decimals`` -1 shows it as given. Colours "" are the theme's
    # (foreground, success, card).
    add("ShKpiTile", "KPI tile", "Industrial", "ShKpiTile", 250, 96,
        {"icon": str, "title": str, "value": str, "decimals": int, "unit": str, "subtitle": str,
         "progress": float, "progressText": str, "valueColor": str, "barColor": str,
         "tileColor": str, **common},
        {"icon": "", "title": "KPI", "value": 0, "decimals": -1, "unit": "",
         "subtitle": "", "progress": -1.0, "progressText": "", "valueColor": "",
         "barColor": "", "tileColor": "", **common_defaults}, ("value", "progress"), False,
        {}, ("valueColor", "barColor", "tileColor"))
    # One line of a "Key Status" list: a lamp, a label and a status badge at
    # the right ("RUNNING") coloured by ``state`` (ok green, warn amber, fault
    # red, idle grey). Stacked rows line their badges up.
    add("ShStatusRow", "Status row", "Industrial", "ShStatusRow", 280, 26,
        {"label": str, "status": str, "state": str, **common},
        {"label": "Main drive", "status": "RUNNING", "state": "ok", **common_defaults},
        ("status", "state"), False, {"state": ("idle", "ok", "warn", "fault")})
    # ``series`` "Label|#color|level;..." draws a multi-series dashboard trend
    # (a legend at the right; until live data each series a gently noisy line
    # about its level; ``data`` feeds the first); ``xLabels`` "12:30,13:00,..."
    # under the x axis. Both "" = the single trace.
    add("ShTrendChart", "Trend Chart", "Industrial", "ShTrendChart", 300, 180,
        {"minValue": float, "maxValue": float, "warningLow": float,
         "warningHigh": float, "maxPoints": int, "label": str, "unit": str,
         "lineColor": str, "fillColor": str, "lineWidth": float, "series": str,
         "xLabels": str, **common},
        {"minValue": 0.0, "maxValue": 100.0, "warningLow": 20.0,
         "warningHigh": 80.0, "maxPoints": 100, "label": "", "unit": "",
         "lineColor": "#006fee", "fillColor": "#006fee", "lineWidth": 2.0,
         "series": "", "xLabels": "", **common_defaults}, ("data",), False,
        {}, ("lineColor", "fillColor"))
    # ``columns`` "Time,Tag,Description,Priority,Status" and ``sampleRows``
    # ("14:28:12|KILN-TEMP-HH|Kiln outlet temperature high|HIGH|ACTIVE;...")
    # make it a table: a column header row, live alarms filled in by column
    # name, and the sample rows drawn while no alarm is active (a design
    # preview). HIGH/MEDIUM/LOW and ACTIVE/ACKED cells are coloured pills.
    # ``headerColor`` colours the title bar ("" = the theme's); ``showCount``
    # shows the count badge. With columns "Time,Description" it is an event log.
    add("ShAlarmTable", "Alarm Table", "Industrial", "ShAlarmTable", 350, 216,
        {"maxVisible": int, "title": str, "showTimestamp": bool, "rowHeight": float,
         "mode": str, "columns": str, "sampleRows": str, "headerColor": str,
         "showCount": bool, **common},
        {"maxVisible": 6, "title": "Active Alarms", "showTimestamp": True,
         "rowHeight": 30.0, "mode": "active", "columns": "", "sampleRows": "", "headerColor": "",
         "showCount": True, **common_defaults}, ("alarms",), False,
        {"mode": ("active", "history")}, ("headerColor",))
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
    # ``glow``: a soft glow around the fill in its colour (a vitals row).
    add("ShEngineBar", "Engine Bar", "Avionics", "ShEngineBar", 76, 190,
        {"value": float, "minimumValue": float, "maximumValue": float,
         "cautionValue": float, "warningValue": float, "label": str,
         "units": str, "orientation": str, "barColor": str, "glow": bool, **common},
        {"value": 68.0, "minimumValue": 0.0, "maximumValue": 100.0,
         "cautionValue": 80.0, "warningValue": 90.0, "label": "N1",
         "units": "%", "orientation": "vertical", "barColor": "", "glow": False,
         **common_defaults}, ("value",),
        False, {"orientation": ("vertical", "horizontal")}, ("barColor",))
    add("ShFuelQuantity", "Fuel Quantity", "Avionics", "ShFuelQuantity", 190, 130,
        {"leftValue": float, "rightValue": float, "capacity": float,
         "lowLevel": float, "units": str, **common},
        {"leftValue": 64.0, "rightValue": 61.0, "capacity": 100.0,
         "lowLevel": 15.0, "units": "KG", **common_defaults},
        ("leftValue", "rightValue"))

    # Style options, off by default: ``headerHeight`` > 0 draws a title band
    # that high across the top in ``headerColor`` ("" = the card colour a
    # little lighter) with a 1 px divider in the border colour under it;
    # ``gradient`` shades the fill from 6 % lighter at the top to the colour.
    add("ShCard", "Card", "Containers", "ShCard", 260, 180,
        {"color": str, "borderColor": str, "borderWidth": int, "radius": int,
         "headerHeight": int, "headerColor": str, "gradient": bool, **common},
        {"color": "#18181b", "borderColor": "#27272a", "borderWidth": 1,
         "radius": 10, "headerHeight": 0, "headerColor": "", "gradient": False,
         **common_defaults}, (), True, {}, ("color", "borderColor", "headerColor"))
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
