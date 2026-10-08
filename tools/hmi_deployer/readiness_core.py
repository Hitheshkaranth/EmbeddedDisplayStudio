from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    severity: str
    detail: str
    action: str


#: The layout compiler's kinds (designer.layout.compiler.kind_of) that show a
#: value the process reports: a face (dial, gauge), a tile or strip (readout,
#: bar), a chart. A Text label is a caption, a lamp a state, a control an
#: input -- none of them a reading.
READING_KINDS = ("face", "tile", "strip", "chart")
#: Registry categories that are a box for other things (a card, a picture), so
#: the compiler's catch-all "tile" is not a reading there.
_BOX_CATEGORIES = ("Basic", "Containers", "Navigation")


def _is_reading(widget, registry) -> bool:
    """True when the widget's registry kind is a face, tile, bar or chart."""
    from designer.layout.compiler import CHROME_MARK, kind_of
    if widget.children or widget.properties.get(CHROME_MARK):
        return False
    definition = registry.get(widget.type)
    if definition is None or definition.category in _BOX_CATEGORIES:
        return False
    return kind_of(registry, widget) in READING_KINDS


def static_readings(project) -> list:
    """Every reading that shows a value with no tag: a static on live glass.

    A reading with neither a binding nor an expression shows the sample it
    was drawn with for ever: on the panel it is a number that never moves,
    which reads as a live value that is wrong. Returns their ids, in design
    order; a Text label, a lamp, a control or a container is never one.
    """
    if project is None:
        return []
    from designer.palette.widget_registry import default_registry
    registry = default_registry()
    statics = []
    for widget in project.all_widgets():
        if widget.bindings or not _is_reading(widget, registry):
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
    project : DesignerProject | None
        The open design. When given, readings with no tag (static_readings)
        make the Tags row a warning.

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
                detail=("1 reading has no tag." if len(statics) == 1
                        else "{} readings have no tag.".format(len(statics))),
                action="Bind them in the Designer, or they show their sample for ever.",
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