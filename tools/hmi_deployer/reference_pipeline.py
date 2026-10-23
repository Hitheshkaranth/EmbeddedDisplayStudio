"""Measured image-to-HMI pipeline shared by AI Designer and repeatable trials.

No reference-specific layouts or prewritten plans enter this path. A source
image provides measurements; a model classifies intent; compilation is local.
"""
from __future__ import annotations

import base64
import json
import re
import tempfile
import time
from pathlib import Path


def _write(folder, name, value):
    (folder / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _annotations(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict) or not isinstance(value.get("elements"), list):
        raise ValueError("Model did not return OCR classifications")
    return value


def generate_reference(connector, brief, model, images, target_width=1024,
                       target_height=768, emit=None, output_dir=None, cancelled=None):
    """Return project/report/artifact_dir; never deploy or write plant data.

    ``passed`` covers measured reconstruction/configuration only, never an
    assertion of visual fidelity. Native rendering is required for a candidate.
    """
    from PySide6.QtGui import QImage
    from tools.hmi_deployer.reference_ocr import extract_ocr
    from tools.hmi_deployer.reference_backing import prepare_backing
    from tools.hmi_deployer.reference_grounding import (
        GROUNDING_SCHEMA, grounding_prompt, compile_grounded_reference, numeric_reading)
    from tools.hmi_deployer.reference_acceptance import evaluate_reference
    from tools.hmi_deployer.ai_review import still
    from designer.preview.native_renderer import NativeRenderer

    if not images:
        raise ValueError("An image is required")
    emit = emit or (lambda event: None)
    def check_cancelled():
        if cancelled is not None and cancelled():
            raise InterruptedError("Image generation cancelled")
    check_cancelled()
    started = time.monotonic()
    folder = Path(output_dir or tempfile.mkdtemp(prefix="eds-reference-"))
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "source.png"
    image = QImage.fromData(base64.b64decode(images[0].data))
    if image.isNull() or not image.save(str(source), "PNG"):
        raise ValueError("Reference image could not be decoded")
    emit({"type": "status", "message": "Measuring source text and positions"})
    ocr = extract_ocr(source)
    check_cancelled()
    if not ocr.get("lines"):
        raise ValueError("No text detected; automatic reconstruction cannot be verified")
    ocr = prepare_backing(source, ocr, folder)
    check_cancelled()
    ocr["backing_asset"] = ocr["backing"]["path"]
    _write(folder, "ocr.json", ocr)
    previous = {name: getattr(connector, name, None) for name in
                ("system_prompt", "response_schema", "max_output_tokens")}
    connector.system_prompt = grounding_prompt(ocr)
    connector.response_schema = GROUNDING_SCHEMA
    connector.max_output_tokens = 12000
    annotations = None
    attempts = []
    resolved = {}
    semantic_corrections = []
    try:
        prompt = ("Classify every OCR ID in the provided image. Preserve all source content. "
                  "Use simulated data only. User request: " + brief)
        for attempt in range(2):
            check_cancelled()
            chunks = []
            for event in connector.generate_events(prompt, model, images=images):
                check_cancelled()
                kind = event.get("type")
                if kind == "error":
                    raise RuntimeError(event.get("message", "Image classification failed"))
                if kind == "turn_end":
                    if event.get("stopped"):
                        raise InterruptedError("Image generation cancelled")
                    continue
                if kind == "delta":
                    chunks.append(event.get("delta", ""))
                emit(event)
            raw = "".join(chunks)
            check_cancelled()
            (folder / f"classification-{attempt+1}.txt").write_text(raw, encoding="utf-8")
            try:
                candidate = _annotations(raw)
                expected = {str(line["id"]) for line in ocr["lines"]}
                actual = [str(item.get("ocr_id", "")) for item in candidate["elements"]]
                texts = {str(line["id"]): line["text"] for line in ocr["lines"]}
                for item in candidate["elements"]:
                    key = str(item.get("ocr_id", ""))
                    if key not in expected or actual.count(key) != 1:
                        continue
                    if item.get("role") not in {"static", "readout", "button", "toggle"}:
                        continue
                    if item["role"] == "readout" and not re.search(r"\d", texts[key]):
                        semantic_corrections.append({"ocr_id": key, "from": "readout", "to": "static",
                                                     "reason": "Source contains no numeric sample; retained as a label"})
                        item = {"ocr_id": key, "role": "static"}
                    elif item["role"] == "readout" and re.fullmatch(r"\s*\d{1,2}:\d{2}(?::\d{2})?\s*", texts[key]):
                        semantic_corrections.append({"ocr_id": key, "from": "readout", "to": "static",
                                                     "reason": "Source is a timestamp, not a numeric process sample"})
                        item = {"ocr_id": key, "role": "static"}
                    elif item["role"] == "readout" and numeric_reading(texts[key]) is None:
                        continue
                    resolved[key] = item
                missing = sorted(expected - resolved.keys())
                if missing:
                    raise ValueError("Classifications must include every OCR ID exactly once. "
                                     "Return classifications only for these missing/invalid IDs: " + ", ".join(missing)
                                     + ". A readout must contain exactly one numeric token; labels/ranges are static")
                annotations = {"elements": [resolved[str(line["id"])] for line in ocr["lines"]],
                               "artwork": candidate.get("artwork", [])}
                attempts.append({"attempt": attempt + 1, "classification_valid": True})
                break
            except (ValueError, TypeError, AttributeError) as error:
                attempts.append({"attempt": attempt + 1, "classification_valid": False,
                                 "reason": str(error)})
                prompt = ("Repair the previous classification: " + str(error) +
                          ". Return JSON with only the requested missing/invalid elements and artwork=[]. "
                          "Previously valid elements are retained by the compiler; do not repeat them. "
                          "If the error is malformed JSON, return all classifications.")
                emit({"type": "status", "message": "Retrying incomplete OCR classification"})
        if annotations is None:
            _write(folder, "attempts.json", attempts)
            raise ValueError("Model failed complete OCR classification after two attempts; evidence: " + str(folder))
    except Exception as error:
        _write(folder, "failure.json", {"stage": "classification", "error": str(error),
                                       "attempts": attempts, "manual_layout_edits": False})
        raise
    finally:
        for name, value in previous.items():
            setattr(connector, name, value)

    check_cancelled()
    project, compilation = compile_grounded_reference(ocr, annotations, target_width, target_height)
    project._reference_ocr = ocr
    project._reference_artifact_dir = str(folder)
    project._reference_images = images
    project.save(str(folder / "project.edsui"))
    _write(folder, "annotations.json", annotations)
    _write(folder, "compilation.json", compilation)
    _write(folder, "simulation-defaults.json", compilation["simulation_defaults"])
    emit({"type": "status", "message": "Rendering measured widgets in the native runtime"})
    renderer = NativeRenderer()
    renderer.project_dir = str(folder)
    sample = still(project)
    check_cancelled()
    rendered = renderer.render_page_sync(sample, sample.pages[0], sample.screen.theme, timeout_ms=30000)
    check_cancelled()
    report = evaluate_reference(ocr, project, image, rendered)
    report["native_render_available"] = rendered is not None and not rendered.isNull()
    if report["native_render_available"]:
        rendered.save(str(folder / "native-preview.png"), "PNG")
        from tools.hmi_deployer.reference_render_check import check_rendered_text
        emit({"type": "status", "message": "Checking rendered text independently"})
        try:
            text_check = check_rendered_text(ocr, folder / "native-preview.png", target_width, target_height)
        except Exception as error:
            text_check = {"passed": False, "available": False, "reason": str(error)}
        check_cancelled()
        _write(folder, "render-text-check.json", text_check)
        report["rendered_text_check"] = text_check
        report["rendered_text_needs_review"] = not text_check.get("passed", False)
    report["gates"]["native_render"] = report["native_render_available"]
    report["gates"]["readout_classification"] = not any("readout needs" in s for s in compilation["unresolved"])
    report["passed"] = all(report["gates"].values())
    report["unresolved_behavior"] = compilation["unresolved"]
    report["semantic_corrections"] = semantic_corrections
    report["simulation_tag_count"] = len(compilation["simulation_defaults"])
    from daemon.tagsim import PROCESS_PERIOD_S, plan, values_at
    signals = plan(project.to_dict())
    initial = values_at(signals, 0, 240)
    # At a waveform peak, even a one-display-digit amplitude is observable.
    # An arbitrary early timestamp can round back to the source sample.
    later = values_at(signals, PROCESS_PERIOD_S / 4, 240)
    mismatches, stationary = [], []
    for tag, default in compilation["simulation_defaults"].items():
        if initial.get(tag) != default["value"]:
            mismatches.append(tag)
        if default["type"] == "number" and later.get(tag) == initial.get(tag):
            stationary.append(tag)
    report["local_simulation"] = {"passed": not mismatches and not stationary,
                                  "sample_mismatch_tags": mismatches, "stationary_numeric_tags": stationary,
                                  "sample_times_seconds": [0, PROCESS_PERIOD_S / 4],
                                  "scope": "Local simulator samples only; no native interaction or hardware test"}
    report["gates"]["simulation_samples"] = report["local_simulation"]["passed"]
    report["passed"] = all(report["gates"].values())
    report["attempts"] = attempts
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    report["pipeline"] = "ocr-grounded-v1"
    report["manual_layout_edits"] = False
    project._reference_acceptance = report
    check_cancelled()
    _write(folder, "reference-acceptance.json", report)
    return {"project": project, "report": report, "artifact_dir": str(folder)}
