"""The image contract, review, and persisted evidence use the same semantics."""
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from designer.model import DesignerProject
from designer.palette.widget_registry import default_registry
from tools.hmi_deployer.ai_design import encode_brief_image
from tools.hmi_deployer.ai_review import apply_review
from tools.hmi_deployer.reference_workflow import prepare_reference_images, reference_geometry_hint, save_reference_audit


def measured_project():
    from designer.layout.compiler import REFERENCE_MARK, WIDGET_BOX_MARK, compile_page
    p = DesignerProject.from_dict({"screen": {"width": 800, "height": 600}, "pages": [
        {"id": "main", "widgets": [{"type": "ShToggle", "id": "heater",
         "geometry": {"x": 0, "y": 0, "width": 100, "height": 40},
         "properties": {REFERENCE_MARK: {"layout": "measured", "width": 1000, "height": 1000,
                                          "viewport": [0, 0, 1, 1]},
                        WIDGET_BOX_MARK: [.1, .1, .3, .2]},
         "bindings": {"checked": "plant.heater"},
         "actions": {"toggled": {"kind": "toggle", "tag": "plant.heater"}}}]}]})
    compile_page(p, p.pages[0], default_registry())
    return p


class ReferenceWorkflowTests(unittest.TestCase):
    def test_measured_artwork_can_contain_a_live_control_without_false_overlap(self):
        from designer.model import DesignerWidget
        from tools.hmi_deployer.ai_review import layout_findings
        p = measured_project()
        p.pages[0].widgets.insert(0, DesignerWidget("Image", "art",
            {"x": 0, "y": 0, "width": 800, "height": 600},
            {"_reference": {"layout": "measured"}}))
        self.assertFalse(any(f["kind"] == "overlap" for f in layout_findings(p)))
        other = copy.deepcopy(p.pages[0].widgets[1])
        other.id = "otherControl"
        p.pages[0].widgets.append(other)
        self.assertTrue(any(f["kind"] == "overlap" for f in layout_findings(p)))

    def test_prepared_crop_has_one_shared_coordinate_system_and_keeps_original(self):
        image = QImage(400, 200, QImage.Format_RGB32)
        image.fill("white")
        reference = encode_brief_image(image)
        original_data = reference.data
        with patch("designer.layout.palette.reference_content_rect", return_value=(20, 10, 380, 190)):
            prepared = prepare_reference_images([reference, reference])
        self.assertEqual((prepared[0].width, prepared[0].height), (360, 180))
        self.assertEqual(reference.data, original_data)
        self.assertIs(prepared[1], reference)
        metadata = reference_geometry_hint(prepared)
        self.assertIn('"viewport": [0.0, 0.0, 1000.0, 1000.0]', metadata)
        self.assertEqual(prepare_reference_images([]), [])

    def test_hint_uses_encoded_image_size_and_full_image_coordinates(self):
        image = QImage(400, 200, QImage.Format_RGB32)
        image.fill("white")
        reference = encode_brief_image(image)
        with patch("designer.layout.palette.reference_content_rect", return_value=(20, 10, 380, 190)):
            hint = reference_geometry_hint([reference])
        metadata = json.JSONDecoder().raw_decode(hint[hint.index('{'):])[0]
        self.assertEqual(metadata, {"layout": "measured", "width": 400, "height": 200,
                                    "viewport": [50, 50, 950, 950]})
        self.assertIn("FULL first image", hint)
        self.assertIn("uniformly fits", hint)
        self.assertIn("do not invent a verified hardware connection", hint)

    def test_missing_or_unreadable_image_has_no_geometry_contract(self):
        self.assertEqual(reference_geometry_hint([]), "")
        self.assertEqual(reference_geometry_hint([SimpleNamespace(data=base64.b64encode(b"bad").decode())]), "")

    def test_audit_is_persisted_without_claiming_runtime_or_visual_success(self):
        p = measured_project()
        before = copy.deepcopy(p.to_dict())
        with tempfile.TemporaryDirectory() as directory:
            result = save_reference_audit(p, directory)
            saved = json.loads((Path(directory) / "reference-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, result.to_dict())
            self.assertFalse((Path(directory) / "reference-audit.json.tmp").exists())
            self.assertTrue(saved["configuration_ready"])
            self.assertFalse(saved["runtime_verified"])
            self.assertFalse(saved["deployment_verified"])
            self.assertFalse(saved["visual_match_verified"])
        self.assertEqual(before, p.to_dict())

    def test_box_review_moves_measured_widget_preserving_behavior(self):
        from designer.layout.compiler import WIDGET_BOX_MARK
        p = measured_project()
        w = p.pages[0].widgets[0]
        bindings, actions = copy.deepcopy(w.bindings), copy.deepcopy(w.actions)
        made = apply_review(p, [{"op": "box", "id": "heater", "box": [200, 300, 500, 400]}],
                            default_registry())
        self.assertEqual(made, ["positioned heater"])
        self.assertEqual(w.properties[WIDGET_BOX_MARK], [.2, .3, .5, .4])
        self.assertEqual(w.geometry, {"x": 220, "y": 180, "width": 180, "height": 60})
        self.assertEqual(w.bindings, bindings)
        self.assertEqual(w.actions, actions)

    def test_box_review_accepts_thin_measured_elements(self):
        p = measured_project()
        made = apply_review(p, [{"op": "box", "id": "heater", "box": [200, 300, 500, 310]}],
                            default_registry())
        self.assertEqual(made, ["positioned heater"])
        self.assertEqual(p.pages[0].widgets[0].geometry["height"], 6)

    def test_box_review_does_not_reposition_legacy_layout(self):
        from designer.layout.compiler import REFERENCE_MARK
        p = measured_project()
        p.pages[0].widgets[0].properties.pop(REFERENCE_MARK)
        before = copy.deepcopy(p.to_dict())
        self.assertEqual(apply_review(p, [{"op": "box", "id": "heater", "box": [200, 300, 500, 400]}],
                                      default_registry()), [])
        self.assertEqual(p.to_dict(), before)

    def test_no_applicable_review_fixes_is_not_a_success_badge(self):
        from tools.hmi_deployer.ai_tab import AIDesignTab
        p = measured_project()
        turn = SimpleNamespace(note_review=Mock())
        state = {"turn": turn, "project": p, "text": ['{"issues": [], "fixes": []}'],
                 "findings": [], "round": 1}
        tab = SimpleNamespace(_review=state, _review_worker=object(), last_project=p, streaming=False,
                              generator=SimpleNamespace(registry=default_registry()), apply_to_canvas=Mock())
        AIDesignTab._on_review_done(tab)
        message, severity = turn.note_review.call_args.args
        self.assertEqual(severity, "neutral")
        self.assertIn("not certified", message)
        tab.apply_to_canvas.assert_not_called()

    def test_incomplete_control_retries_once_and_keeps_candidate_visible(self):
        from tools.hmi_deployer.ai_tab import AIDesignTab
        from designer.layout.compiler import REGION_MARK
        from designer.model import DesignerWidget
        p = measured_project()
        p.pages[0].widgets[0].actions = {}
        p.pages[0].widgets[0].properties[REGION_MARK] = "center"
        p.pages[0].widgets.append(DesignerWidget("Text", "title",
            {"x": 0, "y": 0, "width": 200, "height": 30},
            {"text": "Plant", REGION_MARK: "top"}))
        generator = SimpleNamespace(generate=Mock(side_effect=lambda *args: copy.deepcopy(p)),
                                    registry=default_registry(), last_polish=None, last_fit_notes=[])
        settings = SimpleNamespace(value=lambda key, default, **kwargs:
                                   False if key == "ai/referencePalette" else default)
        tab = SimpleNamespace(generator=generator, settings=settings, _root_images=[object()],
            _screen_size=lambda: (800, 600), _section_run=1, _section_project=None,
            statusMessage=SimpleNamespace(emit=Mock()), _canvas_project=lambda: None,
            auto_apply=SimpleNamespace(isChecked=lambda: True), apply_to_canvas=Mock(return_value="previewed"),
            _offer_variants=Mock(), _plan_previous=None, REFERENCE_MIN_WIDGETS=2,
            _shortfall_retried=False, _queued_retry=None, _queued_section_request=None,
            _root_brief="Reproduce the image", PLAN_REQUEST="Return a complete plan",
            _account_session=Mock(), _review_wanted=lambda project: False)

        def turn():
            shell = Mock()
            shell.response_pane.toPlainText.return_value = "{}"
            shell.error_row = None
            shell.truncated = False
            shell.metrics.return_value = {"total_tokens": 0, "output_tokens": 0,
                "output_estimated": False, "rate": None, "elapsed_ms": 0}
            return SimpleNamespace(shell=shell, conclude=Mock())

        first, second = turn(), turn()
        with patch("tools.hmi_deployer.ai_tab.plan_shortfall", return_value=""):
            AIDesignTab._conclude_turn(tab, first, stopped=False)
            self.assertTrue(tab._shortfall_retried)
            self.assertIn("reference configuration is incomplete", tab._queued_retry[0])
            self.assertIn("heater", tab._queued_retry[0])
            first_candidate = first.conclude.call_args.args[0]
            self.assertIs(tab.last_project, first_candidate)
            tab.apply_to_canvas.assert_called_once_with(project=first_candidate)
            # Simulate the worker consuming the queued retry before its reply.
            tab._queued_retry = None
            AIDesignTab._conclude_turn(tab, second, stopped=False)
        self.assertIsNone(tab._queued_retry, "The second incomplete result must not loop")
        self.assertEqual(tab.apply_to_canvas.call_count, 2)
        chips = second.conclude.call_args.args[2]
        self.assertTrue(any(text.startswith("Incomplete:") and severity == "warn"
                            for text, severity in chips))
        self.assertTrue(any(text.startswith("Reference checks:") and severity == "warn"
                            for text, severity in chips))
        self.assertFalse(any("ready" in text.lower() and severity == "ok" for text, severity in chips))

    def test_reviewed_source_font_size_is_idempotent_after_recompile(self):
        from designer.layout.compiler import compile_page
        p = measured_project()
        widget = p.pages[0].widgets[0]
        widget.type = "Text"
        widget.bindings = {}
        widget.actions = {}
        widget.properties.update(text="Temperature", fontSize=12,
                                 _referenceMetrics={"fontSize": 20})
        fix = {"op": "set", "id": "heater", "property": "fontSize", "value": 30}
        self.assertEqual(apply_review(p, [fix], default_registry()), ["set heater.fontSize"])
        self.assertEqual(widget.properties["_referenceMetrics"]["fontSize"], 30)
        self.assertEqual(widget.properties["fontSize"], 18)
        before = copy.deepcopy(p.to_dict())
        self.assertEqual(apply_review(p, [fix], default_registry()), [])
        compile_page(p, p.pages[0], default_registry())
        self.assertEqual(before, p.to_dict())


if __name__ == "__main__":
    unittest.main()
