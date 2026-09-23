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
        self.window.show_section("widget", "edsui")
        self.assertEqual((self.window.scope, self.window.fmt), ("widget", "edsui"))
        self._select(gauge_id)
        gauge = self.workspace.selected_widget()
        self.assertEqual(self.window.editor.code(), widget_edsui(gauge))
        self.assertFalse(self.window.editor.isReadOnly())
        # QML is not a Code-section format any more: the panel runs the design.
        with self.assertRaises(ValueError):
            self.window.show_section("widget", "qml")
        self._select(button_id)
        self.assertIn(f'"id": "{button_id}"', self.window.editor.code())
        self.assertNotIn(f'"id": "{gauge_id}"', self.window.editor.code())
        self.workspace.scene.clearSelection(); self.app.processEvents()
        self.assertTrue(self.window.editor.code().lstrip().startswith("//"))

    def test_page_scope_shows_whole_screen(self):
        gauge_id, button_id = _ids(self.workspace)
        self.window.show_section("page", "edsui")
        code = self.window.editor.code()
        self.assertIn(f'"id": "{gauge_id}"', code)
        self.assertIn(f'"id": "{button_id}"', code)
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



# =============================================================================
# W3's own tests (below the frozen ones).
# =============================================================================
class CodeWindowMoreTests(unittest.TestCase):
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
        self.workspace.scene.item_for_id(widget_id).setSelected(True)
        self.app.processEvents()

    def test_close_hides(self):
        self.window.show()
        self.window.close()
        self.assertFalse(self.window.isVisible())

    def test_section_changed_and_combos_follow(self):
        seen = []
        self.window.sectionChanged.connect(lambda s, f: seen.append((s, f)))
        self.window.show_section("page", "edsui")
        self.assertEqual(seen, [("page", "edsui")])
        self.assertEqual(self.window._scope_box.currentText(), "Whole screen")
        with self.assertRaises(ValueError):
            self.window.show_section("nope", "edsui")

    def test_edit_survives_refresh_and_keep_stays(self):
        gauge_id, button_id = _ids(self.workspace)
        self._select(gauge_id)
        self.window.show_section("widget", "edsui")
        edited = self.window.editor.code().replace('"width": 180', '"width": 200')
        self.window.editor.set_code(edited, keep_scroll=False)
        self.window.editor.codeEdited.emit()
        self._select(button_id)                       # selection moves; the edit stays
        self.assertEqual(self.window.editor.code(), edited)
        self.assertTrue(self.window._title.text().endswith(" *"))
        self.window._confirm_discard = lambda: False  # Keep
        self.window.show_section("page", "edsui")
        self.assertEqual((self.window.scope, self.window.fmt), ("widget", "edsui"))
        self.assertEqual(self.window.editor.code(), edited)
        self.window._confirm_discard = lambda: True   # Discard
        self.window.show_section("page", "edsui")
        self.assertEqual(self.window.scope, "page")
        self.assertIn(f'"id": "{button_id}"', self.window.editor.code())

    def test_apply_page_json(self):
        self.window.show_section("page", "edsui")
        text = self.window.editor.code().replace('"name": "Main"', '"name": "Renamed"')
        self.window.editor.set_code(text, keep_scroll=False)
        self.window.editor.codeEdited.emit()
        self.assertTrue(self.window.apply())
        self.assertEqual(self.workspace.current_page.name, "Renamed")
        self.assertFalse(self.window.is_edited())

    def test_error_line_moves_cursor(self):
        gauge_id, _ = _ids(self.workspace)
        self._select(gauge_id)
        self.window.show_section("widget", "edsui")
        lines = self.window.editor.code().splitlines()
        lines[2] = lines[2].rstrip(",") + " oops,"
        self.window.editor.set_code("\n".join(lines), keep_scroll=False)
        self.window.editor.codeEdited.emit()
        self.assertFalse(self.window.apply())
        self.assertIn("line 3", self.window.status_text())
        self.assertEqual(self.window.editor.textCursor().blockNumber(), 2)

    def test_preview_messages(self):
        self.workspace.scene.clearSelection(); self.app.processEvents()
        self.window.set_preview_visible(True)
        self.assertIn("Nothing selected", self.window.preview._label.text())
        self.workspace.scene.qml_previews.enabled = False
        self.window.refresh()
        self.assertIn("previews are off", self.window.preview._label.text())
        self.workspace.scene.qml_previews.enabled = True
        self.window.show_section("page", "edsui")
        self.window.show(); QTest.qWait(600)
        pane = self.window.preview
        self.assertTrue(pane._image is not None or pane._label.text() in ("Rendering...", "This section did not render"))


# ---------------------------------------------------------------- W4 extras
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


# ---------------------------------------------------------------- the Studio tab
class StudioCodeTabTests(unittest.TestCase):
    """The Studio hosts the Code window as a section beside Designer / AI Design."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls._stylesheet, cls._font = cls.app.styleSheet(), cls.app.font()
        from PySide6.QtCore import QSettings
        cls._last_bundle = QSettings("MIL-HMI", "Deployer").value("last_bundle", "")

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls._stylesheet)
        cls.app.setFont(cls._font)
        from PySide6.QtCore import QSettings
        QSettings("MIL-HMI", "Deployer").setValue("last_bundle", cls._last_bundle)

    def test_code_is_a_tab_and_the_designer_action_selects_it(self):
        from tools.hmi_deployer.mainwindow import MainWindow
        window = MainWindow()
        self.addCleanup(lambda: (window.close(), window.deleteLater(), self.app.processEvents()))
        tabs = window._right_tabs
        names = [tabs.tabText(i) for i in range(tabs.count())]
        self.assertEqual(names[:3], ["Designer", "AI Design", "Code"])
        self.assertEqual([window.primary_nav.tabText(i) for i in range(window.primary_nav.count())], names)
        tabs.setCurrentWidget(window.designer_workspace)
        # Since the Code IDE (docs/CODE_SECTION.md) the Code tab is the
        # CodeSection; the Code window is its pinned Design tab, and the
        # Designer's action opens the section on that tab.
        section = window._code_tab
        section.tabs.setCurrentIndex(section.tabs.count() - 1)
        code = window.designer_workspace.open_code_window()
        self.assertIs(code, section.design)
        self.assertIs(tabs.currentWidget(), section)
        self.assertIs(section.tabs.currentWidget(), code)
        self.assertFalse(code.isWindow())
        # The tab follows the design like the window did.
        window.designer_workspace.add_widget("ShGauge")
        gauge_id = window.designer_workspace.current_page.widgets[-1].id
        window.designer_workspace.scene.clearSelection()
        window.designer_workspace.scene.item_for_id(gauge_id).setSelected(True)
        self.app.processEvents()
        code.show_section("widget", "edsui")
        self.assertIn(f'"id": "{gauge_id}"', code.editor.code())


if __name__ == "__main__":
    unittest.main()
