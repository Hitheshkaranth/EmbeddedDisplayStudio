"""Measurable OCR reconstruction gates; never a pixel-perfect certification.

OCR is incomplete evidence. Passing these gates means detected text survived at
its measured position and the model is valid, not that the entire image was
understood or that controls are connected to real equipment.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import unicodedata


def _text(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).casefold()


def _box(value):
    try:
        values = tuple(float(v) for v in value)
        return values if len(values) == 4 and all(math.isfinite(v) for v in values) and min(values[2:]) > 0 else None
    except (TypeError, ValueError):
        return None


def _walk(widgets, ox=0, oy=0, visible=True):
    for widget in widgets:
        g = widget.geometry
        box = _box([g.get(k) for k in ("x", "y", "width", "height")])
        shown = visible and widget.properties.get("visible", True) is not False
        absolute = (box[0] + ox, box[1] + oy, box[2], box[3]) if box else None
        yield widget, absolute, shown
        yield from _walk(widget.children, absolute[0] if absolute else ox,
                         absolute[1] if absolute else oy, shown)


def pixel_diagnostics(reference_image, rendered_image):
    """Report same-coordinate RGB error without inventing a similarity cutoff."""
    result = {"available": False, "certifies_visual_match": False}
    if reference_image is None or rendered_image is None:
        return result
    if reference_image.isNull() or rendered_image.isNull():
        return dict(result, reason="An image could not be decoded.")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    # The compiler preserves source aspect ratio and centers it on the target.
    # Exclude target letterboxing instead of stretching it into source pixels.
    scale = min(rendered_image.width()/reference_image.width(),
                rendered_image.height()/reference_image.height())
    viewport_width = max(1, round(reference_image.width()*scale))
    viewport_height = max(1, round(reference_image.height()*scale))
    viewport_x = round((rendered_image.width()-viewport_width)/2)
    viewport_y = round((rendered_image.height()-viewport_height)/2)
    viewport = [viewport_x, viewport_y, viewport_width, viewport_height]
    content = rendered_image.copy(*viewport)
    # Bound work; both images get exactly the same sampling transform.
    size = reference_image.size().scaled(320, 320, Qt.KeepAspectRatio)
    a = reference_image.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
    b = content.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
    diffs = []
    for y in range(a.height()):
        for x in range(a.width()):
            ac, bc = a.pixelColor(x, y), b.pixelColor(x, y)
            diffs.extend(abs(u-v) for u, v in zip(ac.getRgb()[:3], bc.getRgb()[:3]))
    aspect_error = abs((reference_image.width()/reference_image.height()) /
                       (rendered_image.width()/rendered_image.height()) - 1)
    return dict(result, available=True, reference_size=[reference_image.width(), reference_image.height()],
                rendered_size=[rendered_image.width(), rendered_image.height()],
                rendered_content_viewport_xywh=viewport,
                sample_size=[a.width(), a.height()], aspect_ratio_relative_error=aspect_error,
                mean_absolute_rgb_error=sum(diffs)/(255*len(diffs)),
                root_mean_square_rgb_error=math.sqrt(sum(d*d for d in diffs)/len(diffs))/255,
                note="Centered aspect-fit content RGB diagnostics; target letterboxing excluded. Inspect text, assets and interaction separately. No universal pass threshold.")


def evaluate_reference(ocr, project, reference_image=None, rendered_image=None, *, registry=None):
    """Evaluate persisted OCR ownership, visible text, geometry and configuration.

    Geometry uses source pixels uniformly fitted and centered in the screen. A
    widget must contain its OCR union within max(4px, 25% line height), and its
    area must be <= 12x that union; these are declared reconstruction tolerances,
    not perceptual similarity thresholds. Multi-line owners concatenate text in
    OCR order. Text-bearing properties are inspected, never private metadata.
    """
    from .reference_audit import audit_reference
    issues = []
    def issue(gate, code, message, **extra):
        issues.append(dict(gate=gate, code=code, message=message, **extra))
    try:
        sw, sh = float(ocr["width"]), float(ocr["height"])
        valid_size = math.isfinite(sw) and math.isfinite(sh) and min(sw, sh) > 0
    except (KeyError, TypeError, ValueError):
        sw = sh = 0
        valid_size = False
    if not valid_size:
        issue("source", "invalid_source_size", "OCR needs positive finite source dimensions.")
    lines = {}
    for line in ocr.get("lines", []):
        identity = str(line.get("id", ""))
        box = _box(line.get("box", []))
        if not identity or identity in lines or not box or not _text(line.get("text", "")):
            issue("source", "invalid_ocr_line", "OCR lines require unique IDs, nonempty text and valid pixel boxes.", ocr_id=identity)
            continue
        lines[identity] = line
        if valid_size and (min(box[:2]) < 0 or box[0]+box[2] > sw+1 or box[1]+box[3] > sh+1):
            issue("source", "source_box_outside", "OCR line extends beyond source.", ocr_id=identity)
    if not lines:
        issue("source", "empty_ocr", "No detected text: reconstruction cannot be accepted automatically.")
    owners = {}
    pw, ph = project.screen.width, project.screen.height
    scale = min(pw/sw, ph/sh) if valid_size else 1
    offset_x, offset_y = (pw-sw*scale)/2, (ph-sh*scale)/2
    raster_artwork = []
    for page in project.pages:
        for widget, box, shown in _walk(page.widgets):
            ids = widget.properties.get("_ocrIds", [])
            if not isinstance(ids, list):
                issue("coverage", "invalid_ocr_ids", "_ocrIds must be a list.", widget_id=widget.id)
                ids = []
            ids = [str(i) for i in ids]
            for identity in ids:
                owners.setdefault(identity, []).append(widget.id)
                if identity not in lines:
                    issue("coverage", "unknown_ocr_id", "Widget claims unknown OCR identity.", widget_id=widget.id, ocr_id=identity)
            if not box:
                issue("geometry", "invalid_widget_bounds", "Widget is missing finite positive bounds.", widget_id=widget.id)
                continue
            x, y, w, h = box
            if shown and (x < -1 or y < -1 or x+w > pw+1 or y+h > ph+1):
                issue("geometry", "widget_outside", "Visible widget extends beyond screen.", widget_id=widget.id)
            if shown and widget.type in {"Image", "ShAnimatedImage"} and w*h >= .9*pw*ph:
                if widget.properties.get("_referenceArtworkCleaned") is True:
                    raster_artwork.append(widget.id)
                else:
                    issue("editable_content", "screen_sized_raster", "Uncleaned screen-sized raster cannot certify editable reconstruction.", widget_id=widget.id)
            known = [lines[i] for i in ids if i in lines]
            if not known:
                continue
            if not shown or widget.type in {"Image", "ShAnimatedImage"}:
                issue("coverage", "nontext_owner", "OCR text must belong to a visible native text-bearing widget.", widget_id=widget.id)
            text_parts = [_text(widget.properties[k]) for k in
                          ("text", "title", "label", "value", "unit", "subtitle", "description")
                          if k in widget.properties]
            rendered_text = "".join(text_parts)
            expected_text = "".join(_text(line["text"]) for line in known)
            if expected_text != rendered_text and expected_text not in text_parts:
                issue("text", "changed_source_text", "Visible properties do not preserve owned OCR text.", widget_id=widget.id, expected=expected_text)
            if valid_size:
                boxes = [_box(line["box"]) for line in known]
                left = min(b[0] for b in boxes)*scale+offset_x
                top = min(b[1] for b in boxes)*scale+offset_y
                right = max(b[0]+b[2] for b in boxes)*scale+offset_x
                bottom = max(b[1]+b[3] for b in boxes)*scale+offset_y
                tolerance = max(4, .25*max(b[3] for b in boxes)*scale)
                if left < x-tolerance or top < y-tolerance or right > x+w+tolerance or bottom > y+h+tolerance:
                    issue("geometry", "ocr_geometry_mismatch", "Widget does not contain its scaled OCR bounds within declared tolerance.", widget_id=widget.id)
                if w*h > 12*(right-left)*(bottom-top):
                    issue("geometry", "excessive_owner_area", "Text owner is over 12 times the detected text area.", widget_id=widget.id)
    for identity in lines:
        if identity not in owners:
            issue("coverage", "missing_ocr_id", "Detected source text has no persisted native owner.", ocr_id=identity)
        elif len(owners[identity]) != 1:
            issue("coverage", "duplicate_ocr_owner", "OCR identity must have exactly one owner.", ocr_id=identity)
    try:
        audit = audit_reference(project, registry)
        audit_report = audit.to_dict()
        for item in audit.issues:
            if item.severity == "error":
                issue("configuration", item.kind, item.message, widget_id=item.widget_id)
    except (TypeError, ValueError, OverflowError) as error:
        issue("configuration", "audit_failed", "Invalid model prevented configuration audit: " + str(error))
        audit_report = {"configuration_ready": False, "error": str(error)}
    gates = {name: not any(i["gate"] == name for i in issues) for name in
             ("source", "coverage", "text", "geometry", "editable_content", "configuration")}
    return {"schema": 1, "passed": all(gates.values()), "gates": gates,
            "acceptance_scope": "Detected OCR text reconstruction and static configuration only",
            "visual_match_verified": False, "runtime_verified": False, "deployment_verified": False,
            "source_text_count": len(lines), "owned_source_text_count": sum(i in owners for i in lines),
            "raster_artwork_widgets": raster_artwork,
            "artwork_note": "Cleaned raster artwork remains an illustration; cleaning metadata is a pipeline assertion, not independent proof of text removal.",
            "issues": issues, "configuration_audit": audit_report,
            "pixel_evidence": pixel_diagnostics(reference_image, rendered_image),
            "recommendation": "Review native render against reference; establish a human-approved baseline and test interaction before deployment."}


def save_acceptance_report(report, path):
    """Atomically persist the exact evidence reviewed by the caller."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    return target
