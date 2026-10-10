"""AI Design's review pass (tools/hmi_deployer/ai_review.py).

After a reference run the screen as built is shown to the model beside its
picture, with what the layout measures, and the model's fixes are applied
within limits. The case is the user's blast furnace in the Studio
(2026-10-10): a "logo" cut from the picture that was the plant's printed
name beside the name itself, and labels the drawing prints squeezed under it.
"""
import copy
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RECORDED = os.path.join(ROOT, "tests", "fixtures", "ai", "reference_furnace_ornith.json")
W, H = 1024, 768


def _project():
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    with open(RECORDED, encoding="utf-8") as fh:
        plan = json.loads(json.load(fh)["reply"])
    header = plan["pages"][0]["header"]
    # As in the Studio's run: a logo cut where the plant's name is printed.
    header.insert(0, {"type": "Image", "id": "logo", "side": "left",
                      "properties": {"source": "", "crop": [0, 0, 105, 100]}})
    return AIDesignGenerator().generate(json.dumps(plan), W, H)


def _registry():
    from designer.palette.widget_registry import default_registry
    return default_registry()


def _ids(project):
    from tools.hmi_deployer.ai_review import _walk
    return {w.id for w, _r, _p in _walk(project.pages[0].widgets)}


class Findings(unittest.TestCase):
    def test_overlaps_clipped_words_and_words_twice_are_measured(self):
        from designer.model import DesignerProject, DesignerPage, DesignerScreen, DesignerWidget
        from tools.hmi_deployer.ai_review import layout_findings
        page = DesignerPage(id="main", name="Main", widgets=[
            DesignerWidget("Text", "a", {"x": 0, "y": 0, "width": 200, "height": 30},
                           {"text": "BLAST FURNACE", "fontSize": 14}),
            DesignerWidget("Text", "b", {"x": 100, "y": 10, "width": 200, "height": 30},
                           {"text": "Blast furnace", "fontSize": 14}),
            DesignerWidget("ShAnnunciator", "c", {"x": 0, "y": 100, "width": 60, "height": 30},
                           {"text": "SYSTEM NORMAL - CASTING IN PROGRESS"}),
        ])
        project = DesignerProject(name="t", screen=DesignerScreen(width=W, height=H), pages=[page])
        kinds = {(f["kind"], tuple(f["ids"])) for f in layout_findings(project, page, _registry())}
        self.assertIn(("overlap", ("a", "b")), kinds)
        self.assertIn(("twice", ("a", "b")), kinds)
        self.assertIn(("clipped", ("c",)), kinds)

    def test_the_compiled_furnace_has_no_findings(self):
        from tools.hmi_deployer.ai_review import layout_findings
        project = _project()
        self.assertEqual(layout_findings(project, project.pages[0], _registry()), [])


class Fixes(unittest.TestCase):
    def setUp(self):
        self.project = _project()
        self.registry = _registry()

    def test_a_logo_the_model_sees_is_words_is_removed_and_the_page_recompiled(self):
        from tools.hmi_deployer.ai_review import apply_review
        self.assertIn("logo", _ids(self.project))
        made = apply_review(self.project, [{"op": "remove", "id": "logo"}], self.registry)
        self.assertEqual(made, ["removed logo"])
        self.assertNotIn("logo", _ids(self.project))
        self.assertIn("siteName", _ids(self.project))
        self.assertIn("titleBox", _ids(self.project), "recompiled: the strip is rebuilt")

    def test_text_only_goes_when_a_finding_names_it(self):
        # Left to its eyes Ornith removed the plant's name once the logo had gone.
        from tools.hmi_deployer.ai_review import apply_review
        made = apply_review(self.project, [{"op": "remove", "id": "siteName"}], self.registry)
        self.assertEqual(made, [])
        made = apply_review(self.project, [{"op": "remove", "id": "siteName"}], self.registry,
                            findings=[{"kind": "twice", "ids": ["siteName", "x"], "message": ""}])
        self.assertEqual(made, ["removed siteName"])

    def test_readings_buttons_and_the_main_picture_stay(self):
        from tools.hmi_deployer.ai_review import apply_review
        before = _ids(self.project)
        made = apply_review(self.project, [{"op": "remove", "id": "processDiagram"},
                                           {"op": "remove", "id": "btnFurnace"},
                                           {"op": "remove", "id": "hotBlastTemp"},
                                           {"op": "remove", "id": "nope"}], self.registry,
                            findings=[{"kind": "overlap", "ids": ["btnFurnace", "hotBlastTemp"],
                                       "message": ""}])
        self.assertEqual(made, [])
        self.assertEqual(_ids(self.project), before)

    def test_a_recrop_clears_the_source_so_apply_cuts_it_again(self):
        from designer.layout.compiler import CROP_MARK
        from tools.hmi_deployer.ai_review import apply_review, _walk
        picture = next(w for w, _r, _p in _walk(self.project.pages[0].widgets) if w.id == "processDiagram")
        picture.properties["source"] = "assets/processDiagram.png"
        made = apply_review(self.project, [{"op": "crop", "id": "processDiagram", "crop": [0, 100, 700, 840]}],
                            self.registry)
        self.assertEqual(made, ["re-cropped processDiagram"])
        picture = next(w for w, _r, _p in _walk(self.project.pages[0].widgets) if w.id == "processDiagram")
        self.assertEqual(picture.properties["source"], "")
        self.assertTrue(picture.properties[CROP_MARK])

    def test_set_takes_declared_properties_only(self):
        from tools.hmi_deployer.ai_review import apply_review
        # status is a ShAnnunciator here: it has text, not value.
        made = apply_review(self.project, [
            {"op": "set", "id": "status", "property": "value", "value": "ONLINE"},     # not declared
            {"op": "set", "id": "status", "property": "_crop", "value": 1},
            {"op": "set", "id": "status", "property": "text", "value": "STATUS: ON-LINE"}], self.registry)
        self.assertEqual(made, ["set status.text"])


class Reply(unittest.TestCase):
    def test_fixes_are_read_from_the_reply(self):
        from tools.hmi_deployer.ai_review import parse_review
        reply = ('{"issues": ["logo is the name"], "fixes": [{"op": "remove", "id": "logo"}, '
                 '{"op": "crop"}, "junk"]}')
        self.assertEqual(parse_review(reply), [{"op": "remove", "id": "logo"}])
        self.assertEqual(parse_review(""), [])
        self.assertEqual(parse_review("no json here"), [])

    def test_the_brief_lists_widgets_findings_and_the_strip_pictures(self):
        from tools.hmi_deployer.ai_review import review_brief, review_prompt, strip_pictures
        project = _project()
        shown = strip_pictures(project)
        self.assertEqual([w.id for w in shown], ["logo"])
        brief = review_brief(project, project.pages[0], [{"kind": "clipped", "ids": ["status"],
                                                          "message": "status: cut"}], shown)
        self.assertIn("processDiagram (Image)", brief)
        self.assertIn("cut from the reference at", brief)
        self.assertIn("status: cut", brief)
        self.assertIn("Image 3 is picture logo", brief)
        self.assertIn("remove", review_prompt())


class TabAppliesTheReview(unittest.TestCase):
    def test_a_review_reply_lands_on_the_canvas_when_it_does_no_harm(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from tools.hmi_deployer.ai_tab import AIDesignTab
        from tools.hmi_deployer.ai_review import _walk
        tab = AIDesignTab()
        self.addCleanup(tab.deleteLater)
        project = _project()
        project._reference_images = ["ref"]
        tab.last_project = project
        turn = mock.MagicMock()
        tab._review = {"turn": turn, "project": project, "round": 2, "findings": [],
                       "text": ['{"issues": [], "fixes": [{"op": "remove", "id": "logo"}]}']}
        with mock.patch.object(tab, "apply_to_canvas") as applied:
            tab._on_review_done()
        self.assertIsNot(tab.last_project, project)
        self.assertNotIn("logo", {w.id for w, _r, _p in _walk(tab.last_project.pages[0].widgets)})
        applied.assert_called_once()
        self.assertEqual(turn.note_review.call_args[0][1], "ok")
        # A design replaced meanwhile is not touched.
        tab._review = {"turn": turn, "project": project, "round": 2, "findings": [],
                       "text": ['{"fixes": [{"op": "remove", "id": "logo"}]}']}
        current = tab.last_project
        tab._on_review_done()
        self.assertIs(tab.last_project, current)


if __name__ == "__main__":
    unittest.main()
