"""Compile OCR measurements and semantic classifications, never model layout guesses.

The screenshot supplies text/geometry/style. The model supplies only intent.
Simulation tags are deliberately namespaced: a screenshot cannot authorize plant IO.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from PIL import ImageFont

from designer.model.project import DesignerProject


GROUNDING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "elements": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "ocr_id": {"type": "string"},
                "role": {"type": "string", "enum": ["static", "readout", "button", "toggle"]},
                "tag": {"type": "string"}, "unit": {"type": "string"},
                "action": {"type": "string", "enum": ["disabled", "navigate_main", "simulate_toggle"]},
                "checked": {"type": "boolean"},
            }, "required": ["ocr_id", "role"]}},
        "artwork": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"id": {"type": "string"}, "box": {
                "type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}},
            "required": ["id", "box"]}},
    }, "required": ["elements", "artwork"],
}


def grounding_prompt(ocr_doc: dict) -> str:
    lines = [{k: line[k] for k in ("id", "text", "box") if k in line}
             for line in ocr_doc.get("lines", [])]
    return (
        "Classify the screenshot's OCR lines. Return JSON matching the schema. "
        "Reference ocr_id exactly; do not rewrite text or supply text coordinates. "
        "Every line remains visible and editable. static=labels, units, dates, equipment IDs; "
        "readout=one numeric process reading, possibly with prefix or suffix. "
        "Use meaningful dotted tags for related readouts; the compiler namespaces them for simulation. "
        "button/toggle=actual visible controls only. action defaults to disabled. "
        "navigate_main is permitted only for the current overview; never invent destination pages. "
        "simulate_toggle changes a local simulated boolean, never plant equipment. "
        "Use it only where a genuine boolean control is visible. Do not classify decorative statuses as controls. "
        "artwork optionally identifies decorative nontext regions using PIXEL [x,y,width,height]; "
        "never include text or readings in artwork. No screenshot-specific assumptions. "
        f"Source size: {ocr_doc['width']}x{ocr_doc['height']}. OCR:\n"
        + json.dumps(lines, ensure_ascii=False, separators=(",", ":"))
    )


def _box(value, width, height):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("OCR box must be [x,y,width,height]")
    x, y, w, h = map(float, value)
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError("OCR box must be finite and have positive size")
    if x < 0 or y < 0 or x + w > width + 1 or y + h > height + 1:
        raise ValueError("OCR box lies outside the source")
    return x, y, min(w, width - x), min(h, height - y)


def _tag(raw, index):
    parts = re.findall(r"[a-z0-9_]+", str(raw).lower())
    if parts and parts[0] == "sim":
        parts.pop(0)
    return "sim." + (".".join(parts) if parts else f"reading_{index}")


class NumericReading(NamedTuple):
    match: re.Match
    sample: float
    decimals: int


# Group separators are accepted only in groups of exactly three digits.
# Spaces around a comma account for OCR token spacing without accepting a
# decimal comma (ambiguous locale) or ranges/two unrelated numeric values.
_NUMBER = re.compile(r"[-+\u2212]?(?:\d{1,3}(?:(?:[ \t\u00a0\u202f]*,[ \t\u00a0\u202f]*|[ \t\u00a0\u202f]+)\d{3})+|\d+)(?:\.\d+)?")


def numeric_reading(text: str) -> NumericReading | None:
    """Return one unambiguous numeric sample and its ORIGINAL source span.

    ``1,050``, ``1 ,050`` and ``1 050`` mean 1050. Prefix/suffix are
    untouched for binding format construction. Multiple numbers return None.
    """
    matches = list(_NUMBER.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    token = re.sub(r"[,\s]", "", match.group()).replace("\u2212", "-")
    sample = float(token)
    if not math.isfinite(sample):
        return None
    return NumericReading(match, sample, len(token.split(".")[1]) if "." in token else 0)


@lru_cache(maxsize=256)
def _text_font(size, bold):
    filename = "Inter-Bold.ttf" if bold else "Inter-Regular.ttf"
    return ImageFont.truetype(str(Path(__file__).resolve().parents[2] / "ui/qml/Shadcn/fonts" / filename), size)


def _text_layout(box, text, font_size, bold, scale, source_width, source_height):
    """OCR bounds enclose ink; native labels need the full font line box.

    Measure at actual output pixel size to include rounding at small sizes.
    Keep the visible ink's origin at the detected source origin, rather than
    placing the font's ascender space inside the OCR rectangle and clipping it.
    """
    font = _text_font(max(4, round(font_size * scale)), bold)
    left, top, right, bottom = font.getbbox(text or " ")
    ascent, descent = font.getmetrics()
    x, y, w, h = box
    x0, y0 = max(0, x - left / scale), max(0, y - top / scale)
    x1 = min(source_width, max(x + w, x0 + (max(right, font.getlength(text)) + 2) / scale))
    y1 = min(source_height, max(y + h, y0 + (max(ascent + descent, bottom) + 2) / scale))
    return x0, y0, x1 - x0, y1 - y0


def compile_grounded_reference(ocr_doc: dict, annotations: dict,
                               target_width=1024, target_height=768):
    """Return ``(DesignerProject, report)`` with complete source-text coverage.

    Unknown/duplicate annotations are reported and cannot alter authoritative OCR.
    Invalid source measurements raise ValueError instead of producing fake geometry.
    """
    width, height = float(ocr_doc["width"]), float(ocr_doc["height"])
    if not all(math.isfinite(v) and v > 0 for v in (width, height, target_width, target_height)):
        raise ValueError("Source and target dimensions must be positive and finite")
    lines = ocr_doc.get("lines", [])
    ids = [str(line["id"]) for line in lines]
    if len(ids) != len(set(ids)):
        raise ValueError("OCR IDs must be unique")
    report = {"source_text_count": len(lines), "covered_ocr_ids": ids,
              "warnings": [], "unresolved": [], "simulation_defaults": {},
              "artwork_remains_raster": bool(ocr_doc.get("backing_asset")),
              "visual_match_verified": False, "runtime_verified": False}
    semantic = {}
    for item in annotations.get("elements", []):
        key = str(item.get("ocr_id", ""))
        if key not in ids or key in semantic:
            report["warnings"].append(f"Ignored unknown or duplicate annotation {key!r}")
        else:
            semantic[key] = item
    scale = min(target_width / width, target_height / height)
    dx, dy = (target_width - width * scale) / 2, (target_height - height * scale) / 2
    reference = {"layout": "measured", "width": width, "height": height, "viewport": [0, 0, 1000, 1000]}
    widgets = []

    def widget(kind, ident, box, props, **extra):
        x, y, w, h = box
        props.update({"_reference": dict(reference), "_wbox": [x / width, y / height, (x + w) / width, (y + h) / height]})
        widgets.append({"type": kind, "id": ident,
                        "geometry": {"x": dx + x * scale, "y": dy + y * scale,
                                     "width": w * scale, "height": h * scale},
                        "properties": props, **extra})

    if ocr_doc.get("backing_asset"):
        widget("Image", "reference_artwork", (0, 0, width, height), {
            "source": ocr_doc["backing_asset"], "fillMode": "Image.Stretch", "smooth": True,
            "_referenceArtworkCleaned": True, "_sourceTextCount": len(lines)})
    for i, panel in enumerate(ocr_doc.get("panels", [])):
        widget("Rectangle", f"panel_{i}", _box(panel["box"], width, height), {
            "color": panel.get("color", "transparent"), "radius": round(float(panel.get("radius", 0)) * scale),
            "borderWidth": 0})
    for i, line in enumerate(lines):
        key, text = str(line["id"]), str(line["text"])
        box = _box(line["box"], width, height)
        item = semantic.get(key, {})
        role = item.get("role", "static")
        color = line.get("color", line.get("foreground", "#182435"))
        font_size = float(line.get("font_size", line.get("fontSize", box[3])))
        source_box = box
        box = _text_layout(box, text, font_size, bool(line.get("bold", False)), scale, width, height)
        props = {"text": text, "color": color, "fontSize": max(1, round(font_size * scale)),
                 "bold": bool(line.get("bold", False)), "wrapMode": "Text.NoWrap",
                 "verticalAlignment": "Text.AlignTop", "_ocrIds": [key], "_ocrBox": list(source_box),
                 "_referenceMetrics": {"fontSize": font_size}, "_semanticRole": role}
        bindings, actions, kind = {}, {}, "Text"
        if role == "readout":
            # More than one number is ambiguous (ranges, timestamps, equipment IDs).
            reading = numeric_reading(text)
            if reading is not None:
                match, sample, decimals = reading
                tag = _tag(item.get("tag"), i)
                props["_simulationSample"] = sample
                props["_simulationDecimals"] = decimals
                bindings["text"] = {"tag": tag, "format": text[:match.start()] + "%1" + text[match.end():],
                                    "decimals": decimals, "sim": "number"}
                default = {"value": sample, "type": "number", "source_ocr_id": key}
                old = report["simulation_defaults"].get(tag)
                if old and (old["type"] != "number" or old["value"] != sample):
                    tag = f"{tag}.reading_{i}"
                    bindings["text"]["tag"] = tag
                    report["warnings"].append(f"Conflicting samples split into {tag}")
                report["simulation_defaults"][tag] = default
            else:
                report["unresolved"].append(f"{key}: readout needs exactly one numeric token")
        elif role in ("button", "toggle"):
            text_props, text_box = dict(props), box
            box = source_box
            kind = "ShButton"
            action = item.get("action", "disabled")
            if action == "navigate_main":
                actions["clicked"] = {"kind": "navigate", "page": "main"}
            elif action == "simulate_toggle":
                tag = _tag(item.get("tag"), i)
                old = report["simulation_defaults"].get(tag)
                if old and old["type"] != "bool":
                    tag = f"{tag}.control_{i}"
                    report["warnings"].append(f"Conflicting simulation types split into {tag}")
                actions["clicked"] = {"kind": "toggle", "tag": tag}
                report["simulation_defaults"][tag] = {"value": bool(item.get("checked", False)), "type": "bool", "source_ocr_id": key}
            else:
                report["unresolved"].append(f"{key}: control disabled; behavior not established")
            props = {"text": "", "variant": "ghost", "textColor": color,
                     "backgroundColor": line.get("background", "transparent"),
                     "enabled": bool(actions), "cornerRadius": 3,
                     "_controlOcrIds": [key], "_semanticRole": role}
            if action == "simulate_toggle":
                props["_simulationDefaults"] = {tag: bool(item.get("checked", False))}
            x, y, w, h = box
            pad = min(5, h * .2)
            box = (max(0, x - pad), max(0, y - pad), min(width, x + w + pad) - max(0, x - pad),
                   min(height, y + h + pad) - max(0, y - pad))
        widget(kind, f"ocr_{i}", box, props, bindings=bindings, actions=actions)
        if role in ("button", "toggle"):
            # Both kits otherwise use a fixed button font. A plain Text above
            # the empty hit target preserves measured size and source ownership.
            widget("Text", f"ocr_{i}_caption", text_box, text_props)
    report["annotated_ocr_count"] = len(semantic)
    report["artwork_regions"] = annotations.get("artwork", [])
    project = DesignerProject.from_dict({"name": "Image reconstruction", "screen": {
        "width": target_width, "height": target_height, "theme": ocr_doc.get("theme", "light"),
        "background": ocr_doc.get("background", "#eef3f8")},
        "pages": [{"id": "main", "name": "Overview", "widgets": widgets}]})
    return project, report
