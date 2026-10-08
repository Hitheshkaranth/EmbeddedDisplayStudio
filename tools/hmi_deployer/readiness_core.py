from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    severity: str
    detail: str
    action: str


# A widget is a reading when its type shows a value the process reports: a
# face (a dial, a gauge), a tile (a readout, a data field), a bar, or a chart.
# A Text label is a caption, not a reading; a container and a button show
# neither a value nor a tag, so neither is a reading.
READING_KINDS = ("face", "tile", "bar", "chart")


def _is_reading(widget) -> bool:
    """True when the widget type is a reading: a face, tile, bar or chart.

    A label (Text), a container, and a control are not readings.
    """
    kind = widget_kind(widget)
    return kind in READING_KINDS


def widget_kind(widget) -> str:
    """One of face, tile, bar, chart, label, container, control."""
    wtype = getattr(widget, "type", "")
    if wtype == "Text":
        return "label"
    if wtype in ("ShRectangle", "ShContainer", "Frame", "ShPanel", "ShCard", "Rectangle",
                 "Column", "Row", "ShStack", "ShStackedLayout", "ShBorder"):
        return "container"
    if wtype in ("ShButton", "ShToggle", "ShCheckbox", "ShSelect", "ShSlider",
                 "ShInput", "ShNumInput", "ShTabs", "ShMenuItem", "ShMenuItemGroup"):
        return "control"
    if "arc" in wtype.lower() or "gauge" in wtype.lower() or "dial" in wtype.lower() \
            or "tape" in wtype.lower() or "segment" in wtype.lower() \
            or "progress" in wtype.lower() or "analog" in wtype.lower():
        return "face"
    if "bar" in wtype.lower() or "traction" in wtype.lower() or "enginebar" in wtype.lower():
        return "bar"
    if "chart" in wtype.lower():
        return "chart"
    if any(name in wtype for name in ("tile", "readout", "display", "indicator", "field",
                                        "numdisplay", "alert", "icontile", "statuscard",
                                        "consist", "stationline", "trainconsist", "speedarc",
                                        "gear", "show", "tripinfo", "autopos", "autolevel")):
        return "tile"
    return "tile"


def static_readings(project) -> list:
    """Every reading that shows a value with no tag: a static on live glass.

    A reading that has neither a binding nor an expression shows a value the
    model wrote by hand; the panel overwrites it with a real reading, so a
    reading the deployer has not bound to a tag is a reading that is not live
    -- the readiness check warns that it has no tag. A bound reading, or one
    whose value is an expression, is not counted.
    """
    if project is None:
        return []
    statics = []
    for widget in project.all_widgets():
        if not _is_reading(widget):
            continue
        if widget.bindings:
            continue
        props = widget.properties
        if props.get("expr") or props.get("expression"):
            continue
        statics.append(widget.id)
    return statics


def audit_readiness(bundle_valid, manifest, connected, detected_resolution, project=None):
    """Audit readiness and return exactly four ReadinessItem rows.

    Parameters
    ----------
    bundle_valid : bool
        Whether the deployment bundle is valid.
    manifest : dict | None
        The parsed manifest for the target display.
    connected : bool
        Whether the target display is currently connected.
    detected_resolution : tuple[int, int] | None
        The detected screen resolution as (width, height), or None.

    Returns
    -------
    tuple[ReadinessItem, ReadinessItem, ReadinessItem, ReadinessItem]
        Bundle, Target, Display, Tags items in that order.
    """
    # --- Bundle ---
    if manifest is None or not bundle_valid:
        bundle_item = ReadinessItem(
            name="Bundle",
            severity="error",
            detail="Bundle is invalid or manifest is missing.",
            action="Provide a valid bundle with a manifest.",
        )
    else:
        bundle_item = ReadinessItem(
            name="Bundle",
            severity="ready",
            detail="Bundle is valid.",
            action="",
        )

    # --- Target ---
    if connected:
        target_item = ReadinessItem(
            name="Target",
            severity="ready",
            detail="Target display is connected.",
            action="",
        )
    else:
        target_item = ReadinessItem(
            name="Target",
            severity="warning",
            detail="Target display is not connected.",
            action="Connect the target display before deploying.",
        )

    # --- Display (geometry match) ---
    if manifest is not None:
        screen = manifest.get("screen", {})
        target_w = screen.get("width")
        target_h = screen.get("height")
        if target_w is not None and target_h is not None and detected_resolution is not None:
            if (target_w, target_h) == detected_resolution:
                display_item = ReadinessItem(
                    name="Display",
                    severity="ready",
                    detail="Screen geometry matches detected resolution.",
                    action="",
                )
            else:
                display_item = ReadinessItem(
                    name="Display",
                    severity="warning",
                    detail="Screen geometry mismatch: expected ({}, {}), detected {}.".format(
                        target_w, target_h, detected_resolution
                    ),
                    action="Verify display configuration or update manifest.",
                )
        else:
            display_item = ReadinessItem(
                name="Display",
                severity="info",
                detail="Target geometry or detected resolution unavailable.",
                action="Check display detection.",
            )
    else:
        display_item = ReadinessItem(
            name="Display",
            severity="info",
            detail="Manifest unavailable; cannot verify display geometry.",
            action="Provide a valid manifest.",
        )

    # --- Tags ---
    if manifest is not None:
        tags_required = manifest.get("tags_required")
        statics = static_readings(project) if project is not None else []
        if statics:
            tags_item = ReadinessItem(
                name="Tags",
                severity="warning",
                detail="{} readings have no tag.".format(len(statics)),
                action="Bind these readings to a tag so the panel shows the live value.",
            )
        elif tags_required:
            tags_item = ReadinessItem(
                name="Tags",
                severity="ready",
                detail="All required tags are present.",
                action="",
            )
        else:
            tags_item = ReadinessItem(
                name="Tags",
                severity="info",
                detail="No required tags specified.",
                action="",
            )
    else:
        tags_item = ReadinessItem(
            name="Tags",
            severity="info",
            detail="Manifest unavailable; cannot verify tags.",
            action="Provide a valid manifest.",
        )

    return (bundle_item, target_item, display_item, tags_item)