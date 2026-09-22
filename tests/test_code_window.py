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


# =============================================================================
# STAND-IN, removed at integration (W3). Minimal working versions of the
# pieces W1 (designer.code), W2 (CodeEditor) and W4 (workspace API) own, so
# CodeWindowTests can run in W3's worktree where those still raise
# NotImplementedError. Each is installed only when the real one raises.
# =============================================================================
import json  # noqa: E402
import re  # noqa: E402

import shiboken6  # noqa: E402

from PySide6.QtCore import Signal as _Signal  # noqa: E402
from PySide6.QtGui import QTextCursor as _QTextCursor  # noqa: E402
from PySide6.QtWidgets import QPlainTextEdit as _QPlainTextEdit  # noqa: E402

import designer.code as _design_code  # noqa: E402
import designer.code.code_model as _code_model  # noqa: E402
import designer.ui.code_editor as _code_editor  # noqa: E402
from designer.commands import CallbackCommand as _CallbackCommand  # noqa: E402
from designer.model import DesignerPage as _DesignerPage  # noqa: E402

_ID_RE = re.compile(r"^[a-z_][A-Za-z0-9_]*$")


def _si_widget_qml(generator, project, widget):
    lines = generator._widget(widget, 0)
    while lines and lines[0] == "":
        lines = lines[1:]
    return "\n".join(lines) + "\n"


def _si_page_qml(generator, project, page):
    return generator._page(project, page)


def _si_widget_edsui(widget):
    return json.dumps(widget.to_dict(), indent=2, ensure_ascii=False) + "\n"


def _si_page_edsui(page):
    data = {"id": page.id, "name": page.name, "widgets": [w.to_dict() for w in page.widgets]}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _si_load(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _code_model.CodeError(f"line {exc.lineno}: {exc.msg}") from None
    if not isinstance(data, dict):
        raise _code_model.CodeError("expected a JSON object")
    return data


def _si_check(widget, registry, project, replacing):
    seen = set()
    taken = {w.id for w in project.all_widgets()} if project else set()
    if replacing:
        for w in project.all_widgets():
            if w.id == replacing:
                taken -= {c.id for c in w.walk()}
    for node in widget.walk():
        if registry.get(node.type) is None:
            raise _code_model.CodeError(f'unknown widget type "{node.type}"')
        if not _ID_RE.match(node.id):
            raise _code_model.CodeError(f'"{node.id}" is not a QML identifier')
        if node.id in seen or node.id in taken:
            raise _code_model.CodeError(f'duplicate id "{node.id}"')
        seen.add(node.id)


def _si_parse_widget_edsui(text, registry, project=None, replacing=None):
    data = _si_load(text)
    if not isinstance(data.get("type"), str) or not isinstance(data.get("id"), str):
        raise _code_model.CodeError('a widget needs a string "type" and "id"')
    widget = DesignerWidget.from_dict(data)
    _si_check(widget, registry, project, replacing)
    return widget


def _si_parse_page_edsui(text, registry, project=None, replacing=None):
    data = _si_load(text)
    page = _DesignerPage.from_dict(data)
    seen = set()
    for widget in page.widgets:
        _si_check(widget, registry, None, None)
        for node in widget.walk():
            if node.id in seen:
                raise _code_model.CodeError(f'duplicate id "{node.id}"')
            seen.add(node.id)
    return page


def _si_section_for(generator, registry, project, page, widget, scope, fmt):
    if scope not in _code_model.SCOPES or fmt not in _code_model.FORMATS:
        raise ValueError(f"unknown section {scope}/{fmt}")
    language = "qml" if fmt == "qml" else "json"
    if scope == "widget":
        if widget is None:
            return _code_model.CodeSection(scope, fmt, "Nothing selected", "// nothing selected\n", False, language)
        text = _si_widget_qml(generator, project, widget) if fmt == "qml" else _si_widget_edsui(widget)
        title = f"{widget.id} ({widget.type}) -- " + ("generated QML" if fmt == "qml" else "design JSON")
    else:
        text = _si_page_qml(generator, project, page) if fmt == "qml" else _si_page_edsui(page)
        title = f'Page "{page.name}" -- ' + ("generated QML" if fmt == "qml" else "design JSON")
    return _code_model.CodeSection(scope, fmt, title, text, fmt == "edsui", language)


class _StandInCodeEditor(_QPlainTextEdit):
    codeEdited = _Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setting = False
        self.textChanged.connect(lambda: None if self._setting else self.codeEdited.emit())

    def set_language(self, language): self._language = language
    def set_code(self, text, keep_scroll=True):
        self._setting = True
        try: self.setPlainText(text)
        finally: self._setting = False
    def code(self): return self.toPlainText()
    def set_read_only_view(self, read_only): self.setReadOnly(read_only)
    def apply_theme(self, theme): self._theme = theme
    def go_to_line(self, line):
        cursor = _QTextCursor(self.document().findBlockByNumber(max(0, line - 1)))
        self.setTextCursor(cursor)
    def show_find(self): pass
    def find_next(self, query, backwards=False): return self.find(query)


def _si_selected_widget(self):
    models = self.scene.selected_models()
    return models[0] if len(models) == 1 else None


def _si_replace_widget(self, widget_id, new_widget):
    def locate(widgets):
        for index, widget in enumerate(widgets):
            if widget.id == widget_id: return widgets, index
            found = locate(widget.children)
            if found: return found
        return None
    found = locate(self.current_page.widgets)
    if not found: return False
    siblings, index = found
    old = siblings[index]
    def swap(model):
        siblings[index] = model; self._load_page(select=[model.id])
    self.undo_stack.push(_CallbackCommand(f"Edit {widget_id} code", lambda: swap(new_widget), lambda: swap(old)))
    return True


def _si_replace_page(self, index, new_page):
    if not 0 <= index < len(self.project.pages): return False
    old = self.project.pages[index]
    def swap(page):
        self.project.pages[index] = page
        if index == self.current_page_index: self._load_page()
    self.undo_stack.push(_CallbackCommand("Edit page code", lambda: swap(new_page), lambda: swap(old)))
    return True


def _si_open_code_window(self):
    if getattr(self, "_code_window", None) is None:
        self._code_window = CodeWindow(self)
    self._code_window.show(); self._code_window.raise_()
    return self._code_window


def _raises_not_implemented(call):
    try:
        call()
    except NotImplementedError:
        return True
    except Exception:  # noqa: BLE001 -- anything else means a real implementation is in
        return False
    return False


def setUpModule():
    app = QApplication.instance() or QApplication(sys.argv)
    probe = DesignerWidget(type="Item", id="probe", geometry={"x": 0, "y": 0, "width": 10, "height": 10})
    if _raises_not_implemented(lambda: _design_code.widget_edsui(probe)):
        for name, stand_in in (("widget_qml", _si_widget_qml), ("page_qml", _si_page_qml),
                               ("widget_edsui", _si_widget_edsui), ("page_edsui", _si_page_edsui),
                               ("parse_widget_edsui", _si_parse_widget_edsui),
                               ("parse_page_edsui", _si_parse_page_edsui), ("section_for", _si_section_for)):
            setattr(_code_model, name, stand_in)
            setattr(_design_code, name, stand_in)
            globals()[name] = stand_in       # the frozen tests bound these names at import
    if _raises_not_implemented(lambda: _code_editor.CodeEditor()):
        _code_editor.CodeEditor = _StandInCodeEditor
    throwaway = DesignerWorkspace()
    if _raises_not_implemented(throwaway.selected_widget):
        DesignerWorkspace.selected_widget = _si_selected_widget
        DesignerWorkspace.replace_widget = _si_replace_widget
        DesignerWorkspace.replace_page = _si_replace_page
        DesignerWorkspace.open_code_window = _si_open_code_window
        # The contract emits designChanged on every undo-stack index change
        # and pageChanged on a page switch; the stand-in wires both at
        # construction since it cannot reach into the frozen workspace body.
        original_init = DesignerWorkspace.__init__
        def design_changed(self, _index):
            # The stack's last index change arrives while the workspace is
            # being torn down; a dead QObject cannot emit.
            if shiboken6.isValid(self): self.designChanged.emit()
        DesignerWorkspace._si_design_changed = design_changed
        def init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.undo_stack.indexChanged.connect(self._si_design_changed)
            original_load = self._load_page
            def load_page(select=None):
                original_load(select)
                self.pageChanged.emit(self.current_page_index)
            self._load_page = load_page
        DesignerWorkspace.__init__ = init
    throwaway.close()
    app.processEvents()


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
        self.assertEqual(self.window._fmt_box.currentText(), "Design JSON")
        self.window._fmt_box.setCurrentIndex(0)
        self.assertEqual((self.window.scope, self.window.fmt), ("page", "qml"))
        with self.assertRaises(ValueError):
            self.window.show_section("nope", "qml")

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
        self.window.show_section("widget", "qml")
        self.assertEqual((self.window.scope, self.window.fmt), ("widget", "edsui"))
        self.assertEqual(self.window.editor.code(), edited)
        self.window._confirm_discard = lambda: True   # Discard
        self.window.show_section("widget", "qml")
        self.assertEqual(self.window.fmt, "qml")
        self.assertIn(f"id: {button_id}", self.window.editor.code())

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
        self.window.show_section("page", "qml")
        self.window.show(); QTest.qWait(600)
        pane = self.window.preview
        self.assertTrue(pane._image is not None or pane._label.text() in ("Rendering...", "This section did not render"))


if __name__ == "__main__":
    unittest.main()
