"""The property panel must not delete an editor that is still talking.

Typing a new font size crashed the Studio outright -- an access violation
in Qt6Widgets.dll, with nothing in the log, because the crash was native
and not a Python exception. QFormLayout.removeRow deletes the row's
widgets immediately; handling propertyEdited rebuilds the whole panel; so
the spin box asked Qt to free the spin box in the middle of its own
valueChanged, and Qt returned into freed memory.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "gui"))

from PySide6.QtWidgets import QApplication, QSpinBox

from designer.model import DesignerWidget
from designer.palette.widget_registry import default_registry
from designer.ui.designer_workspace import PropertyEditor

app = QApplication.instance() or QApplication([])


def _text(widget_id="title", size=18):
    return DesignerWidget("Text", widget_id, {"x": 0, "y": 0, "width": 200, "height": 40},
                          {"text": "Hello", "fontSize": size})


class PropertyEditorLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.panel = PropertyEditor(default_registry())

    def _font_size_box(self):
        for box in self.panel.findChildren(QSpinBox):
            label = self.panel.form.labelForField(box)
            if label is not None and "font" in label.text().lower():
                return box
        return None

    def test_the_font_size_editor_survives_its_own_signal(self):
        """The crash, reproduced: rebuild the panel from the editor's signal."""
        self.panel.set_widget(_text())
        box = self._font_size_box()
        self.assertIsNotNone(box, "no font size editor to test")

        # Exactly what the workspace does: a property edit reloads the page,
        # which reselects the widget, which rebuilds this panel.
        self.panel.propertyEdited.connect(lambda *_: self.panel.set_widget(_text()))
        box.setValue(48)

        # Before the fix this raised RuntimeError ("Internal C++ object
        # already deleted") in Python, and killed the process outright in a
        # packaged build, where the signal returns into Qt's own C++ frame.
        try:
            box.value()
        except RuntimeError as exc:
            self.fail("the editor was deleted inside its own signal: %s" % exc)

    def test_rebuilding_twice_over_leaves_one_form(self):
        self.panel.set_widget(_text())
        rows = self.panel.form.rowCount()
        for _ in range(5):
            self.panel.set_widget(_text())
        self.assertEqual(self.panel.form.rowCount(), rows)

    def test_an_empty_selection_clears_the_form(self):
        self.panel.set_widget(_text())
        self.panel.set_widget(None)
        self.assertEqual(self.panel.form.rowCount(), 1)   # the empty state

    def test_the_editor_still_reports_the_new_value(self):
        self.panel.set_widget(_text())
        seen = []
        self.panel.propertyEdited.connect(lambda name, value: seen.append((name, value)))
        box = self._font_size_box()
        box.setValue(32)
        self.assertIn(("fontSize", 32), seen)


if __name__ == "__main__":
    unittest.main()
