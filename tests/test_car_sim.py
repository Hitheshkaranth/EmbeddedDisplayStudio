"""sim.car.* -- a drive cycle, not a sweep.

A cluster on the bench should move the way a car moves: pull away through
the gears, cruise, sprint, brake, stop. These tests pin the generator's
expression, the demo template, and the cycle's shape at known moments of
the page clock.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QUrl  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.canvas.qml_previews import _StillBus  # noqa: E402
from designer.generators.qml_generator import CAR_TAGS, QmlGenerator, _sim_expression  # noqa: E402
from designer.model import DesignerProject, DesignerWidget  # noqa: E402
from designer.palette import default_registry  # noqa: E402


class CarSimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()

    def test_every_car_tag_becomes_a_car_call(self):
        for name in CAR_TAGS:
            self.assertEqual(_sim_expression("sim.car." + name), f'car("{name}")')

    def test_the_demo_template_validates_and_needs_no_live_tags_to_move(self):
        project = DesignerProject.load(str(REPO_ROOT / "designer" / "templates" / "automotive_cluster_demo.edsui"))
        self.assertEqual(project.validate(self.registry), [])
        qml = QmlGenerator(self.registry).generate(project)["Main.qml"]
        self.assertIn('readout: car("speed")', qml)
        self.assertIn("function carSpeed(t)", qml)
        # Everything that moves is a sim value; only the drive-mode write is a real tag.
        self.assertEqual(project.required_tags(), ["mb.drive_mode"])

    def _page(self):
        project = DesignerProject()
        project.pages[0].widgets = [DesignerWidget(
            "ShClusterGauge", "g", {"x": 0, "y": 0, "width": 200, "height": 200},
            {"value": "sim.car.rpm_k", "readout": "sim.car.speed", "caption": "sim.car.gear"})]
        root_dir = tempfile.mkdtemp()
        paths = QmlGenerator(self.registry).write(project, os.path.join(root_dir, "generated"), root_dir)
        engine = QQmlEngine()
        engine.addImportPath(str(REPO_ROOT / "ui" / "qml"))
        engine.rootContext().setContextProperty("Bus", _StillBus())
        engine.rootContext().setContextProperty("Tags", QObject())
        component = QQmlComponent(engine, QUrl.fromLocalFile(paths[0]))
        item = component.create()
        self.assertEqual([e.toString() for e in component.errors()], [])
        self._keep = (engine, component, item)
        gauge = next(c for c in item.childItems() if c.property("readoutUnit") is not None)
        return item, gauge

    def test_the_cycle_idles_pulls_away_sprints_and_stops(self):
        item, gauge = self._page()

        def at(t):
            item.setProperty("_t", float(t))
            return (float(gauge.property("value")), str(gauge.property("readout")), str(gauge.property("caption")))

        rpm_idle, speed_idle, gear_idle = at(1.0)
        self.assertEqual(speed_idle, "0")
        self.assertLess(rpm_idle, 1.0)                 # ~850 rpm shown as 0.85 on the x1000 scale
        self.assertEqual(gear_idle, "P")
        rpm_pull, speed_pull, gear_pull = at(8.0)
        self.assertGreater(int(speed_pull), 20)
        self.assertEqual(gear_pull, "D")
        rpm_sprint, speed_sprint, _ = at(30.5)
        self.assertGreater(int(speed_sprint), 125)
        self.assertGreater(rpm_sprint, rpm_pull)
        self.assertGreater(rpm_sprint, 5.0)             # up near the redline in the sprint
        _, speed_end, _ = at(58.0)
        self.assertEqual(speed_end, "0")
        # The lap repeats.
        self.assertEqual(at(61.0)[1], at(1.0)[1])


if __name__ == "__main__":
    unittest.main()
