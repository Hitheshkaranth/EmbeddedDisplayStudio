"""Generate a disclosed raster artwork backing with OCR text removed.

This is local interpolation, not semantic reconstruction: missed OCR remains
in the artwork and texture/edges behind removed labels cannot be recovered.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageFont, ImageOps


def _font_path() -> Path:
    return Path(__file__).resolve().parents[2] / "ui/qml/Shadcn/fonts/Inter-Regular.ttf"


def _fit_font(text: str, width: float, height: float) -> int:
    font_path = _font_path()
    best, error = 1, float("inf")
    for size in range(1, max(4, min(512, int(height * 2.5) + 5))):
        font = ImageFont.truetype(str(font_path), size)
        box = font.getbbox(text or " ")
        measured_width, measured_height = max(1, box[2] - box[0]), max(1, box[3] - box[1])
        score = abs(np.log(measured_width / max(1, width))) + abs(np.log(measured_height / max(1, height)))
        if score < error:
            best, error = size, score
    return best


def _word_patch(pixels: np.ndarray, box: list[float]):
    height, width = pixels.shape[:2]
    bx, by, bw, bh = box
    x0, y0 = max(0, int(np.floor(bx)) - 2), max(0, int(np.floor(by)) - 2)
    x1, y1 = min(width, int(np.ceil(bx + bw)) + 2), min(height, int(np.ceil(by + bh)) + 2)
    if x1 <= x0 or y1 <= y0:
        return None
    region = pixels[y0:y1, x0:x1].astype(float)
    # Interpolate between opposite border strips in both directions. Their
    # median dampens isolated strokes and supports gently varying backgrounds.
    top = np.median(pixels[max(0, y0 - 2):y0 + 1, x0:x1], axis=0)
    bottom = np.median(pixels[y1 - 1:min(height, y1 + 2), x0:x1], axis=0)
    left = np.median(pixels[y0:y1, max(0, x0 - 2):x0 + 1], axis=1)
    right = np.median(pixels[y0:y1, x1 - 1:min(width, x1 + 2)], axis=1)
    vertical = top[None, :, :] * np.linspace(1, 0, y1-y0)[:, None, None] + bottom[None, :, :] * np.linspace(0, 1, y1-y0)[:, None, None]
    horizontal = left[:, None, :] * np.linspace(1, 0, x1-x0)[None, :, None] + right[:, None, :] * np.linspace(0, 1, x1-x0)[None, :, None]
    background = (vertical + horizontal) / 2
    distance = np.linalg.norm(region - background, axis=2)
    strongest = distance >= max(18, float(np.percentile(distance, 80)))
    foreground = np.median(region[strongest], axis=0) if strongest.any() else np.median(region.reshape(-1, 3), axis=0)
    # Restrict removal to contrasting pixels within OCR boxes, with a one-pixel
    # dilation to catch antialiased stroke edges. No screen-specific regions.
    mask = distance > 18
    mask = np.asarray(Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.MaxFilter(3))) > 0
    return x0, y0, x1, y1, background, mask, foreground


def prepare_backing(source_path: str | Path, ocr_doc: dict, output_dir: str | Path) -> dict:
    """Save assets/reference-artwork.png and mask; return enriched OCR copy.

    Lines gain foreground (#RRGGBB), font_size (source pixels), font_family,
    and typography_source. Original measured boxes and text are preserved.
    ``backing`` records source-derived raster provenance and limitations.
    """
    if ocr_doc.get("box_format") != "xywh":
        raise ValueError("Backing requires OCR box_format='xywh'")
    with Image.open(source_path) as image:
        source = ImageOps.exif_transpose(image).convert("RGB")
    if source.size != (ocr_doc["width"], ocr_doc["height"]):
        raise ValueError("OCR dimensions do not match the source image")
    original = np.asarray(source)
    cleaned = original.copy()
    mask_image = np.zeros(original.shape[:2], dtype=np.uint8)
    document = deepcopy(ocr_doc)
    count = 0
    for line in document.get("lines", []):
        colors = []
        for word in line.get("words", []):
            patch = _word_patch(original, word["box"])
            if patch is None:
                continue
            x0, y0, x1, y1, background, mask, foreground = patch
            cleaned[y0:y1, x0:x1][mask] = np.rint(np.clip(background[mask], 0, 255)).astype("uint8")
            mask_image[y0:y1, x0:x1][mask] = 255
            colors.append(foreground)
            count += 1
        foreground = np.median(colors, axis=0) if colors else np.array([0, 0, 0])
        line["foreground"] = "#" + "".join(f"{int(c):02x}" for c in foreground)
        line["font_size"] = _fit_font(line.get("text", ""), line["box"][2], line["box"][3])
        line["font_family"] = "Inter"
        line["typography_source"] = "source-pixel-contrast-and-Inter-Regular-bbox-fit"
    assets = Path(output_dir) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cleaned).save(assets / "reference-artwork.png")
    Image.fromarray(mask_image).save(assets / "reference-text-mask.png")
    document["backing"] = {
        "path": "assets/reference-artwork.png", "mask_path": "assets/reference-text-mask.png",
        "method": "ocr-word-local-border-interpolation", "source_derived_raster": True,
        "word_boxes_processed": count, "masked_pixels": int(np.count_nonzero(mask_image)),
        "limitations": ["OCR-missed text remains rasterized", "Inpainting cannot recover obscured artwork",
                        "Text over complex edges or textures may leave artifacts", "Font family is an Inter approximation"],
    }
    return document
