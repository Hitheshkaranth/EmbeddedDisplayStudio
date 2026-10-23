"""Measured reference text using Windows' installed OCR engine.

Boxes are source-image pixel [x, y, width, height] coordinates. Confidence
is null because Windows.Media.Ocr does not provide recognition confidence.
Recognition is evidence, not verified transcription: spelling can be wrong.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile

from PIL import Image, ImageOps


class ReferenceOCRError(RuntimeError):
    """OCR unavailable, invalid input, or native recognition failed."""


def _native_ocr(path: Path, timeout: float) -> dict:
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.name != "nt" or not executable.is_file():
        raise ReferenceOCRError("Reference OCR requires Windows.Media.Ocr and an installed OCR language pack.")
    try:
        process = subprocess.run(
            [str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(Path(__file__).with_suffix(".ps1")), "-ImagePath", str(path.resolve())],
            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReferenceOCRError(f"Native OCR failed: {exc}") from exc
    if process.returncode:
        raise ReferenceOCRError(f"Windows OCR failed: {process.stderr.strip() or process.stdout.strip()}")
    try:
        result = json.loads(process.stdout.lstrip("\ufeff"))
        if not isinstance(result.get("lines"), list):
            raise ValueError("Missing OCR lines")
        return result
    except (ValueError, AttributeError) as exc:
        raise ReferenceOCRError("Windows OCR returned invalid JSON evidence") from exc


def _overlap(a: list[float], b: list[float]) -> float:
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return intersection / smaller if smaller > 0 else 0


def _merge_passes(passes: list[tuple[dict, float, int, int]], width: int, height: int) -> list[dict]:
    """Keep first recognition of a spatial word; tile passes add missed words."""
    seen: list[dict] = []
    lines = []
    for result, scale, offset_x, offset_y in passes:
        for line in result["lines"]:
            words = []
            for word in line.get("words", []):
                raw = word["box"]
                box = [round(raw[0] / scale + offset_x, 2), round(raw[1] / scale + offset_y, 2),
                       round(raw[2] / scale + offset_x, 2), round(raw[3] / scale + offset_y, 2)]
                box = [max(0, min(width if i % 2 == 0 else height, value)) for i, value in enumerate(box)]
                if box[2] <= box[0] or box[3] <= box[1] or not word.get("text", "").strip():
                    continue
                if any(_overlap(box, previous["box"]) > .65 for previous in seen):
                    continue
                item = {"id": f"word_{len(seen) + 1:04d}", "text": word["text"], "box": box, "confidence": None}
                seen.append(item)
                words.append(item)
            for run in _spatial_runs(words):
                lines.append({"id": f"line_{len(lines) + 1:04d}", "text": " ".join(word["text"] for word in run),
                              "box": [min(w["box"][0] for w in run), min(w["box"][1] for w in run),
                                      max(w["box"][2] for w in run), max(w["box"][3] for w in run)],
                              "confidence": None, "words": run})
    return sorted(lines, key=lambda line: (line["box"][1], line["box"][0]))


def _spatial_runs(words: list[dict]) -> list[list[dict]]:
    """Split OCR lines spanning independent columns, using measured gaps.

    Native OCR sometimes combines a caption, readout and unrelated next-panel
    words into one line. Wide gutters always split; a shorter gap before a
    numeric readout splits once it exceeds 0.8 glyph heights. Ordinary dates,
    units and numeric ranges retain their normal inter-word spacing.
    Input boxes are internal xyxy, before public serialization to xywh.
    """
    if not words:
        return []
    glyph_height = statistics.median(w["box"][3] - w["box"][1] for w in words)
    runs = [[words[0]]]
    for word in words[1:]:
        previous = runs[-1][-1]
        gap = word["box"][0] - previous["box"][2]
        numeric_start = bool(re.match(r"^[+−-]?\d", word["text"]))
        previous_numeric = bool(re.match(r"^[+−-]?\d", previous["text"]))
        different_baseline = abs(word["box"][3] - previous["box"][3]) > glyph_height * .8
        if gap > max(24, glyph_height * 2) or different_baseline or (
            numeric_start and not previous_numeric and gap > max(6, glyph_height * .8)
        ):
            runs.append([word])
        else:
            runs[-1].append(word)
    return runs


def extract_ocr(image_path: str | Path, *, tiled: bool = True, timeout: float = 30) -> dict:
    """Recognize text without a model or screen-specific coordinates.

    Uses a full-image pass (bounded to 2400px) and, by default, overlapping
    768px tiles enlarged 2x to improve dense dashboard label recall.
    ``timeout`` applies to each native call. Raises ReferenceOCRError instead
    of silently pretending missing OCR evidence succeeded.
    """
    path = Path(image_path)
    try:
        with Image.open(path) as source:
            picture = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ReferenceOCRError(f"Cannot read reference image: {path}") from exc
    width, height = picture.size
    passes = []
    with tempfile.TemporaryDirectory(prefix="reference-ocr-") as directory:
        temporary = Path(directory) / "input.png"
        scale = min(1.0, 2400 / max(width, height))
        full = picture.resize((max(1, round(width * scale)), max(1, round(height * scale))))
        full.save(temporary)
        first = _native_ocr(temporary, timeout)
        passes.append((first, scale, 0, 0))
        if tiled and (width > 768 or height > 768):
            for y in range(0, height, 640):
                for x in range(0, width, 640):
                    tile = picture.crop((x, y, min(x + 768, width), min(y + 768, height)))
                    if tile.width < 64 or tile.height < 64:
                        continue
                    tile.resize((tile.width * 2, tile.height * 2), Image.Resampling.LANCZOS).save(temporary)
                    passes.append((_native_ocr(temporary, timeout), 2., x, y))
    lines = _merge_passes(passes, width, height)
    for line in lines:
        for item in [line, *line["words"]]:
            x, y, right, bottom = item["box"]
            item["box"] = [x, y, round(right - x, 2), round(bottom - y, 2)]
    return {"schema": 1, "engine": "windows.media.ocr", "box_format": "xywh", "width": width, "height": height,
            "language": first.get("language"), "confidence": None, "passes": len(passes),
            "lines": lines}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-tiles", action="store_true")
    args = parser.parse_args()
    evidence = extract_ocr(args.image, tiled=not args.no_tiles)
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
