from copy import deepcopy

import unittest

from designer.palette.widget_registry import default_registry
from tools.hmi_deployer.reference_grounding import compile_grounded_reference, grounding_prompt


def source():
    return {"width": 800, "height": 400, "lines": [
        {"id": "a", "text": "Temperature", "box": [20, 20, 100, 16]},
        {"id": "b", "text": "78.2 °C", "box": [20, 50, 90, 24], "color": "#00aa33"},
        {"id": "c", "text": "Enable", "box": [180, 50, 60, 20]},
    ]}


def test_geometry_and_text_come_only_from_ocr():
    doc = source()
    annotations = {"elements": [{"ocr_id": "b", "role": "readout", "tag": "reactor.temperature",
                                 "box": [0, 0, 1, 1], "text": "invented"}]}
    project, report = compile_grounded_reference(doc, annotations, 800, 600)
    value = project.pages[0].widgets[1]
    assert value.properties["text"] == "78.2 °C"
    assert value.properties["_ocrBox"] == [20, 50, 90, 24]
    assert value.geometry["x"] == 20
    assert value.geometry["y"] < 150  # ascender space precedes the OCR ink
    assert value.geometry["width"] >= 90
    assert value.geometry["height"] > 24  # descenders and native line box fit
    assert value.bindings["text"].format == "%1 °C"
    assert report["simulation_defaults"]["sim.reactor.temperature"]["value"] == 78.2
    assert report["covered_ocr_ids"] == ["a", "b", "c"]
    assert not project.validate(default_registry())


def test_new_sample_changes_result_without_reference_specific_code():
    for sample in ["94.7 C", "5.0 MW", "Pressure 2.8 bar", "-12.4 kPa"]:
        check_changed_sample(sample)


def check_changed_sample(sample):
    doc = source()
    doc["lines"][1]["text"] = sample
    project, report = compile_grounded_reference(doc, {"elements": [{"ocr_id": "b", "role": "readout"}]})
    assert project.pages[0].widgets[1].properties["text"] == sample
    assert len(report["simulation_defaults"]) == 1


def test_ambiguous_readout_preserved_and_reported():
    doc = source()
    doc["lines"][1]["text"] = "70 - 85"
    project, report = compile_grounded_reference(doc, {"elements": [{"ocr_id": "b", "role": "readout"}]})
    assert not project.pages[0].widgets[1].bindings
    assert report["unresolved"]


def test_controls_never_invent_navigation_or_physical_actions():
    doc = source()
    project, report = compile_grounded_reference(doc, {"elements": [{"ocr_id": "c", "role": "button", "action": "navigate", "page": "missing"}]})
    button = project.pages[0].widgets[2]
    assert not button.properties["enabled"] and not button.actions
    caption = project.pages[0].widgets[3]
    assert button.properties["text"] == ""
    assert "_ocrIds" not in button.properties
    assert caption.properties["text"] == "Enable"
    assert caption.properties["_ocrIds"] == ["c"]
    assert caption.properties["fontSize"] == 26
    project, report = compile_grounded_reference(doc, {"elements": [{"ocr_id": "c", "role": "toggle", "action": "simulate_toggle", "tag": "do.motor.run"}]})
    assert project.pages[0].widgets[2].actions["clicked"].tag == "sim.do.motor.run"
    assert report["simulation_defaults"]["sim.do.motor.run"]["type"] == "bool"
    assert not project.validate(default_registry())


def test_unknown_and_duplicate_annotations_cannot_drop_ocr():
    project, report = compile_grounded_reference(source(), {"elements": [
        {"ocr_id": "missing", "role": "readout"}, {"ocr_id": "a", "role": "static"},
        {"ocr_id": "a", "role": "readout"}]})
    assert len(project.pages[0].widgets) == 3
    assert len(report["warnings"]) == 2


def test_cleaned_backing_is_explicit_not_a_claim_of_functionality():
    doc = source()
    doc["backing_asset"] = "assets/reference-artwork.png"
    project, report = compile_grounded_reference(doc, {})
    backing = project.pages[0].widgets[0]
    assert backing.properties["_referenceArtworkCleaned"]
    assert "_crop" not in backing.properties
    assert report["artwork_remains_raster"] and not report["visual_match_verified"]
    assert [w.properties["_ocrIds"][0] for w in project.all_widgets() if "_ocrIds" in w.properties] == ["a", "b", "c"]


def test_invalid_measurements_fail_instead_of_fabricating_geometry():
    doc = deepcopy(source())
    doc["lines"][0]["box"][2] = -1
    with unittest.TestCase().assertRaises(ValueError):
        compile_grounded_reference(doc, {})


def test_native_text_boxes_include_font_advance_and_descenders():
    from tools.hmi_deployer.reference_grounding import _text_font
    doc = source()
    doc["lines"][0].update(text="Typography gjpq", font_size=22, box=[20, 30, 130, 18])
    project, _ = compile_grounded_reference(doc, {}, 800, 400)
    widget = project.pages[0].widgets[0]
    font = _text_font(22, False)
    left, top, right, bottom = font.getbbox("Typography gjpq")
    ascent, descent = font.getmetrics()
    assert widget.geometry["height"] >= ascent + descent
    assert widget.geometry["width"] >= font.getlength("Typography gjpq")
    assert widget.geometry["y"] + top == 30


def test_prompt_contains_measured_source_ids_and_no_layout_request():
    prompt = grounding_prompt(source())
    assert "78.2 °C" in prompt and '"id":"b"' in prompt
    assert "do not rewrite text or supply text coordinates" in prompt


def test_simulation_metadata_roundtrip_starts_with_source_sample():
    import json
    from designer.model import DesignerProject
    from daemon.tagsim import plan, values_at
    project, _ = compile_grounded_reference(source(), {"elements": [
        {"ocr_id": "b", "role": "readout", "tag": "reactor.temperature"},
        {"ocr_id": "c", "role": "toggle", "action": "simulate_toggle", "tag": "motor.run", "checked": True}]})
    restored = DesignerProject.from_dict(json.loads(json.dumps(project.to_dict())))
    value = restored.pages[0].widgets[1]
    button = restored.pages[0].widgets[2]
    assert value.properties["_simulationSample"] == 78.2
    assert value.properties["_simulationDecimals"] == 1
    assert button.properties["_simulationDefaults"] == {"sim.motor.run": True}
    signals = plan(restored.to_dict())
    initial = values_at(signals, 0, 180)
    later = values_at(signals, 15, 180)
    assert initial["sim.reactor.temperature"] == 78.2
    assert later["sim.reactor.temperature"] != initial["sim.reactor.temperature"]
    assert initial["sim.motor.run"] is True and later["sim.motor.run"] is True


def test_grouped_numeric_readings_preserve_original_span_and_units():
    from tools.hmi_deployer.reference_grounding import numeric_reading
    cases = [("1,050 °c", 1050, 0), ("1 ,050 °c", 1050, 0),
             ("Output 1 050.20 MW", 1050.2, 2), ("-1,234,567.8 bar", -1234567.8, 1),
             ("1\u202f050 rpm", 1050, 0)]
    for sample_text, expected, decimals in cases:
        reading = numeric_reading(sample_text)
        assert reading is not None
        assert reading.sample == expected and reading.decimals == decimals
        doc = source()
        doc["lines"][1]["text"] = sample_text
        project, report = compile_grounded_reference(doc, {"elements": [{"ocr_id": "b", "role": "readout"}]})
        value = project.pages[0].widgets[1]
        assert value.properties["text"] == sample_text
        assert value.bindings["text"].format == sample_text[:reading.match.start()] + "%1" + sample_text[reading.match.end():]
        assert value.properties["_simulationSample"] == expected
    for invalid in ["70 - 85", "1,05 bar", "12:30", "Inlet", "1.2 3.4"]:
        assert numeric_reading(invalid) is None


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(value) for key, value in globals().items() if key.startswith("test_"))
