"""Exercise the automatic pipeline boundary without network or native binaries."""
import base64
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from tools.hmi_deployer.reference_pipeline import generate_reference


class Connector:
    def __init__(self, replies):
        self.system_prompt = "previous system"
        self.response_schema = {"previous": True}
        self.max_output_tokens = 321
        self.replies = iter(replies)
        self.calls = []

    def generate_events(self, prompt, model, images):
        self.calls.append((prompt, model, images, self.system_prompt, self.response_schema))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, list):
            yield from reply
        else:
            yield {"type": "delta", "delta": json.dumps(reply)}
            yield {"type": "turn_end"}


class ReferencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.image = QImage(320, 200, QImage.Format.Format_RGB32)
        self.image.fill("#eeeeee")
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.image.save(buffer, "PNG")
        self.images = [SimpleNamespace(data=base64.b64encode(bytes(data)).decode("ascii"))]
        self.ocr = {"width": 320, "height": 200, "lines": [
            {"id": "label", "text": "Pressure", "box": [10, 10, 80, 18]},
            {"id": "value", "text": "7.25 bar", "box": [10, 40, 80, 20]}]}
        self.valid = {"elements": [{"ocr_id": "label", "role": "static"},
                                  {"ocr_id": "value", "role": "readout", "tag": "vessel.pressure"}],
                      "artwork": []}
        self.extract = self.stack.enter_context(patch(
            "tools.hmi_deployer.reference_ocr.extract_ocr", return_value=deepcopy(self.ocr)))
        self.backing = self.stack.enter_context(patch(
            "tools.hmi_deployer.reference_backing.prepare_backing", side_effect=self.prepare_backing))
        self.renderer = self.stack.enter_context(patch("designer.preview.native_renderer.NativeRenderer"))
        self.renderer.return_value.render_page_sync.return_value = self.image
        self.text_check = self.stack.enter_context(patch(
            "tools.hmi_deployer.reference_render_check.check_rendered_text",
            return_value={"passed": True, "available": True}))

    def prepare_backing(self, source, ocr, folder):
        asset = Path(folder) / "assets" / "reference-artwork.png"
        asset.parent.mkdir()
        self.image.save(str(asset), "PNG")
        return {**ocr, "backing": {"path": "assets/reference-artwork.png"}}

    def run_pipeline(self, connector):
        return generate_reference(connector, "Build from uploaded image", "test-model", self.images,
                                  target_width=320, target_height=200, output_dir=self.folder)

    def assert_restored(self, connector):
        self.assertEqual(connector.system_prompt, "previous system")
        self.assertEqual(connector.response_schema, {"previous": True})
        self.assertEqual(connector.max_output_tokens, 321)

    def test_image_only_path_compiles_renders_and_persists_evidence(self):
        connector = Connector([self.valid])
        result = self.run_pipeline(connector)
        self.assertTrue(result["report"]["passed"], result["report"]["issues"])
        self.assertFalse(result["report"]["manual_layout_edits"])
        self.assertFalse(result["report"]["runtime_verified"])
        self.assertEqual(result["report"]["simulation_tag_count"], 1)
        self.assertTrue(result["report"]["gates"]["simulation_samples"], result["report"]["local_simulation"])
        self.extract.assert_called_once_with(self.folder / "source.png")
        self.renderer.return_value.render_page_sync.assert_called_once()
        defaults = json.loads((self.folder / "simulation-defaults.json").read_text())
        self.assertEqual(defaults["sim.vessel.pressure"]["value"], 7.25)
        self.assertTrue((self.folder / "native-preview.png").exists())
        self.assertTrue((self.folder / "project.edsui").exists())
        self.assert_restored(connector)

    def test_missing_id_retries_with_complete_grounding_contract(self):
        missing = {"elements": [self.valid["elements"][0]], "artwork": []}
        connector = Connector([missing, self.valid])
        result = self.run_pipeline(connector)
        self.assertEqual([a["classification_valid"] for a in result["report"]["attempts"]], [False, True])
        self.assertIn("every OCR ID exactly once", connector.calls[1][0])
        self.assertIn('"id":"value"', connector.calls[1][3])
        self.assert_restored(connector)

    def test_readings_with_unit_exponents_pass_without_classification_retry(self):
        for text, sample in [("76,600 Nm3/min", 76600),
                             ("2.39 kg/cm2", 2.39), ("1.23 kg/cm2", 1.23)]:
            with self.subTest(text=text):
                self.extract.return_value["lines"][1]["text"] = text
                connector = Connector([self.valid])
                # Each run writes its own evidence and backing asset.
                self.folder = self.folder / str(sample)
                result = self.run_pipeline(connector)
                self.assertEqual(len(connector.calls), 1)
                self.assertTrue(result["report"]["passed"], result["report"])
                defaults = json.loads((self.folder / "simulation-defaults.json").read_text())
                self.assertEqual(defaults["sim.vessel.pressure"]["value"], sample)
                self.assert_restored(connector)

    def test_duplicate_id_fails_after_bounded_retry_without_render(self):
        duplicate = deepcopy(self.valid)
        duplicate["elements"].append(deepcopy(duplicate["elements"][0]))
        connector = Connector([duplicate, duplicate])
        with self.assertRaisesRegex(ValueError, "after two attempts"):
            self.run_pipeline(connector)
        self.renderer.assert_not_called()
        self.assertEqual(len(json.loads((self.folder / "attempts.json").read_text())), 2)
        self.assert_restored(connector)

    def test_missing_annotation_retry_merges_only_corrected_missing_element(self):
        first = {"elements": [self.valid["elements"][0]], "artwork": []}
        second = {"elements": [self.valid["elements"][1]], "artwork": []}
        result = self.run_pipeline(Connector([first, second]))
        self.assertTrue(result["report"]["passed"], result["report"])
        annotations = json.loads((self.folder / "annotations.json").read_text())
        self.assertEqual([item["ocr_id"] for item in annotations["elements"]], ["label", "value"])
        self.assertEqual(len(result["report"]["attempts"]), 2)

    def test_independent_rendered_text_mismatch_is_disclosed(self):
        self.text_check.return_value = {"passed": False, "available": True, "missing": ["value"]}
        result = self.run_pipeline(Connector([self.valid]))
        self.assertTrue(result["report"]["rendered_text_needs_review"])
        self.assertFalse(result["report"]["visual_match_verified"])
        self.assertTrue((self.folder / "render-text-check.json").exists())

    def test_low_precision_reading_is_tested_at_visible_waveform_peak(self):
        self.extract.return_value["lines"][1]["text"] = "3.4 bar"
        result = self.run_pipeline(Connector([self.valid]))
        self.assertTrue(result["report"]["local_simulation"]["passed"])
        self.assertFalse(result["report"]["local_simulation"]["stationary_numeric_tags"])

    def test_model_timestamp_readout_is_retained_as_static_source_text(self):
        self.extract.return_value["lines"][1]["text"] = "14:28:12"
        result = self.run_pipeline(Connector([self.valid]))
        self.assertTrue(result["report"]["passed"])
        self.assertEqual(result["report"]["simulation_tag_count"], 0)
        self.assertEqual(result["report"]["semantic_corrections"][0]["to"], "static")

    def test_connector_exception_restores_settings(self):
        connector = Connector([RuntimeError("provider unavailable")])
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            self.run_pipeline(connector)
        self.assert_restored(connector)

    def test_cancel_restores_settings_without_compiling_or_rendering(self):
        connector = Connector([[{"type": "turn_end", "stopped": True}]])
        with self.assertRaises(InterruptedError):
            self.run_pipeline(connector)
        self.assert_restored(connector)
        self.renderer.assert_not_called()
        self.assertFalse((self.folder / "project.edsui").exists())

    def test_cancel_during_ocr_never_starts_model(self):
        cancelled = [False]
        def extract(*args):
            cancelled[0] = True
            return deepcopy(self.ocr)
        self.extract.side_effect = extract
        connector = Connector([self.valid])
        with self.assertRaises(InterruptedError):
            generate_reference(connector, "image", "model", self.images,
                output_dir=self.folder, cancelled=lambda: cancelled[0])
        self.assertEqual(connector.calls, [])
        self.renderer.assert_not_called()
        self.assert_restored(connector)

    def test_cancel_during_render_never_publishes_acceptance(self):
        cancelled = [False]
        def render(*args, **kwargs):
            cancelled[0] = True
            return self.image
        self.renderer.return_value.render_page_sync.side_effect = render
        connector = Connector([self.valid])
        with self.assertRaises(InterruptedError):
            generate_reference(connector, "image", "model", self.images,
                output_dir=self.folder, cancelled=lambda: cancelled[0])
        self.text_check.assert_not_called()
        self.assertFalse((self.folder / "reference-acceptance.json").exists())
        self.assert_restored(connector)

    def test_missing_native_render_fails_acceptance(self):
        self.renderer.return_value.render_page_sync.return_value = None
        result = self.run_pipeline(Connector([self.valid]))
        self.assertFalse(result["report"]["passed"])
        self.assertFalse(result["report"]["gates"]["native_render"])
        self.assertFalse((self.folder / "native-preview.png").exists())

    def test_null_native_render_fails_acceptance(self):
        self.renderer.return_value.render_page_sync.return_value = QImage()
        result = self.run_pipeline(Connector([self.valid]))
        self.assertFalse(result["report"]["passed"])
