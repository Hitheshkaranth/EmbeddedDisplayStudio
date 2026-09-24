"""
tests/test_layout_fit.py
Layer: Test

Making an AI design fit its screen (designer/layout/fit.py), the layouts it
leans on (the twin archetype, card grids for pages of readouts) and the
scale repairs of the style pass.

The evidence is tests/fixtures/layout/fighter-jet.edsui: a real vLLM run of a
fighter-jet dual-engine brief, 35 widgets for a 1024x768 panel, which polish
alone left with 33 overlapping pairs and RPM dials reading 98400 on a 0..1
scale.
"""

import copy
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from designer.layout import fit  # noqa: E402
from designer.layout.archetypes import archetype_for  # noqa: E402
from designer.layout.polish import polish  # noqa: E402
from designer.layout.style import live_readouts, paired_ranges, sane_ranges  # noqa: E402
from designer.model import DesignerBinding, DesignerPage, DesignerProject, DesignerWidget  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402

FIGHTER = REPO_ROOT / "tests" / "fixtures" / "layout" / "fighter-jet.edsui"


def overlapping_pairs(page):
    """Pairs of non-container widgets whose boxes intersect."""
    flat = [w for w in page.widgets if w.type not in ("ShCard", "Rectangle")]
    pairs = []
    for i, a in enumerate(flat):
        for b in flat[i + 1:]:
            A, B = a.geometry, b.geometry
            if (min(A["x"] + A["width"], B["x"] + B["width"]) > max(A["x"], B["x"])
                    and min(A["y"] + A["height"], B["y"] + B["height"]) > max(A["y"], B["y"])):
                pairs.append((a.id, b.id))
    return pairs


def widget(kind, wid, props=None, bindings=None, w=200, h=200):
    return DesignerWidget(kind, wid, {"x": 0, "y": 0, "width": w, "height": h},
                          dict(props or {}), dict(bindings or {}))


class ComposeTheFighterDesign(unittest.TestCase):
    """The real run: every page composed with nothing stacked, and deployable."""

    @classmethod
    def setUpClass(cls):
        cls.registry = default_registry()
        cls.original = DesignerProject.load(str(FIGHTER))
        cls.project = copy.deepcopy(cls.original)
        cls.report, cls.notes = fit.compose_project(
            cls.project, cls.registry, polish, brief="fighter jet dual engine monitoring dashboard")

    def test_the_design_did_not_fit_as_one_page(self):
        self.assertGreater(fit.load(self.original, self.original.pages[0], self.registry),
                           fit.FILL_LIMIT)
        self.assertGreater(len(self.project.pages), 1)
        self.assertTrue(self.notes)

    def test_no_page_has_overlapping_widgets(self):
        for page in self.project.pages:
            self.assertEqual(overlapping_pairs(page), [], page.name)

    def test_nothing_is_lost(self):
        before = {w.id for w in self.original.all_widgets()}
        after = {w.id for w in self.project.all_widgets() if not w.properties.get(fit.NAV_MARK)}
        # The style pass may drop the model's own captions; it never drops a
        # reading, control or instrument.
        lost = {i for i in before - after if not i.endswith("Caption")}
        self.assertEqual(lost, set())

    def test_every_detail_page_links_both_ways_and_validates(self):
        overview = self.project.pages[0]
        targets = {w.actions["clicked"].page for w in overview.widgets if w.properties.get(fit.NAV_MARK)}
        for page in self.project.pages[1:]:
            self.assertIn(page.id, targets)
            backs = [w for w in page.widgets if w.properties.get(fit.NAV_MARK)]
            self.assertEqual([b.actions["clicked"].page for b in backs], [overview.id])
        self.assertEqual([str(i) for i in self.project.validate(self.registry)], [])

    def test_navigation_is_one_row_along_the_foot(self):
        overview = self.project.pages[0]
        nav = [w for w in overview.widgets if w.properties.get(fit.NAV_MARK)]
        content = [w for w in overview.widgets if not w.properties.get(fit.NAV_MARK)]
        self.assertEqual(len({b.geometry["y"] for b in nav}), 1)
        strip_top = nav[0].geometry["y"]
        for item in content:
            self.assertLessEqual(item.geometry["y"] + item.geometry["height"], strip_top, item.id)

    def test_the_two_engines_are_a_mirrored_pair_on_one_scale(self):
        dials = [w for w in self.project.pages[0].widgets if w.type == "ShClusterGauge"]
        self.assertEqual(len(dials), 2)
        left, right = sorted(dials, key=lambda w: w.geometry["x"])
        self.assertEqual((left.geometry["width"], left.geometry["y"]),
                         (right.geometry["width"], right.geometry["y"]))
        self.assertEqual(left.properties["maximumValue"], right.properties["maximumValue"])
        self.assertGreaterEqual(left.properties["maximumValue"], 98400)
        self.assertEqual((left.properties["readout"], right.properties["readout"]), ("", ""))


class FitsAlreadyIsLeftAlone(unittest.TestCase):
    def test_a_small_design_stays_one_page(self):
        registry = default_registry()
        project = DesignerProject()
        project.screen.width, project.screen.height = 1024, 768
        project.pages[0].widgets = [widget("ShGauge", "g"), widget("ShButton", "b", w=120, h=48)]
        self.assertEqual(fit.split_to_fit(project, project.pages[0], registry), [])
        self.assertEqual(len(project.pages), 1)


class ArchetypeChoice(unittest.TestCase):
    def test_a_pair_of_dials_is_a_twin_page(self):
        page = DesignerPage("main", "Main", [widget("ShClusterGauge", "a"), widget("ShClusterGauge", "b"),
                                             widget("ShNumDisplay", "n", w=120, h=60)])
        self.assertEqual(archetype_for("engine cluster", 3, page).id, "twin")

    def test_a_brief_that_says_dual_asks_for_the_twin(self):
        self.assertEqual(archetype_for("dual engine monitor", 6).id, "twin")

    def test_a_page_of_readouts_is_a_grid(self):
        page = DesignerPage("p", "P", [widget("ShNumDisplay", f"n{i}", w=120, h=60) for i in range(4)])
        self.assertEqual(archetype_for("engine", 4, page).id, "card-grid")


class ScaleRepairs(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_a_threshold_past_the_end_widens_the_range(self):
        gauge = widget("ShGauge", "egt", {"minimum": 0, "maximum": 100},
                       {"value": DesignerBinding("eng.egt", warning="> 850", critical="> 950")})
        notes = sane_ranges(DesignerPage("p", "P", [gauge]), self.registry)
        self.assertTrue(notes)
        self.assertGreaterEqual(gauge.properties["maximum"], 950)

    def test_a_range_that_already_fits_is_untouched(self):
        gauge = widget("ShGauge", "p", {"minimum": 0, "maximum": 100, "value": 40})
        self.assertEqual(sane_ranges(DesignerPage("p", "P", [gauge]), self.registry), [])
        self.assertEqual(gauge.properties["maximum"], 100)

    def test_a_fraction_scale_with_a_real_readout_becomes_the_real_scale(self):
        dial = widget("ShClusterGauge", "rpm", {"minimumValue": 0.0, "maximumValue": 1.0,
                                                 "value": 0.82, "redlineFrom": 0.95, "readout": "98400"},
                      {"value": DesignerBinding("eng.rpm1")})
        sane_ranges(DesignerPage("p", "P", [dial]), self.registry)
        self.assertEqual(dial.properties["value"], 98400)
        self.assertEqual(dial.properties["maximumValue"], 120000)
        self.assertAlmostEqual(dial.properties["redlineFrom"], 114000)

    def test_a_bound_gauge_shows_its_live_value_not_a_fixed_readout(self):
        dial = widget("ShClusterGauge", "rpm", {"readout": "98400"}, {"value": DesignerBinding("eng.rpm1")})
        self.assertTrue(live_readouts(DesignerPage("p", "P", [dial]), self.registry))
        self.assertEqual(dial.properties["readout"], "")
        unbound = widget("ShClusterGauge", "demo", {"readout": "88"})
        self.assertEqual(live_readouts(DesignerPage("p", "P", [unbound]), self.registry), [])

    def test_a_pair_of_instruments_shares_one_scale(self):
        a = widget("ShClusterGauge", "rpm1", {"label": "RPM", "maximumValue": 120000.0})
        b = widget("ShClusterGauge", "rpm2", {"label": "RPM", "maximumValue": 150000.0})
        other = widget("ShClusterGauge", "speed", {"label": "KTS", "maximumValue": 800.0})
        paired_ranges(DesignerPage("p", "P", [a, b, other]), self.registry)
        self.assertEqual((a.properties["maximumValue"], b.properties["maximumValue"]), (150000.0, 150000.0))
        self.assertEqual(other.properties["maximumValue"], 800.0)


if __name__ == "__main__":
    unittest.main()
