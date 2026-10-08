import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QFileDialog, QFormLayout, QPushButton
from designer.ui import designer_workspace
from designer.ui import DesignerWorkspace


def _write_png(path):
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(0xFF3B82F6)
    image.save(path, "PNG")


class DesignerAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _click_browse(self, workspace, property_name):
        """Drive the inspector the way the user does, through the Browse button."""
        form = workspace.properties.form
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.LabelRole)
            if label and label.widget() and label.widget().text() == property_name:
                editor = form.itemAt(row, QFormLayout.FieldRole).widget()
                for button in editor.findChildren(QPushButton):
                    if button.text() == "Browse":
                        button.click()
                        return
        self.fail(f"no Browse button for {property_name!r}")

    def test_browse_copies_image_into_bundle_assets(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "bundle")
            os.makedirs(bundle)
            picture = os.path.join(root, "logo.png")
            _write_png(picture)

            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle)
            workspace.add_widget("Image")
            model = workspace.current_page.widgets[0]
            workspace.scene.item_for_id(model.id).setSelected(True)

            original = QFileDialog.getOpenFileName
            designer_workspace.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (picture, ""))
            try:
                self._click_browse(workspace, "source")
            finally:
                designer_workspace.QFileDialog.getOpenFileName = original

            self.assertEqual(model.properties["source"], "assets/logo.png")
            self.assertTrue(os.path.isfile(os.path.join(bundle, "assets", "logo.png")))
            self.assertEqual(workspace.project.validate(workspace.registry, bundle), [])
            # And it has to actually show up on the canvas, not just in the model.
            self.assertEqual(self._canvas_pixel(workspace, model), 0xFF3B82F6)

    def _canvas_pixel(self, workspace, model):
        """The color the canvas paints at the middle of a widget."""
        item = workspace.scene.item_for_id(model.id)
        frame = QImage(40, 40, QImage.Format_ARGB32)
        frame.fill(0)
        painter = QPainter(frame)
        workspace.scene.render(painter, QRectF(frame.rect()), item.sceneBoundingRect())
        painter.end()
        return frame.pixel(20, 20)

    def test_save_as_gives_the_canvas_an_asset_root(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            self.assertEqual(workspace.scene.project_dir, "")
            target = os.path.join(root, "ui.edsui")
            original = QFileDialog.getSaveFileName
            designer_workspace.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (target, ""))
            try:
                self.assertTrue(workspace.save())
            finally:
                designer_workspace.QFileDialog.getSaveFileName = original
            self.assertEqual(workspace.scene.project_dir, os.path.dirname(target))


class DesignerContextMenuTests(unittest.TestCase):
    """Right-click and double-click are the two ways an author reaches an image."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _bundle_with_image_widget(self, root):
        bundle = os.path.join(root, "bundle")
        os.makedirs(bundle)
        picture = os.path.join(root, "logo.png")
        _write_png(picture)
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(bundle)
        workspace.add_widget("Image")
        model = workspace.current_page.widgets[0]
        workspace.scene.item_for_id(model.id).setSelected(True)
        return workspace, model, bundle, picture

    def _with_picked_file(self, picture, call):
        original = QFileDialog.getOpenFileName
        designer_workspace.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (picture, ""))
        try:
            call()
        finally:
            designer_workspace.QFileDialog.getOpenFileName = original

    def test_right_click_offers_set_image_then_change_and_clear(self):
        with tempfile.TemporaryDirectory() as root:
            workspace, model, bundle, picture = self._bundle_with_image_widget(root)
            actions = workspace.context_menu(model.id).actions()
            texts = [action.text() for action in actions]
            self.assertIn("Set Image...", texts)
            self.assertNotIn("Clear Image", texts)
            for entry in ("Cut", "Copy", "Duplicate", "Delete", "Bring to Front", "Send to Back"):
                self.assertIn(entry, texts)

            self._with_picked_file(picture, actions[texts.index("Set Image...")].trigger)
            self.assertEqual(model.properties["source"], "assets/logo.png")

            texts = [action.text() for action in workspace.context_menu(model.id).actions()]
            self.assertIn("Change Image...", texts)
            self.assertIn("Clear Image", texts)

    def test_double_clicking_an_image_widget_opens_the_picker(self):
        with tempfile.TemporaryDirectory() as root:
            workspace, model, bundle, picture = self._bundle_with_image_widget(root)
            item = workspace.scene.item_for_id(model.id)
            workspace.scene.clearSelection()

            class _Event:
                def accept(self):
                    self.accepted = True

            self._with_picked_file(picture, lambda: item.mouseDoubleClickEvent(_Event()))
            self.assertEqual(model.properties["source"], "assets/logo.png")

    def test_empty_canvas_menu_only_offers_page_actions(self):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        texts = [action.text() for action in workspace.context_menu("").actions()]
        self.assertEqual(texts, ["Paste", "Select All"])


class PromptImagesTests(unittest.TestCase):
    """A canvas request that names an image file: the file goes into assets."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_named_logo_is_copied_in_trimmed_and_the_request_names_the_asset(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "bundle")
            os.makedirs(bundle)
            # A 40x20 mark padded onto a transparent 100x100 canvas, as logo
            # exports usually are.
            padded = QImage(100, 100, QImage.Format_ARGB32)
            padded.fill(0)
            painter = QPainter(padded)
            painter.fillRect(QRectF(30, 40, 40, 20), 0xFF1D4ED8)
            painter.end()
            picture = os.path.join(root, "Acme Logo.png")
            padded.save(picture, "PNG")

            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle)
            prompt, imported = workspace.import_prompt_images(
                f'Add the logo "{picture}" at the right end of the header')

            self.assertEqual(imported, ["assets/acme-logo.png"])
            self.assertEqual(prompt, 'Add the logo assets/acme-logo.png at the right end of the header')
            copied = QImage(os.path.join(bundle, "assets", "acme-logo.png"))
            self.assertEqual((copied.width(), copied.height()), (40, 20))

    def test_a_file_named_from_downloads_is_found_without_a_full_path(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as root:
            home = os.path.join(root, "home")
            os.makedirs(os.path.join(home, "Downloads"))
            _write_png(os.path.join(home, "Downloads", "Brand.png"))
            bundle = os.path.join(root, "bundle")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle)
            with mock.patch.dict(os.environ, {"USERPROFILE": home, "HOME": home}):
                prompt, imported = workspace.import_prompt_images(
                    "Add our logo from Downloads/Brand.png to the header; keep assets/old.png")
            self.assertEqual(imported, ["assets/brand.png"])
            self.assertEqual(prompt, "Add our logo from assets/brand.png to the header; keep assets/old.png")

    def test_a_webp_logo_arrives_as_a_png_the_panel_can_draw(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "bundle")
            os.makedirs(bundle)
            picture = QImage(60, 30, QImage.Format_RGB32)
            picture.fill(0xFF2E7D32)
            source = os.path.join(root, "Namma_metro.svg.webp")
            self.assertTrue(picture.save(source, "WEBP"))
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle)
            prompt, imported = workspace.import_prompt_images(f"Add {source} to the header")
            self.assertEqual(imported, ["assets/namma_metro.png"])
            copied = QImage(os.path.join(bundle, "assets", "namma_metro.png"))
            self.assertEqual((copied.width(), copied.height()), (60, 30))
            with open(os.path.join(bundle, "assets", "namma_metro.png"), "rb") as fh:
                self.assertEqual(fh.read(4), b"\x89PNG")

    def test_a_path_that_is_not_a_file_is_left_alone(self):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        prompt, imported = workspace.import_prompt_images(r"use C:\nowhere\missing.png please")
        self.assertEqual(imported, [])
        self.assertEqual(prompt, r"use C:\nowhere\missing.png please")


if __name__ == "__main__":
    unittest.main()
