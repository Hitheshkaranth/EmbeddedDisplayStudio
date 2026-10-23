"""Read-only checks for an image-derived design, never proof of deployment.

The audit distinguishes editable configuration from illustration. It does not
infer PLC addresses or manufacture actions from a screenshot. Text-fit findings
are estimates; visual similarity and runtime operation require separate checks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re


@dataclass(frozen=True)
class ReferenceIssue:
    kind: str
    severity: str
    page_id: str
    widget_id: str
    message: str


@dataclass(frozen=True)
class ReferenceAudit:
    issues: tuple[ReferenceIssue, ...]
    counts: dict[str, int]

    @property
    def configuration_ready(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def summary(self) -> str:
        errors = sum(issue.severity == "error" for issue in self.issues)
        warnings = sum(issue.severity == "warning" for issue in self.issues)
        return (f"Reference check: {errors} configuration issue(s), {warnings} warning(s). "
                "Visual match and live operation are not verified.")

    def to_dict(self) -> dict:
        return {"schema": 1, "configuration_ready": self.configuration_ready,
                "visual_match_verified": False, "runtime_verified": False,
                "deployment_verified": False, "summary": self.summary(),
                "counts": dict(self.counts), "issues": [asdict(i) for i in self.issues]}


_CONTROLS = {"ShButton", "ShToggle", "ShCheckbox", "ShSlider", "ShNumInput",
             "ShSelect", "ShInput", "ShDriveMode", "ShIconTile"}
_READOUTS = {"ShKpiTile": ("value",), "ShProcessValue": ("value",),
             "ShDataField": ("value",), "ShTrendChart": ("data",),
             "ShStatusRow": ("state", "status"), "ShGauge": ("value",),
             "ShProgress": ("value",), "ShLevel": ("value",)}
_PICTURES = {"Image", "ShAnimatedImage"}
_DIAGRAM = re.compile(r"\b(pfd|diagram|process flow|plant|schematic)\b", re.I)


def _walk(widgets, ox=0, oy=0, visible=True):
    for widget in widgets:
        g = widget.geometry
        shown = visible and widget.properties.get("visible", True) is not False
        x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
        yield widget, (x, y, float(g.get("width", 0)), float(g.get("height", 0))), shown
        yield from _walk(widget.children, x, y, shown)


def _bound(widget, properties=None):
    return any((properties is None or prop in properties) and
               (str(binding.tag).strip() or str(binding.expr).strip())
               for prop, binding in widget.bindings.items())


def _valid_reference_box(value):
    """Validate without the compiler's forgiving clamping/fallback behavior."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    try:
        box = [float(v) for v in value]
    except (ValueError, TypeError):
        return False
    if not all(math.isfinite(v) for v in box):
        return False
    scale = 1000 if max(box) > 1.5 else 1
    left, top, right, bottom = (v / scale for v in box)
    return 0 <= left < right <= 1 and 0 <= top < bottom <= 1


def audit_reference(project, registry=None, *, require_measured=False) -> ReferenceAudit:
    """Audit a DesignerProject without changing it or querying any device.

    Known readout types require a binding; ordinary static Text does not. A
    disabled control is not flagged as a missing action. Images are reported
    as diagram candidates only by a semantic label or substantial screen area,
    so a small logo is not treated as nonfunctional process equipment.
    """
    if registry is None:
        from designer.palette.widget_registry import default_registry
        registry = default_registry()
    issues = []
    counts = {"widgets": 0, "bound_widgets": 0, "interactive_controls": 0,
              "controls_with_actions": 0, "images": 0, "diagram_images": 0}
    width, height = project.screen.width, project.screen.height

    def add(kind, severity, page, widget, message):
        issues.append(ReferenceIssue(kind, severity, page, widget, message))

    if not project.pages or not any(page.widgets for page in project.pages):
        add("empty_design", "error", "", "", "The design has no widgets.")
    # Reuse the model's signal, action target, tag and property validation.
    for issue in project.validate(registry):
        add("invalid_configuration", "error", "", "", str(issue))

    for page in project.pages:
        checked_metadata = set()
        missing_reference = []
        for widget, rect, shown in _walk(page.widgets):
            counts["widgets"] += 1
            counts["bound_widgets"] += int(_bound(widget))
            if not shown:
                continue
            reference = widget.properties.get("_reference")
            if require_measured and not (isinstance(reference, dict) and
                                         reference.get("layout") == "measured"):
                missing_reference.append(widget.id)
            if isinstance(reference, dict) and reference.get("layout") == "measured":
                if not _valid_reference_box(widget.properties.get("_wbox")):
                    add("missing_measured_box", "error", page.id, widget.id,
                        f"{widget.id} lacks a valid individual reference box; section fallback "
                        "or unchanged geometry does not establish its position in the image.")
                signature = repr(reference)
                if signature not in checked_metadata:
                    checked_metadata.add(signature)
                    if reference.get("coordinateScaleInference"):
                        add("inferred_coordinate_scale", "warning", page.id, "",
                            str(reference["coordinateScaleInference"]) + "; inspect the rendered positions.")
                    try:
                        size_valid = all(math.isfinite(float(reference[key])) and
                                         float(reference[key]) > 0 for key in ("width", "height"))
                    except (KeyError, TypeError, ValueError):
                        size_valid = False
                    if not size_valid:
                        add("invalid_reference_size", "error", page.id, widget.id,
                            "Measured reference source width and height must be finite positive "
                            "numbers; assuming the target aspect ratio cannot preserve the image.")
                    if not _valid_reference_box(reference.get("viewport")):
                        add("invalid_reference_viewport", "error", page.id, widget.id,
                            "Measured reference viewport must be an ordered box within the source "
                            "image; a full-image fallback has not verified the content boundary.")
            x, y, w, h = rect
            if (not all(math.isfinite(v) for v in rect) or w <= 0 or h <= 0 or
                    x < 0 or y < 0 or x + w > width + 0.5 or y + h > height + 0.5):
                add("bounds", "error", page.id, widget.id,
                    f"{widget.id} has invalid geometry or extends beyond the screen.")
            definition = registry.get(widget.type)
            enabled = widget.properties.get("enabled", True) is not False
            if widget.type in _CONTROLS and enabled:
                counts["interactive_controls"] += 1
                signals = definition.action_signals if definition else ()
                has_action = any(signal in signals and action.kind
                                 for signal, action in widget.actions.items())
                counts["controls_with_actions"] += int(has_action)
                if not has_action:
                    add("missing_action", "error", page.id, widget.id,
                        f"{widget.id} is an enabled control with no supported action; "
                        "choose its behavior in the action editor.")
                state = definition.state_property if definition else ""
                if state and not _bound(widget, (state,)):
                    add("missing_state_binding", "warning", page.id, widget.id,
                        f"{widget.id} has no {state} binding; its displayed state is local only.")
            if widget.type in _READOUTS and not _bound(widget, _READOUTS[widget.type]):
                add("missing_live_binding", "error", page.id, widget.id,
                    f"{widget.id} is a static reading; bind it to a simulated or real tag.")
            if widget.type in _PICTURES:
                counts["images"] += 1
                description = " ".join(str(widget.properties.get(k, ""))
                                       for k in ("label", "title", "source")) + " " + widget.id
                description = re.sub(r"([a-z])([A-Z])", r"\1 \2", description).replace("_", " ")
                crop = widget.properties.get("_crop")
                if (isinstance(crop, (list, tuple)) and len(crop) == 4
                        and all(isinstance(v, (int, float)) for v in crop)
                        and crop[0] <= .02 and crop[1] <= .02 and crop[2] >= .98 and crop[3] >= .98
                        and w * h >= width * height * .1):
                    add("screenshot_substitution", "error", page.id, widget.id,
                        f"{widget.id} uses the whole reference as artwork. Crop only its decorative "
                        "region and keep controls/readings as separate widgets.")
                if _DIAGRAM.search(description) or w * h >= width * height * 0.15:
                    counts["diagram_images"] += 1
                    add("raster_diagram", "warning", page.id, widget.id,
                        f"{widget.id} is an image, not individually editable equipment. "
                        "Any embedded readings or controls are static artwork.")
        if missing_reference:
            names = ", ".join(missing_reference[:5])
            suffix = f" and {len(missing_reference) - 5} more" if len(missing_reference) > 5 else ""
            add("missing_reference_geometry", "error", page.id, "",
                f"Page {page.id} has widgets without measured reference metadata: {names}{suffix}. "
                "Return page reference layout=measured, source width/height/viewport, and an "
                "individual box for every widget; a generic layout does not establish image fidelity.")
        # Existing text measurement is deliberately approximate and remains a
        # warning; do not reinterpret repeated labels as configuration errors.
        from .ai_review import layout_findings
        for finding in layout_findings(project, page, registry):
            if finding["kind"] == "clipped":
                add("text_fit_estimate", "warning", page.id,
                    finding["ids"][0], finding["message"] + " (estimated; inspect the render)")
    return ReferenceAudit(tuple(issues), counts)
