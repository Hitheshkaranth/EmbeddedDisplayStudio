"""Independent OCR check of rendered text, not a whole-image fidelity claim."""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re
import tempfile
import unicodedata

from PIL import Image

try:
    from .reference_ocr import extract_ocr
except ImportError:
    from reference_ocr import extract_ocr


def _normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())


def _numbers(text: str) -> list[str]:
    return re.findall(r"(?<![\w.])\d+(?:[.,]\d+)*", text)


def compare_rendered_ocr(source_ocr: dict, rendered_ocr: dict, target_width: int, target_height: int) -> dict:
    """Compare independent OCR documents using scaled spatial word matches.

    Default thresholds: 90% character-weighted recall, 85% line recall, and
    90% exact numeric-line recall. Individual lines need 80% character and
    token agreement. OCR uncertainty is reported rather than called a proven
    rendering defect; the result is a screening gate requiring inspection.
    """
    if source_ocr.get("box_format") != "xywh" or rendered_ocr.get("box_format") != "xywh":
        raise ValueError("Render text checking requires xywh OCR boxes")
    if (rendered_ocr["width"], rendered_ocr["height"]) != (target_width, target_height):
        raise ValueError("Rendered image dimensions differ from the declared target")
    # Native preview contains the design in its framebuffer, preserving aspect
    # ratio and centering the spare space (the same mapping as the renderer).
    scale = min(target_width / source_ocr["width"], target_height / source_ocr["height"])
    offset_x = (target_width - source_ocr["width"] * scale) / 2
    offset_y = (target_height - source_ocr["height"] * scale) / 2
    rendered_words = [word for line in rendered_ocr["lines"] for word in line.get("words", [])]
    details = []
    ignored = []
    for line in source_ocr["lines"]:
        expected = line.get("text", "")
        normalized = _normalized(expected)
        if not normalized or (len(normalized) == 1 and not normalized.isdigit()):
            ignored.append(line["id"])
            continue
        x, y, width, height = line["box"]
        x, y, width, height = x*scale+offset_x, y*scale+offset_y, width*scale, height*scale
        margin_x, margin_y = max(3, height*.35), max(3, height*.4)
        candidates = []
        for word in rendered_words:
            wx, wy, ww, wh = word["box"]
            cx, cy = wx + ww/2, wy + wh/2
            if x-margin_x <= cx <= x+width+margin_x and y-margin_y <= cy <= y+height+margin_y:
                candidates.append(word)
        candidates.sort(key=lambda word: (round(word["box"][1] / max(1, height)), word["box"][0]))
        observed = " ".join(word["text"] for word in candidates)
        actual = _normalized(observed)
        matcher = SequenceMatcher(None, normalized, actual, autojunk=False)
        matched_characters = sum(block.size for block in matcher.get_matching_blocks())
        char_recall = matched_characters / len(normalized)
        expected_tokens, observed_tokens = _tokens(expected), _tokens(observed)
        unused = list(observed_tokens)
        matched_tokens = 0
        for token in expected_tokens:
            ranked = [(SequenceMatcher(None, token, candidate).ratio(), index) for index, candidate in enumerate(unused)]
            if ranked and max(ranked)[0] >= .8:
                _, index = max(ranked)
                unused.pop(index)
                matched_tokens += 1
        token_recall = matched_tokens / len(expected_tokens) if expected_tokens else 1.
        numbers, actual_numbers = _numbers(expected), _numbers(observed)
        numeric_match = numbers == actual_numbers if numbers else None
        line_pass = char_recall >= .8 and token_recall >= .8 and numeric_match is not False
        source_suspect = "\ufffd" in expected or any(ord(c) < 32 for c in expected)
        details.append({"id": line["id"], "expected": expected, "observed": observed,
                        "target_box": [round(v, 2) for v in (x, y, width, height)],
                        "character_recall": round(char_recall, 4), "token_recall": round(token_recall, 4),
                        "numeric_match": numeric_match, "expected_numbers": numbers, "observed_numbers": actual_numbers,
                        "passed": line_pass, "missing": not bool(actual), "source_suspect": source_suspect,
                        "source_confidence": line.get("confidence"), "expected_characters": len(normalized),
                        "matched_characters": matched_characters})
    total_characters = sum(item["expected_characters"] for item in details)
    recall = sum(item["matched_characters"] for item in details) / max(1, total_characters)
    line_recall = sum(item["passed"] for item in details) / max(1, len(details))
    numeric_lines = [item for item in details if item["numeric_match"] is not None]
    numeric_recall = sum(item["numeric_match"] for item in numeric_lines) / len(numeric_lines) if numeric_lines else 1.
    return {"schema": 1, "scope": "rendered-text-only", "method": "independent-windows-ocr-spatial-comparison",
            "mapping": {"mode": "contain-centered", "scale": scale, "offset_x": offset_x, "offset_y": offset_y},
            "passed": bool(details) and recall >= .9 and line_recall >= .85 and numeric_recall >= .9,
            "recall": round(recall, 4), "line_recall": round(line_recall, 4), "numeric_recall": round(numeric_recall, 4),
            "thresholds": {"character_recall": .9, "line_recall": .85, "numeric_recall": .9,
                           "per_line_character_recall": .8, "per_line_token_recall": .8},
            "source_lines": len(source_ocr["lines"]), "checked_lines": len(details), "ignored_ids": ignored,
            "missing_ids": [item["id"] for item in details if item["missing"]],
            "mismatched_ids": [item["id"] for item in details if not item["passed"] and not item["missing"]],
            "numeric_mismatch_ids": [item["id"] for item in numeric_lines if not item["numeric_match"]],
            "source_suspect_ids": [item["id"] for item in details if item["source_suspect"]],
            "limitations": ["Both source and rendered OCR may misrecognize text; mismatches require review",
                            "Source OCR confidence is unknown when the OCR engine supplies none",
                            "Rasterized text and native text cannot be distinguished by OCR",
                            "Passing does not establish visual fidelity, semantics, or functional behavior"],
            "lines": details}


def check_rendered_text(source_ocr: dict, rendered_path: str | Path, target_width: int, target_height: int) -> dict:
    # Small framebuffer fonts are often missed at native resolution. Enlarge
    # the actual raster, never expected text, then map measured boxes back.
    with Image.open(rendered_path) as image:
        if image.size != (target_width, target_height):
            raise ValueError("Rendered image dimensions differ from the declared target")
        with tempfile.TemporaryDirectory(prefix="render-text-check-") as directory:
            enlarged_path = Path(directory) / "render-2x.png"
            image.convert("RGB").resize((target_width*2, target_height*2), Image.Resampling.LANCZOS).save(enlarged_path)
            rendered = extract_ocr(enlarged_path)
    rendered["width"], rendered["height"] = target_width, target_height
    for line in rendered["lines"]:
        for item in [line, *line["words"]]:
            item["box"] = [value / 2 for value in item["box"]]
    report = compare_rendered_ocr(source_ocr, rendered, target_width, target_height)
    report["render_ocr_preprocess"] = "2x-lanczos; measured coordinates mapped back to framebuffer pixels"
    return report
