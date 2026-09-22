"""designer/ui/code_window.py -- the Code window (W3 gate), and its
integration with the workspace (W4 gate: the last class).

FROZEN: the tests below are the minimum W3/W4 must pass; add more below
them, never change these. W3 runs CodeWindowTests against the stubbed
workspace API until W4 lands; the tests here use only the frozen API.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.code import page_edsui, widget_edsui, widget_qml  # noqa: E402
from designer.model import DesignerWidget  # noqa: E402
from designer.ui.code_window import CodeWindow  # noqa: E402
from designer.ui.designer_workspace import DesignerWorkspace  # noqa: E402


def _workspace():
    workspace = DesignerWorkspace()
    workspace.add_widget("ShGauge")
    workspace.add_widget("ShButton")
    return workspace


def _ids(workspace):
    return [w.id for w in workspace.current_page.widgets]


class CodeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.workspace = _workspace()
        self.addCleanup(self.workspace.close)
        self.window = CodeWindow(self.workspace)
        self.addCleanup(self.window.close)

    def _select(self, widget_id):
        self.workspace.scene.clearSelection()
        item = self.workspace.scene.item_for_id(widget_id)
        item.setSelected(True)
        self.app.processEvents()

    def test_follows_selection_in_widget_qml_scope(self):
        gauge_id, button_id = _ids(self.workspace)
        self.window.show_section("widget", "qml")
        self.assertEqual((self.window.scope, self.window.fmt), ("widget", "qml"))
        self._select(gauge_id)
        gauge = self.workspace.selected_widget()
        self.assertEqual(self.window.editor.code(), widget_qml(self.workspace.generator, self.workspace.project, gauge))
        self.assertTrue(self.window.editor.isReadOnly())
        self._select(button_id)
        self.assertIn(f"id: {button_id}", self.window.editor.code())
        self.assertNotIn(f"id: {gauge_id}", self.window.editor.code())
        self.workspace.scene.clearSelection(); self.app.processEvents()
        self.assertTrue(self.window.editor.code().lstrip().startswith("//"))

    def test_page_scope_shows_whole_screen(self):
        gauge_id, button_id = _ids(self.workspace)
        self.window.show_section("page", "qml")
        code = self.window.editor.code()
        self.assertIn(f"id: {gauge_id}", code)
        self.assertIn(f"id: {button_id}", code)
        self.window.show_section("page", "edsui")
        self.assertEqual(self.window.editor.code(), page_edsui(self.workspace.current_page))
        self.assertFalse(self.window.editor.isReadOnly())

    def test_edit_marks_and_apply_replaces_widget(self):
        gauge_id, _ = _ids(self.workspace)
        self._select(gauge_id)
        self.window.show_section("widget", "edsui")
        self.assertFalse(self.window.is_edited())
        text = self.window.editor.code().replace('"width": 180', '"width": 321')
        self.assertNotEqual(text, self.window.editor.code(), "fixture assumes ShGauge default width 180")
        self.window.editor.set_code(text, keep_scroll=False)
        self.window.editor.codeEdited.emit()
        self.assertTrue(self.window.is_edited())
        self.assertTrue(self.window.apply())
        self.assertFalse(self.window.is_edited())
        gauge = next(w for w in self.workspace.current_page.widgets if w.id == gauge_id)
        self.assertEqual(gauge.geometry["width"], 321)
        self.assertIn("Applied", self.window.status_text())
        self.workspace.undo_stack.undo(); self.app.processEvents()
        gauge = next(w for w in self.workspace.current_page.widgets if w.id == gauge_id)
        self.assertEqual(gauge.geometry["width"], 180)
        self.assertIn('"width": 180', self.window.editor.code())    # refreshed by designChanged

    def test_apply_error_goes_to_status(self):
        gauge_id, _ = _ids(self.workspace)
        self._select(gauge_id)
        self.window.show_section("widget", "edsui")
        self.window.editor.set_code(self.window.editor.code().replace('"ShGauge"', '"ShNope"'), keep_scroll=False)
        self.window.editor.codeEdited.emit()
        self.assertFalse(self.window.apply())
        self.assertIn("ShNope", self.window.status_text())
        self.assertTrue(self.window.is_edited())

    def test_preview_toggle(self):
        gauge_id, _ = _ids(self.workspace)
        self._select(gauge_id)
        self.window.set_preview_visible(True)
        self.assertTrue(self.window.preview_visible())
        self.window.show(); QTest.qWait(300)
        self.window.set_preview_visible(False)
        self.assertFalse(self.window.preview_visible())

    def test_theme(self):
        for theme in ("light", "dark"):
            self.window.apply_theme(theme)
        self.assertEqual(self.window.windowTitle(), "Code")


class WorkspaceCodeIntegrationTests(unittest.TestCase):
    """W4: the workspace side of the contract."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.workspace = _workspace()
        self.addCleanup(self.workspace.close)

    def test_open_code_window_is_single_instance(self):
        first = self.workspace.open_code_window()
        second = self.workspace.open_code_window()
        self.assertIs(first, second)
        self.assertIsInstance(first, CodeWindow)
        self.assertTrue(first.isVisible())
        first.close()
        self.assertIs(self.workspace.open_code_window(), first)

    def test_toolbar_has_code_action(self):
        names = [a.text() for a in self.workspace.findChildren(type(self.workspace.live_action))]
        self.assertIn("Code", names)

    def test_replace_widget_is_undoable_and_emits(self):
        gauge_id, _ = _ids(self.workspace)
        changes = []
        self.workspace.designChanged.connect(lambda: changes.append(1))
        gauge = next(w for w in self.workspace.current_page.widgets if w.id == gauge_id)
        new = DesignerWidget.from_dict(gauge.to_dict())
        new.geometry["x"] = 77
        self.assertTrue(self.workspace.replace_widget(gauge_id, new))
        self.assertEqual(next(w for w in self.workspace.current_page.widgets if w.id == gauge_id).geometry["x"], 77)
        self.assertEqual([w.id for w in self.workspace.scene.selected_models()], [gauge_id])
        self.assertGreaterEqual(len(changes), 1)
        self.assertEqual(self.workspace.undo_stack.undoText(), f"Edit {gauge_id} code")
        self.workspace.undo_stack.undo()
        self.assertNotEqual(next(w for w in self.workspace.current_page.widgets if w.id == gauge_id).geometry["x"], 77)
        self.assertFalse(self.workspace.replace_widget("nope", new))

    def test_replace_page_is_undoable(self):
        page = self.workspace.current_page
        from designer.model import DesignerPage
        new = DesignerPage.from_dict(page.to_dict())
        new.name = "Renamed"
        self.assertTrue(self.workspace.replace_page(0, new))
        self.assertEqual(self.workspace.current_page.name, "Renamed")
        self.assertEqual(self.workspace.undo_stack.undoText(), "Edit page code")
        self.workspace.undo_stack.undo()
        self.assertNotEqual(self.workspace.current_page.name, "Renamed")
        self.assertFalse(self.workspace.replace_page(5, new))

    def test_designChanged_on_undo_and_page_change(self):
        changes = []
        self.workspace.designChanged.connect(lambda: changes.append(1))
        pages = []
        self.workspace.pageChanged.connect(pages.append)
        self.workspace.undo_stack.undo()
        self.assertGreaterEqual(len(changes), 1)
        self.workspace.new_page()
        self.assertGreaterEqual(len(pages), 1)


# ---------------------------------------------------------------------------
# STAND-IN, removed at integration (W4). CodeWindow.__init__ raises
# NotImplementedError until W3 lands, so the workspace gate runs against a
# minimal window with the frozen constructor and the two members the
# workspace touches (apply_theme and the "Code" title). It subclasses the
# frozen class so the gate's isinstance check holds, and skips its __init__.
# Delete everything from here to "END STAND-IN" once W3 is merged; the W4
# tests below it use only the frozen API and stay.
# ---------------------------------------------------------------------------
from PySide6.QtWidgets import QMainWindow  # noqa: E402

import designer.ui.code_window as _code_window_module  # noqa: E402


class _StandInCodeWindow(CodeWindow):
    def __init__(self, workspace, parent=None):
        QMainWindow.__init__(self, parent)
        self.workspace = workspace
        self.themes = []
        self.setWindowTitle("Code")

    def apply_theme(self, theme):
        self.themes.append(theme)


def setUpModule():
    _code_window_module.CodeWindow = _StandInCodeWindow


def tearDownModule():
    _code_window_module.CodeWindow = CodeWindow
# ---------------------------------------------------------------- END STAND-IN


class WorkspaceCodeIntegrationExtraTests(unittest.TestCase):
    """W4: what the brief asks for beyond the frozen minimum."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.workspace = _workspace()
        self.addCleanup(self.workspace.close)

    def _select(self, *ids):
        self.workspace.scene.clearSelection()
        for widget_id in ids:
            self.workspace.scene.item_for_id(widget_id).setSelected(True)
        self.app.processEvents()

    def test_selected_widget_is_the_single_selection(self):
        gauge_id, button_id = _ids(self.workspace)
        self._select()                                   # add_widget leaves the newcomer selected
        self.assertIsNone(self.workspace.selected_widget())
        self._select(gauge_id)
        self.assertEqual(self.workspace.selected_widget().id, gauge_id)
        self._select(gauge_id, button_id)
        self.assertIsNone(self.workspace.selected_widget())

    def test_code_action_icon_and_shortcut(self):
        from PySide6.QtGui import QKeySequence, QShortcut
        action = next(a for a in self.workspace.findChildren(type(self.workspace.live_action)) if a.text() == "Code")
        self.assertEqual(self.workspace._designer_icon_names[action], "terminal-2")
        keys = [s.key().toString() for s in self.workspace.findChildren(QShortcut)]
        self.assertIn(QKeySequence("Ctrl+Shift+K").toString(), keys)

    def test_theme_is_forwarded_once_the_window_exists(self):
        self.workspace.apply_theme("light")             # no window yet: nothing to forward to
        window = self.workspace.open_code_window()
        self.assertEqual(window.themes, ["light"])      # caught up on open
        self.workspace.apply_theme("dark")
        self.assertEqual(window.themes, ["light", "dark"])

    def test_replace_widget_reaches_a_nested_child(self):
        self.workspace.add_widget("ShCard")
        card_id = _ids(self.workspace)[-1]
        self.workspace.add_widget("Text", parent_id=card_id)
        card = next(w for w in self.workspace.current_page.widgets if w.id == card_id)
        child = card.children[0]
        new = DesignerWidget.from_dict(child.to_dict())
        new.properties["text"] = "nested edit"
        self.assertTrue(self.workspace.replace_widget(child.id, new))
        self.assertEqual(card.children[0].properties["text"], "nested edit")
        self.assertIsNot(card.children[0], new, "the command must own its own copy")
        self.workspace.undo_stack.undo()
        self.assertIs(card.children[0], child)
        self.workspace.undo_stack.redo()
        self.assertEqual(card.children[0].properties["text"], "nested edit")
        self.assertEqual([w.id for w in self.workspace.scene.selected_models()], [child.id])

    def test_replace_widget_can_rename(self):
        gauge_id, _ = _ids(self.workspace)
        gauge = next(w for w in self.workspace.current_page.widgets if w.id == gauge_id)
        new = DesignerWidget.from_dict(gauge.to_dict())
        new.id = "renamedGauge"
        self.assertTrue(self.workspace.replace_widget(gauge_id, new))
        self.assertEqual([w.id for w in self.workspace.scene.selected_models()], ["renamedGauge"])
        self.workspace.undo_stack.undo()
        self.assertEqual([w.id for w in self.workspace.scene.selected_models()], [gauge_id])

    def test_designChanged_on_loads_and_page_operations(self):
        import tempfile
        # A fresh workspace: its undo stack is empty, so clear() on load is
        # silent and the load has to speak for itself.
        workspace = DesignerWorkspace(); self.addCleanup(workspace.close)
        changes = []
        workspace.designChanged.connect(lambda: changes.append(1))
        workspace.set_bundle(tempfile.mkdtemp(), {"name": "qc", "version": "1.0.0"})
        self.assertEqual(len(changes), 1, "a bundle load with an empty undo stack")
        workspace.new_page(); workspace.duplicate_page()
        workspace.change_page(0); workspace.delete_page()
        self.assertEqual(len(changes), 5)
        workspace.new_ui()
        self.assertEqual(len(changes), 6)

    def test_replace_page_off_screen_renames_the_combo_entry(self):
        from designer.model import DesignerPage
        self.workspace.new_page()            # now on page 1
        new = DesignerPage.from_dict(self.workspace.project.pages[0].to_dict())
        new.name = "Cover"
        self.assertTrue(self.workspace.replace_page(0, new))
        self.assertEqual(self.workspace.current_page_index, 1)
        self.assertEqual(self.workspace.pages.itemText(0), "Cover")
        self.workspace.undo_stack.undo()
        self.assertNotEqual(self.workspace.pages.itemText(0), "Cover")


if __name__ == "__main__":
    unittest.main()
