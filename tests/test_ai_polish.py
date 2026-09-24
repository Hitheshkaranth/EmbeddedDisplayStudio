"""designer/layout/polish.py and the AI tab that uses it .

The claim this file holds the pipeline to: polishing the real AI draft
closes most of the gap to a hand-built screen, and never changes what the
design *is* -- only how it is laid out and styled.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.layout import PolishReport, critique, polish  # noqa: E402
from designer.layout.polish import polish_candidates  # noqa: E402
from designer.model import DesignerProject  # noqa: E402
from designer.palette import default_registry  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "layout"


def _load(name):
    project = DesignerProject.load(str(FIXTURES / name))
    return project, project.pages[0]


class PolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.registry = default_registry()

    def test_polishing_the_real_draft_closes_the_gap(self):
        good_project, good_page = _load("hand-built.edsui")
        project, page = _load("ai-baseline.edsui")
        target = critique(good_project, good_page, self.registry).score
        before = critique(project, page, self.registry).score
        report = polish(project, page, self.registry, brief="engine data summary")
        self.assertIsInstance(report, PolishReport)
        after = critique(project, page, self.registry).score
        self.assertEqual(round(after, 3), round(report.after.score, 3))
        self.assertGreater(after, before + 15, f"{before:.0f} -> {after:.0f}")
        self.assertGreaterEqual(after, min(75.0, target - 5))
        self.assertGreater(report.gain, 0)
        self.assertEqual(report.after.scores["overlap"], 100)
        self.assertFalse([i for i in report.after.issues if i.severity == "error"],
                         [i.detail for i in report.after.issues if i.severity == "error"])

    def test_polish_changes_layout_not_meaning(self):
        project, page = _load("ai-baseline.edsui")
        before = {w.id: (w.type, dict(w.properties), set(w.bindings), set(w.actions))
                  for w in page.widgets}
        polish(project, page, self.registry, brief="engine data summary")

        def walk(widgets):
            for w in widgets:
                yield w
                yield from walk(w.children)

        after = {w.id: w for w in walk(page.widgets)}
        for wid, (wtype, props, bindings, actions) in before.items():
            self.assertIn(wid, after, f"{wid} disappeared")
            self.assertEqual(after[wid].type, wtype)
            self.assertEqual(set(after[wid].bindings), bindings)
            self.assertEqual(set(after[wid].actions), actions)
            # The style pass may set presentation properties; it may not
            # change what a widget says or is bound to.
            for key in ("text", "label", "title", "unit", "value"):
                if key in props:
                    self.assertEqual(after[wid].properties.get(key), props[key], f"{wid}.{key}")

    def test_polish_is_idempotent(self):
        project, page = _load("ai-baseline.edsui")
        polish(project, page, self.registry, brief="engine data summary")
        first = [(w.id, dict(w.geometry)) for w in page.widgets]
        second = polish(project, page, self.registry, brief="engine data summary")
        self.assertEqual([(w.id, dict(w.geometry)) for w in page.widgets], first)
        self.assertLessEqual(abs(second.gain), 1.0)

    def test_candidates_are_ranked(self):
        project, page = _load("ai-baseline.edsui")
        original = [(w.id, dict(w.geometry)) for w in page.widgets]
        candidates = polish_candidates(project, page, self.registry, brief="engine data summary", limit=3)
        self.assertGreaterEqual(len(candidates), 2)
        scores = [verdict.score for _page, verdict, _archetype in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len({a for _p, _v, a in candidates}), len(candidates))
        # The page it was asked about is untouched.
        self.assertEqual([(w.id, dict(w.geometry)) for w in page.widgets], original)

    def test_a_hand_built_screen_is_not_made_worse(self):
        project, page = _load("hand-built.edsui")
        before = critique(project, page, self.registry).score
        polish(project, page, self.registry)
        after = critique(project, page, self.registry).score
        self.assertGreaterEqual(after, before - 2)


class AITabWiringTests(unittest.TestCase):
    """The pipeline the AI tab runs: the prompt asks for a composition, and
    every generated section is polished before it reaches the canvas."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_system_prompt_states_the_composition_rules(self):
        from tools.hmi_deployer.ai_generator import build_system_prompt
        prompt = build_system_prompt(default_registry(), 1024, 768,
                                     brief="engine data summary with gauges")
        lowered = prompt.lower()
        for word in ("grid", "overlap", "align"):
            self.assertIn(word, lowered, f"the prompt should speak about {word}")
        self.assertIn("1024", prompt)

    def test_generated_sections_are_polished(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        generator = AIDesignGenerator(default_registry())
        self.assertTrue(hasattr(generator, "polish_enabled"))
        payload = (
            '```json\n{"name": "Draft", "pages": [{"id": "main", "name": "Main", "widgets": ['
            '{"type": "ShFuelQuantity", "id": "fuelQty", "geometry": {"x": 80, "y": 610, "width": 864, "height": 100}},'
            '{"type": "ShButton", "id": "startStopBtn", "geometry": {"x": 864, "y": 560, "width": 120, "height": 120}},'
            '{"type": "ShClusterGauge", "id": "rpmGauge", "geometry": {"x": 312, "y": 184, "width": 400, "height": 400}}'
            ']}]}\n```'
        )
        project = generator.generate(payload, 1024, 768)
        self.assertIsNotNone(project)
        page = project.pages[0]
        verdict = critique(project, page, default_registry())
        self.assertEqual(verdict.scores["overlap"], 100, "the draft's overlap should be gone")
        self.assertGreaterEqual(verdict.score, 70)




# ---------------------------------------------------------------------------
# Further polish tests.
# ---------------------------------------------------------------------------

class PolishPipelineTests(unittest.TestCase):
    """The rest of the polish loop: variants,
    rounds, captions, and what happens when a pass falls over."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.registry = default_registry()

    def test_every_variant_tried_is_reported_best_first(self):
        project, page = _load("ai-baseline.edsui")
        report = polish(project, page, self.registry, brief="engine data summary", variants=3)
        self.assertEqual(len(report.candidates), 3)
        scores = [score for _archetype, score in report.candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(report.archetype, report.candidates[0][0])
        self.assertEqual(round(report.after.score, 2), round(report.candidates[0][1], 2))

    def test_extra_rounds_never_lower_the_score(self):
        project, one = _load("ai-baseline.edsui")
        _project, many = _load("ai-baseline.edsui")
        first = polish(project, one, self.registry, brief="engine data summary", rounds=1)
        second = polish(_project, many, self.registry, brief="engine data summary", rounds=6)
        self.assertGreaterEqual(second.after.score, first.after.score)
        self.assertLessEqual(second.rounds, 6)
        self.assertGreaterEqual(second.rounds, 1)

    def test_a_pass_that_raises_leaves_the_page_exactly_as_it_was(self):
        import importlib
        arrange_module = importlib.import_module("designer.layout.arrange")
        project, page = _load("ai-baseline.edsui")
        before = [(w.id, dict(w.geometry)) for w in page.widgets]
        original = arrange_module.arrange

        def explode(*_args, **_kwargs):
            raise RuntimeError("arrange fell over")

        arrange_module.arrange = explode
        try:
            with self.assertRaises(RuntimeError):
                polish(project, page, self.registry, brief="engine data summary")
        finally:
            arrange_module.arrange = original
        self.assertEqual([(w.id, dict(w.geometry)) for w in page.widgets], before)

    def test_a_renderer_that_cannot_render_is_not_fatal(self):
        class DeadRenderer:
            available = True

            def render_page_sync(self, *_args, **_kwargs):
                raise OSError("hmi-ui is not there")

        project, page = _load("ai-baseline.edsui")
        report = polish(project, page, self.registry, brief="engine data summary",
                        renderer=DeadRenderer())
        self.assertGreater(report.gain, 0)
        self.assertIsNone(report.after.scores["clipping"])

    def test_captions_are_rebuilt_rather_than_stacked(self):
        project, page = _load("ai-baseline.edsui")
        polish(project, page, self.registry, brief="engine data summary")
        first = [w.id for w in page.widgets if w.type == "Text"]
        polish(project, page, self.registry, brief="engine data summary")
        self.assertEqual([w.id for w in page.widgets if w.type == "Text"], first)
        self.assertEqual(len(first), len(set(first)))

    def test_candidates_leave_the_project_alone(self):
        project, page = _load("ai-baseline.edsui")
        pages = list(project.pages)
        polish_candidates(project, page, self.registry, brief="engine data summary", limit=4)
        self.assertEqual(list(project.pages), pages)
        self.assertIs(project.pages[0], page)

    def test_summary_line_reads_as_the_run_log_shows_it(self):
        from designer.layout.polish import summary
        project, page = _load("ai-baseline.edsui")
        report = polish(project, page, self.registry, brief="engine data summary")
        line = summary(report)
        self.assertTrue(line.startswith("Composed: "), line)
        self.assertIn(report.archetype, line)
        self.assertIn("→", line)


class GeneratorPolishTests(unittest.TestCase):
    """AIDesignGenerator.generate: composed on the way out, never lost."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    PAYLOAD = (
        '```json\n{"name": "Draft", "pages": [{"id": "main", "name": "Main", "widgets": ['
        '{"type": "ShFuelQuantity", "id": "fuelQty", "geometry": {"x": 80, "y": 610, "width": 864, "height": 100}},'
        '{"type": "ShButton", "id": "startStopBtn", "geometry": {"x": 864, "y": 560, "width": 120, "height": 120},'
        ' "properties": {"text": "START"}, "actions": {"clicked": {"kind": "pulse", "tag": "do.start", "ms": 250}}},'
        '{"type": "ShClusterGauge", "id": "rpmGauge", "geometry": {"x": 312, "y": 184, "width": 400, "height": 400},'
        ' "bindings": {"value": {"tag": "ai.rpm"}}}'
        ']}]}\n```'
    )

    def generator(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        return AIDesignGenerator(default_registry())

    def test_polish_is_reported_and_keeps_the_design(self):
        generator = self.generator()
        project = generator.generate(self.PAYLOAD, 1024, 768)
        self.assertIsInstance(generator.last_polish, PolishReport)
        self.assertGreater(generator.last_polish.gain, 0)
        widget = next(w for w in project.all_widgets() if w.id == "startStopBtn")
        self.assertEqual(widget.properties["text"], "START")
        self.assertEqual(widget.actions["clicked"].tag, "do.start")
        self.assertEqual(next(w for w in project.all_widgets() if w.id == "rpmGauge")
                         .bindings["value"].tag, "ai.rpm")

    def test_polish_can_be_switched_off(self):
        generator = self.generator()
        generator.polish_enabled = False
        project = generator.generate(self.PAYLOAD, 1024, 768)
        fuel = next(w for w in project.all_widgets() if w.id == "fuelQty")
        self.assertEqual(fuel.geometry["width"], 864)
        self.assertIsNone(generator.last_polish)

    def test_a_polish_failure_never_loses_a_design(self):
        import importlib
        arrange_module = importlib.import_module("designer.layout.arrange")
        generator = self.generator()
        original = arrange_module.arrange

        def explode(*_args, **_kwargs):
            raise RuntimeError("arrange fell over")

        arrange_module.arrange = explode
        try:
            project = generator.generate(self.PAYLOAD, 1024, 768)
        finally:
            arrange_module.arrange = original
        self.assertIsNotNone(project)
        self.assertEqual(len(list(project.all_widgets())), 3)
        self.assertIsNone(generator.last_polish)

    def test_the_prompt_keeps_its_contract_and_gains_a_composition(self):
        from tools.hmi_deployer.ai_generator import build_system_prompt
        prompt = build_system_prompt(default_registry(), 1024, 768,
                                     brief="engine data summary with RPM and fuel gauges")
        for kept in ("```json", "section.complete=true", "at most 8 widgets", "1024x768"):
            self.assertIn(kept, prompt)
        for composed in ("12-column grid", "must not overlap", "ShClusterGauge 240x240"):
            self.assertIn(composed, prompt)
        # The real grid's numbers, not invented ones.
        from designer.layout import grid as grid_module
        grid = grid_module.grid_for(1024, 768)
        self.assertIn(f"{grid.margin} px", prompt)
        self.assertIn(f"{grid.gutter} px", prompt)


class TidyUpActionTests(unittest.TestCase):
    """The Designer's own way in: one toolbar action, one undo step."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def workspace(self):
        from designer.ui import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        # Tidy up is a geometry test, not a picture one: the live QML
        # previews would keep rendering in the background for no gain.
        workspace.live_action.setChecked(False)
        workspace.toggle_live_previews(False)
        return workspace

    def test_tidy_up_composes_the_page_in_one_undoable_step(self):
        from PySide6.QtWidgets import QToolBar
        workspace = self.workspace()
        project = DesignerProject.load(str(FIXTURES / "ai-baseline.edsui"))
        workspace.load_project(project)
        page = workspace.current_page
        before = [(w.id, dict(w.geometry)) for w in page.widgets]
        depth = workspace.undo_stack.count()

        item = next(action for bar in workspace.findChildren(QToolBar)
                    for action in bar.actions() if action.text() == "Tidy up")
        item.trigger()

        page = workspace.current_page
        self.assertNotEqual([(w.id, dict(w.geometry)) for w in page.widgets], before)
        self.assertEqual(workspace.undo_stack.count(), depth + 1)
        self.assertEqual(workspace.undo_stack.command(depth).text(), "Tidy up")
        workspace.undo_stack.undo()
        self.assertEqual([(w.id, dict(w.geometry)) for w in workspace.current_page.widgets], before)
        workspace.undo_stack.redo()
        self.assertNotEqual([(w.id, dict(w.geometry)) for w in workspace.current_page.widgets], before)

    def test_tidy_up_on_an_empty_page_does_nothing_and_says_so(self):
        from PySide6.QtWidgets import QToolBar
        workspace = self.workspace()
        workspace.current_page.widgets.clear()
        workspace._load_page()
        depth = workspace.undo_stack.count()
        item = next(action for bar in workspace.findChildren(QToolBar)
                    for action in bar.actions() if action.text() == "Tidy up")
        item.trigger()
        self.assertEqual(workspace.undo_stack.count(), depth)



class AITabWiringExtraTests(unittest.TestCase):
    """What the tab does with a PolishReport once the section is on the canvas."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_the_run_log_says_what_the_composition_did(self):
        from tools.hmi_deployer.ai_tab import ExecutionShell
        project, page = _load("ai-baseline.edsui")
        report = polish(project, page, default_registry(), brief="engine data summary")
        shell = ExecutionShell()
        self.addCleanup(shell.deleteLater)
        row = shell.note_polish(report)
        self.assertIsNotNone(row)
        self.assertTrue(row.title.text().startswith("Composed: "), row.title.text())
        self.assertIn(report.archetype, row.title.text())
        # No polish (it was switched off, or it failed): no row at all.
        self.assertIsNone(shell.note_polish(None))

    def test_a_clicked_thumbnail_offers_its_own_project(self):
        from PySide6.QtGui import QImage
        from tools.hmi_deployer.ai_tab import VariantStrip, VariantThumb
        image = QImage(64, 48, QImage.Format_ARGB32)
        image.fill(0)
        strip = VariantStrip()
        self.addCleanup(strip.deleteLater)
        taken = []
        strip.picked.connect(taken.append)
        strip.show_variants([("hero-centre", 88.0, image, "first"),
                             ("thirds", 81.0, image, "second"),
                             ("split", 74.0, image, "third"),
                             ("card-grid", 70.0, image, "fourth")])
        thumbs = strip.findChildren(VariantThumb)
        self.assertEqual(len(thumbs), 3, "at most three are offered")
        thumbs[1].clicked.emit()
        self.assertEqual(taken, ["second"])
        strip.clear()
        self.assertEqual(strip.findChildren(VariantThumb), [])

    def test_the_strip_is_skipped_without_the_panel_renderer(self):
        from tools.hmi_deployer.ai_tab import AIDesignTab, TurnWidget
        tab = AIDesignTab()
        self.addCleanup(tab.deleteLater)
        tab._variant_renderer_cache = False      # "asked, and there is no binary"
        turn = TurnWidget("engine data summary")
        self.addCleanup(turn.deleteLater)
        project = DesignerProject.load(str(FIXTURES / "ai-baseline.edsui"))
        tab._offer_variants(turn, project)
        self.assertFalse(turn.variant_strip.isVisible())


if __name__ == "__main__":
    unittest.main()
