"""Image candidates use the grounded pipeline and require explicit Apply."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from designer.model import DesignerProject
from tools.hmi_deployer.ai_tab import AIDesignTab, GenerationWorker


class GroundedIntegrationTests(unittest.TestCase):
    def test_stop_requests_thread_interruption_before_connector_cancel(self):
        calls = []
        tab = SimpleNamespace(streaming=True,
            _worker=SimpleNamespace(requestInterruption=lambda: calls.append("interrupt")),
            connector=SimpleNamespace(cancel=lambda: calls.append("cancel")), send_btn=Mock())
        AIDesignTab.stop_generation(tab)
        self.assertEqual(calls, ["interrupt", "cancel"])

    def test_candidate_preview_uses_native_artifact_without_applying(self):
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtGui import QImage
        from tools.hmi_deployer.ai_tab import PreviewView
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            image = QImage(80, 40, QImage.Format_RGB32)
            image.fill("blue")
            image.save(str(Path(directory) / "native-preview.png"))
            project = DesignerProject()
            project._reference_artifact_dir = directory
            tab = QWidget()
            tab.preview_view = PreviewView(tab)
            tab.preview_placeholder = Mock()
            tab.bezel_badge = Mock()
            tab.statusMessage = Mock()
            tab._refresh_preview_meta = Mock()
            tab._variant_renderer = Mock()
            self.assertTrue(AIDesignTab._show_reference_candidate(tab, project))
            self.assertIs(tab._candidate_preview_project, project)
            self.assertEqual(tab.preview_view.scene().sceneRect().width(), 80)
            tab._variant_renderer.assert_not_called()
            tab.bezel_badge.setText.assert_called_with("CANDIDATE PREVIEW")
            app.processEvents()  # Drain PreviewView's deferred initial fit before teardown.
            tab.close()

    def test_image_worker_pipeline_and_text_worker_legacy(self):
        connector = Mock()
        connector.generate_events.return_value = [{"type": "turn_end"}]
        result = {"project": DesignerProject(), "report": {"passed": True}, "artifact_dir": ""}
        with patch("tools.hmi_deployer.reference_pipeline.generate_reference", return_value=result) as pipeline:
            worker = GenerationWorker(connector, "brief", "model", images=[object()])
            worker.reference_target = (800, 600)
            events = []
            worker.event.connect(events.append)
            worker.run()
            pipeline.assert_called_once()
            connector.generate_events.assert_not_called()
            self.assertEqual([e["type"] for e in events], ["reference_result", "turn_end"])
            self.assertEqual(events[0]["result"], result)
            GenerationWorker(connector, "text", "model").run()
            connector.generate_events.assert_called_once_with("text", "model")

    def test_grounded_conclusion_never_autoapplies_or_reparses(self):
        for passed in (True, False):
            project = DesignerProject()
            shell = Mock()
            shell.error_row = None
            shell.response_pane.toPlainText.return_value = "model annotations"
            shell.metrics.return_value = {"total_tokens": 0, "output_tokens": 0,
                "output_estimated": False, "rate": None, "elapsed_ms": 0}
            turn = SimpleNamespace(shell=shell, conclude=Mock(), _reference_result={
                "project": project, "report": {"passed": passed}, "artifact_dir": "work"})
            tab = SimpleNamespace(generator=Mock(), _root_images=[object()],
                _canvas_project=lambda: None, statusMessage=Mock(), _account_session=Mock(),
                apply_to_canvas=Mock(), auto_apply=SimpleNamespace(isChecked=lambda: True),
                _review_wanted=Mock(), _queued_section_request=None, _show_reference_candidate=Mock())
            AIDesignTab._conclude_turn(tab, turn, False)
            self.assertIs(tab.last_project, project)
            tab.generator.generate.assert_not_called()
            tab.apply_to_canvas.assert_not_called()
            tab._review_wanted.assert_not_called()
            self.assertIs(turn.conclude.call_args.args[0], project)
            tab._show_reference_candidate.assert_called_once_with(project)

    def test_partial_reference_failure_never_falls_back_to_legacy_parser(self):
        connector = Mock()
        with patch("tools.hmi_deployer.reference_pipeline.generate_reference", side_effect=RuntimeError("native render failed")):
            worker = GenerationWorker(connector, "image", "model", images=[object()])
            worker.reference_target = (800, 600)
            events = []
            worker.event.connect(events.append)
            worker.run()
        self.assertTrue(events[0]["reference_failure"])
        shell = Mock()
        shell.response_pane.toPlainText.return_value = '{"elements": [{"ocr_id": "line1"}]}'
        shell.error_row.title.text.return_value = "native render failed"
        shell.metrics.return_value = {"total_tokens": 0, "output_tokens": 0,
            "output_estimated": False, "rate": None, "elapsed_ms": 0}
        turn = SimpleNamespace(shell=shell, conclude=Mock(), show_error=Mock())
        tab = SimpleNamespace(generator=Mock(), _probe_ok=True, _scroll_to_bottom=Mock(),
            _account_session=Mock(), apply_to_canvas=Mock(), _review_wanted=Mock())
        AIDesignTab._on_event(tab, turn, events[0])
        AIDesignTab._conclude_turn(tab, turn, False)
        tab.generator.generate.assert_not_called()
        tab.apply_to_canvas.assert_not_called()
        self.assertIsNone(turn.conclude.call_args.args[0])
        shell.finish.assert_called_with("failed")

    def test_target_change_invalidates_passed_render_before_preview(self):
        from tests.test_reference_acceptance import fixture
        from tools.hmi_deployer.reference_acceptance import evaluate_reference
        ocr, project = fixture()
        project._reference_ocr = ocr
        project._reference_acceptance = evaluate_reference(ocr, project)
        project._reference_acceptance["gates"].update(native_render=True, readout_classification=False)
        project._reference_acceptance["passed"] = True
        workspace = SimpleNamespace(bundle_dir="", preview=Mock(),
            load_project=lambda candidate: setattr(candidate.screen, "width", 1000))
        tab = SimpleNamespace(last_project=project, workspace=workspace, statusMessage=Mock(),
            preview_view=Mock(), _refresh_preview_meta=Mock(), generateRequested=Mock(),
            canvasFocusRequested=Mock())
        AIDesignTab.apply_to_canvas(tab)
        report = project._reference_acceptance
        self.assertFalse(report["passed"])
        self.assertFalse(report["gates"]["native_render"])
        self.assertFalse(report["gates"]["readout_classification"])
        self.assertFalse(report["pixel_evidence"]["available"])
        workspace.preview.assert_not_called()
        tab.generateRequested.emit.assert_not_called()

    def test_failed_apply_copies_assets_but_never_previews_or_emits_generate(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = Path(folder) / "candidate"
            bundle = Path(folder) / "bundle"
            (artifact / "assets").mkdir(parents=True)
            (artifact / "assets" / "art.png").write_bytes(b"test image")
            (artifact / "ocr.json").write_text('{"lines": []}', encoding="utf-8")
            (artifact / "simulation-defaults.json").write_text('{"sim.level": 12}', encoding="utf-8")
            project = DesignerProject()
            project._reference_artifact_dir = str(artifact)
            project._reference_acceptance = {"passed": False}
            workspace = SimpleNamespace(bundle_dir=str(bundle), load_project=Mock(), preview=Mock())
            tab = SimpleNamespace(last_project=project, workspace=workspace, statusMessage=Mock(),
                preview_view=Mock(), _refresh_preview_meta=Mock(), generateRequested=Mock(),
                canvasFocusRequested=Mock(), _root_brief="image")
            result = AIDesignTab.apply_to_canvas(tab)
            self.assertEqual(result, "applied")
            self.assertEqual((bundle / "assets" / "art.png").read_bytes(), b"test image")
            self.assertTrue((bundle / "reference-acceptance.json").exists())
            self.assertEqual((bundle / "ocr.json").read_text(encoding="utf-8"), '{"lines": []}')
            self.assertEqual((bundle / "simulation-defaults.json").read_text(encoding="utf-8"), '{"sim.level": 12}')
            workspace.load_project.assert_called_once_with(project)
            workspace.preview.assert_not_called()
            tab.generateRequested.emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
