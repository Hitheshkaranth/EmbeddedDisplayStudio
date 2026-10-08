"""Custom widgets: a group of kit widgets saved in the Studio, reused anywhere.

designer/palette/custom_widgets.py holds the library; the Designer saves a
selection into it, lists it in the palette's Custom section and inserts a
fresh copy as an Item container (so the panel runtime needs nothing new).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.model import DesignerBinding  # noqa: E402
from designer.palette.custom_widgets import CustomWidgetLibrary  # noqa: E402
from designer.ui import DesignerWorkspace  # noqa: E402


class CustomWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        os.environ["EDS_CUSTOM_WIDGETS_DIR"] = self.folder.name
        self.addCleanup(os.environ.pop, "EDS_CUSTOM_WIDGETS_DIR", None)
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.assertEqual(self.ws.custom_library.folder, self.folder.name)
        # A status tile: an icon tile and a value tile bound to a tag.
        self.ws.add_widget("ShIconTile", 100, 60)
        self.ws.add_widget("ShValueTile", 210, 70)
        page = self.ws.current_page.widgets
        self.tile, self.value = page[-2], page[-1]
        self.value.bindings["value"] = DesignerBinding(tag="hvac.cab_temp")
        self.ws._load_page()

    def _select(self, *models):
        self.ws.scene.clearSelection()
        for model in models:
            self.ws.scene.item_for_id(model.id).setSelected(True)

    def _palette_rows(self):
        section = self.ws.palette._custom_category
        return [section.child(i).data(0, Qt.UserRole) for i in range(section.childCount())]

    def test_a_selection_is_saved_relative_to_its_corner(self):
        self._select(self.tile, self.value)
        custom = self.ws.save_selection_as_custom(name="Cab Climate")
        path = os.path.join(self.folder.name, "cab-climate.edswidget")
        self.assertTrue(os.path.isfile(path))
        data = json.load(open(path, encoding="utf-8"))
        self.assertEqual(data["name"], "Cab Climate")
        corners = sorted((w["geometry"]["x"], w["geometry"]["y"]) for w in data["widgets"])
        self.assertEqual(corners[0], (0, 0))
        self.assertEqual(corners[1], (110, 10))
        self.assertEqual(custom.width, 110 + self.value.geometry["width"])

    def test_it_appears_in_the_palette_and_inserts_a_fresh_bound_copy(self):
        self._select(self.tile, self.value)
        self.ws.save_selection_as_custom(name="Cab Climate")
        self.assertEqual(self._palette_rows(), ["custom:cab-climate"])
        before = len(self.ws.current_page.widgets)
        depth = self.ws.undo_stack.count()
        self.ws.add_widget("custom:cab-climate", 400, 300)
        group = self.ws.current_page.widgets[-1]
        self.assertEqual(len(self.ws.current_page.widgets), before + 1)
        self.assertEqual(group.type, "Item")
        self.assertEqual((group.geometry["x"], group.geometry["y"]), (400, 300))
        self.assertEqual(sorted(c.type for c in group.children), ["ShIconTile", "ShValueTile"])
        ids = [w.id for w in self.ws.project.all_widgets()]
        self.assertEqual(len(ids), len(set(ids)), "every id stays unique")
        self.assertIn("hvac.cab_temp", self.ws.project.required_tags())
        self.assertEqual(self.ws.undo_stack.count(), depth + 1)
        self.ws.undo_stack.undo()
        self.assertEqual(len(self.ws.current_page.widgets), before)

    def test_two_copies_do_not_share_ids(self):
        self._select(self.tile)
        self.ws.save_selection_as_custom(name="Tile")
        self.ws.add_widget("custom:tile", 0, 0)
        self.ws.add_widget("custom:tile", 0, 200)
        ids = [w.id for w in self.ws.project.all_widgets()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_deleting_it_takes_it_out_of_the_palette(self):
        self._select(self.tile)
        self.ws.save_selection_as_custom(name="Tile")
        self.assertTrue(self.ws.custom_library.delete("custom:tile"))
        self.assertEqual(self._palette_rows(), [])

    def test_nothing_selected_saves_nothing(self):
        self.ws.scene.clearSelection()
        self.assertIsNone(self.ws.save_selection_as_custom(name="Empty"))
        self.assertEqual(os.listdir(self.folder.name) if os.path.isdir(self.folder.name) else [], [])

    def test_the_library_survives_a_new_workspace(self):
        self._select(self.tile, self.value)
        self.ws.save_selection_as_custom(name="Cab Climate")
        other = DesignerWorkspace()
        self.addCleanup(other.close)
        self.assertEqual([c.name for c in other.custom_library.items()], ["Cab Climate"])

    def test_a_broken_file_is_ignored(self):
        with open(os.path.join(self.folder.name, "junk.edswidget"), "w") as fh:
            fh.write("{not json")
        self.assertEqual(CustomWidgetLibrary(self.folder.name).items(), [])


if __name__ == "__main__":
    unittest.main()
