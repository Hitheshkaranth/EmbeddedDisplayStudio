"""Shared reference-image guidance and durable build evidence for Studio/CLI."""
from __future__ import annotations

import base64
import json
from pathlib import Path


def prepare_reference_images(references):
    """Remove a confidently detected device bezel from the primary reference.

    Return new attachments without changing the user's file. Generation, asset
    crops and review must all use this same returned list/coordinate system.
    Ambiguous or dark screenshots remain unchanged.
    """
    result = list(references or [])
    if not result:
        return result
    from PySide6.QtGui import QImage
    from designer.layout.palette import reference_content_rect
    from tools.hmi_deployer.ai_design import encode_brief_image
    image = QImage.fromData(base64.b64decode(result[0].data))
    if image.isNull():
        return result
    left, top, right, bottom = reference_content_rect(image)
    if (left, top, right, bottom) != (0, 0, image.width(), image.height()):
        result[0] = encode_brief_image(image.copy(left, top, right-left, bottom-top),
                                       "reference-content.png")
    return result


def reference_geometry_hint(references) -> str:
    """Give vision the same coordinate system used by cropping and compilation."""
    if not references:
        return ""
    from PySide6.QtGui import QImage
    from designer.layout.palette import reference_content_rect
    image = QImage.fromData(base64.b64decode(references[0].data))
    if image.isNull():
        return ""
    width, height = image.width(), image.height()
    rect = reference_content_rect(image)
    viewport = [round(value * 1000 / extent, 2)
                for value, extent in zip(rect, (width, height, width, height))]
    metadata = {"layout": "measured", "width": width, "height": height,
                "viewport": viewport}
    return (
        "Reference reproduction contract: preserve the first image's composition, labels, "
        "theme and all visible sections. Use this page reference metadata (the viewport is "
        "a conservative suggestion; adjust only if the image shows a different screen boundary): "
        + json.dumps(metadata) + ". All widget boxes and artwork crops use 0..1000 "
        "coordinates relative to the FULL first image, including its outer frame. "
        "Give every widget its own box. The compiler uniformly fits the content viewport "
        "to the target without stretching it. Recreate controls and changing readings as "
        "editable widgets with valid actions and bindings; never use the full screenshot "
        "as the application. A picture cannot reveal PLC addresses: use descriptive simulated "
        "tags and do not invent a verified hardware connection. Artwork may be a crop, "
        "but process controls, states and values must remain separate editable widgets."
    )


def save_reference_audit(project, bundle_dir=None, registry=None):
    """Audit configuration only; never claim rendering or hardware was verified."""
    from tools.hmi_deployer.reference_audit import audit_reference
    audit = audit_reference(project, registry, require_measured=True)
    if bundle_dir:
        folder = Path(bundle_dir)
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / "reference-audit.json"
        temporary = folder / "reference-audit.json.tmp"
        temporary.write_text(json.dumps(audit.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)
    return audit
