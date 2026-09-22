"""designer/layout/polish.py and the AI tab that uses it (W4 gate).

FROZEN: the minimum W4 must pass; add more below, never change these.

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


if __name__ == "__main__":
    unittest.main()
