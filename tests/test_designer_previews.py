"""
tests/test_designer_previews.py
Layer: Test (W11)

Pins that the Designer canvas draws each component rather than a labelled box,
and that a Text's declared alignment is what the canvas and the generated QML
both act on.

The complaint these were written for: every widget on the canvas rendered as
the same rounded rectangle with its caption centred in it, so a Button, a
Gauge, a Progress bar and an Alarm indicator were indistinguishable until the
page was generated and deployed. Laying out a screen means judging it by eye,
and there was nothing to judge. Text had no alignment property at all --
paint() hardcoded AlignLeft|AlignTop -- so a caption could not be centred or
right-aligned anywhere in the tool.

These tests render to a QImage rather than inspecting painter calls: what
matters is that two components no longer look the same, which is a property of
the pixels and not of the code path that produced them.

Requires PySide6; skipped elsewhere.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - environment without PySide6
    HAVE_QT = False

if HAVE_QT:
    from designer.canvas import widget_previews
    from designer.generators import QmlGenerator
    from designer.model import DesignerPage, DesignerProject, DesignerWidget
    from designer.palette.widget_registry import default_registry


@unittest.skipUnless(HAVE_QT, "PySide6 is required for canvas previews")
class WidgetPreviews(unittest.TestCase):
    """Renders each painter onto a bitmap and compares what comes out."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()

    def render(self, widget_type, props, size=(200, 120)):
        """Paint one widget preview and return the image."""
        painter_fn = widget_previews.painter_for(widget_type)
        self.assertIsNotNone(painter_fn, f"no preview painter for {widget_type}")
        image = QImage(size[0], size[1], QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter_fn(painter, QRectF(0, 0, size[0], size[1]), props, None)
        painter.end()
        return image

    @staticmethod
    def _ink(image):
        """Every colour actually laid down, as a set."""
        return {
            image.pixel(x, y)
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        }

    # -- every type is drawn, and drawn differently ----------------------

    def test_every_registered_type_has_a_preview_or_a_stated_reason(self):
        """A type with no painter falls back to the box this work replaced.

        Image is the one deliberate omission: resolving a relative source needs
        the project directory, which only the canvas item holds.
        """
        missing = [
            definition.type for definition in self.registry.definitions()
            if not widget_previews.has_preview(definition.type)
        ]
        self.assertEqual(missing, ["Image"], f"types drawn as a generic box: {missing}")

    def test_components_do_not_all_look_the_same(self):
        """The complaint, stated as an assertion.

        Four components that were previously one rounded box with a caption.
        Comparing the raw bytes is enough: identical drawings are the bug.
        """
        drawings = {
            "ShButton": self.render("ShButton", {"text": "Start", "variant": "default"}),
            "ShProgress": self.render("ShProgress", {"value": 0.5}),
            "ShGauge": self.render("ShGauge", {"value": 40.0, "minimum": 0.0,
                                               "maximum": 100.0}),
            "ShAlert": self.render("ShAlert", {"title": "Alarm",
                                               "variant": "destructive"}),
        }
        seen = {}
        for name, image in drawings.items():
            data = bytes(image.constBits())
            self.assertNotIn(
                data, seen,
                f"{name} renders identically to {seen.get(data)}",
            )
            seen[data] = name

    def test_a_button_carries_its_variant_colour(self):
        """variant is the property that decides what a button looks like."""
        default = self._ink(self.render("ShButton", {"text": "Go", "variant": "default"}))
        destructive = self._ink(self.render("ShButton", {"text": "Go",
                                                         "variant": "destructive"}))

        self.assertIn(widget_previews.token("primary").rgb() & 0xFFFFFF,
                      {c & 0xFFFFFF for c in default})
        self.assertIn(widget_previews.token("destructive").rgb() & 0xFFFFFF,
                      {c & 0xFFFFFF for c in destructive})

    def test_a_status_indicator_shows_its_state(self):
        """The four machine states are the whole point of the component."""
        colours = {
            state: {c & 0xFFFFFF for c in self._ink(
                self.render("ShStatDot", {"state": state}, size=(36, 36)))}
            for state in ("ok", "warn", "fault", "idle")
        }
        for state, expected in (("ok", "success"), ("warn", "warning"),
                                ("fault", "destructive")):
            with self.subTest(state=state):
                self.assertIn(widget_previews.token(expected).rgb() & 0xFFFFFF,
                              colours[state])
        self.assertNotEqual(colours["ok"], colours["fault"])

    def test_a_progress_bar_reflects_its_value(self):
        """An empty bar and a full one cannot be the same drawing."""
        empty = self.render("ShProgress", {"value": 0.0}, size=(200, 12))
        full = self.render("ShProgress", {"value": 1.0}, size=(200, 12))

        self.assertNotEqual(bytes(empty.constBits()), bytes(full.constBits()))
        primary = widget_previews.token("primary").rgb() & 0xFFFFFF
        self.assertIn(primary, {c & 0xFFFFFF for c in self._ink(full)})
        self.assertNotIn(primary, {c & 0xFFFFFF for c in self._ink(empty)})

    def test_a_gauge_past_its_fault_threshold_turns_destructive(self):
        """Thresholds are what a gauge is read for at a glance."""
        nominal = {c & 0xFFFFFF for c in self._ink(
            self.render("ShGauge", {"value": 10.0, "thresholdWarning": 70.0,
                                    "thresholdFault": 90.0}, size=(160, 160)))}
        faulted = {c & 0xFFFFFF for c in self._ink(
            self.render("ShGauge", {"value": 95.0, "thresholdWarning": 70.0,
                                    "thresholdFault": 90.0}, size=(160, 160)))}

        self.assertIn(widget_previews.token("success").rgb() & 0xFFFFFF, nominal)
        self.assertIn(widget_previews.token("destructive").rgb() & 0xFFFFFF, faulted)

    # -- text alignment --------------------------------------------------

    def test_text_alignment_changes_where_the_glyphs_land(self):
        """Left, centre and right have to produce three different drawings."""
        renders = {
            value: self.render("Text", {"text": "Hi", "fontSize": 18,
                                        "color": "#ffffff",
                                        "horizontalAlignment": value},
                               size=(200, 40))
            for value in ("Text.AlignLeft", "Text.AlignHCenter", "Text.AlignRight")
        }
        columns = {}
        for value, image in renders.items():
            painted = [x for y in range(image.height()) for x in range(image.width())
                       if image.pixelColor(x, y).alpha() > 0]
            self.assertTrue(painted, f"{value} drew no glyphs at all")
            columns[value] = sum(painted) / len(painted)

        self.assertLess(columns["Text.AlignLeft"], columns["Text.AlignHCenter"])
        self.assertLess(columns["Text.AlignHCenter"], columns["Text.AlignRight"])

    def test_the_registry_offers_the_three_alignments(self):
        """The inspector builds its combo straight from these choices."""
        choices = self.registry.get("Text").choices["horizontalAlignment"]

        for value in ("Text.AlignLeft", "Text.AlignHCenter", "Text.AlignRight"):
            self.assertIn(value, choices)

    def test_alignment_reaches_the_generated_qml(self):
        """A canvas that shows it and a panel that ignores it is worse than
        neither, so the property has to survive generation."""
        project = DesignerProject()
        page = project.pages[0] if project.pages else DesignerPage(id="p1", name="Page")
        if not project.pages:
            project.pages.append(page)
        page.widgets.append(DesignerWidget(
            id="caption", type="Text",
            geometry={"x": 0, "y": 0, "width": 140, "height": 32},
            properties={"text": "Centred", "horizontalAlignment": "Text.AlignHCenter"},
        ))

        qml = "\n".join(QmlGenerator(self.registry).generate(project).values())

        self.assertIn("horizontalAlignment: Text.AlignHCenter", qml,
                      "the alignment was quoted or dropped on the way to QML")


if __name__ == "__main__":
    unittest.main()
