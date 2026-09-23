"""designer/ide/project_files.py and widget_picker.py -- W1's gate.

FROZEN: the tests below are the minimum W1 must pass; add more in a class
below them, never change these.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide import project_files as pf  # noqa: E402
from designer.ide.project_files import ProjectTree  # noqa: E402
from designer.ide.widget_picker import WidgetPicker  # noqa: E402
from designer.ui.designer_workspace import DesignerWorkspace  # noqa: E402


def _make_project(root):
    """root/
         assets/logo.png (binary)
         src/main.c  src/util.h
         .git/HEAD   __pycache__/x.pyc
         project.edsui  README.md  Zeta.txt  alpha.py
    """
    for d in ("assets", "src", ".git", "__pycache__"):
        os.makedirs(os.path.join(root, d))
    files = {
        "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        "src/main.c": b"int main(void) { return 0; }\n",
        "src/util.h": b"#pragma once\n",
        ".git/HEAD": b"ref: refs/heads/main\n",
        "__pycache__/x.pyc": b"\x00\x01",
        "project.edsui": b'{"pages": []}\n',
        "README.md": b"# demo\n",
        "Zeta.txt": b"z\n",
        "alpha.py": b"print('a')\n",
    }
    for rel, data in files.items():
        with open(os.path.join(root, rel), "wb") as f:
            f.write(data)


class FileHelperTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ide-files-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write(self, name, data: bytes):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_language_for(self):
        cases = {"a.c": "c", "B.H": "c", "x.cpp": "c", "m.py": "python", "v.qml": "qml",
                 "d.json": "json", "project.edsui": "json", "notes.md": "plain", "Makefile": "plain"}
        for name, lang in cases.items():
            self.assertEqual(pf.language_for(os.path.join(self.dir, name)), lang, name)

    def test_read_utf8_and_newlines(self):
        path = self._write("a.c", "int x; // é\r\nint y;\r\n".encode("utf-8"))
        tf = pf.read_text(path)
        self.assertEqual(tf.text, "int x; // é\nint y;\n")
        self.assertEqual(tf.encoding, "utf-8")
        self.assertEqual(tf.newline, "\r\n")

    def test_read_bom_and_latin1(self):
        tf = pf.read_text(self._write("bom.txt", b"\xef\xbb\xbfhello\n"))
        self.assertEqual((tf.text, tf.encoding, tf.newline), ("hello\n", "utf-8-sig", "\n"))
        tf = pf.read_text(self._write("l1.txt", b"caf\xe9\n"))
        self.assertEqual((tf.text, tf.encoding), ("café\n", "latin-1"))

    def test_read_refuses_binary_large_missing(self):
        with self.assertRaises(pf.FileReadError):
            pf.read_text(self._write("b.bin", b"abc\x00def"))
        with self.assertRaises(pf.FileReadError):
            pf.read_text(self._write("big.txt", b"a" * (pf.MAX_TEXT_BYTES + 1)))
        with self.assertRaises(pf.FileReadError):
            pf.read_text(os.path.join(self.dir, "nope.txt"))
        with self.assertRaises(pf.FileReadError):
            pf.read_text(self.dir)
        self.assertTrue(pf.is_binary(os.path.join(self.dir, "b.bin")))
        self.assertFalse(pf.is_binary(os.path.join(self.dir, "big.txt")))

    def test_write_round_trip_keeps_encoding_and_newline(self):
        path = self._write("w.txt", b"\xef\xbb\xbfone\r\ntwo\r\n")
        tf = pf.read_text(path)
        pf.write_text(path, tf.text + "three\n", tf.encoding, tf.newline)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"\xef\xbb\xbfone\r\ntwo\r\nthree\r\n")
        self.assertEqual(sorted(os.listdir(self.dir)), ["w.txt"], "no temporary file left behind")

    def test_write_failure_leaves_original(self):
        path = self._write("keep.txt", b"original\n")
        with self.assertRaises((LookupError, OSError)):
            pf.write_text(path, "new\n", encoding="no-such-codec")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"original\n")
        self.assertEqual(sorted(os.listdir(self.dir)), ["keep.txt"])

    def test_is_inside_and_relative(self):
        sub = os.path.join(self.dir, "src", "main.c")
        self.assertTrue(pf.is_inside(self.dir, sub))
        self.assertTrue(pf.is_inside(self.dir, self.dir))
        self.assertFalse(pf.is_inside(self.dir, os.path.join(self.dir, "..", "other")))
        self.assertFalse(pf.is_inside(self.dir, self.dir + "-sibling"))
        self.assertEqual(pf.relative_path(self.dir, sub), "src/main.c")
        self.assertEqual(pf.relative_path(self.dir, self.dir), ".")

    def test_validate_name(self):
        self.assertEqual(pf.validate_name("  main.c "), "main.c")
        for bad in ("", "  ", ".", "..", "a/b", "a\\b", "c:x", "a*b", "a?b", "a|b", "a\x01"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                pf.validate_name(bad)


class ProjectTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ide-tree-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        _make_project(self.dir)
        self.tree = ProjectTree()
        self.addCleanup(self.tree.deleteLater)
        self.roots = []
        self.tree.rootChanged.connect(self.roots.append)
        self.tree.set_root(self.dir)

    def _p(self, rel):
        return os.path.join(self.dir, *rel.split("/"))

    def test_top_level_order_and_ignored(self):
        names = [os.path.basename(p) for p in self.tree.visible_paths()]
        self.assertEqual(names, ["assets", "src", "alpha.py", "project.edsui", "README.md", "Zeta.txt"])
        self.assertEqual(self.roots, [self.dir])
        self.assertEqual(self.tree.root(), self.dir)

    def test_expand_and_reveal(self):
        self.assertNotIn(self._p("src/main.c"), self.tree.visible_paths())
        self.tree.reveal(self._p("src/main.c"))
        visible = self.tree.visible_paths()
        self.assertIn(self._p("src/main.c"), visible)
        self.assertEqual(visible.index(self._p("src/main.c")), visible.index(self._p("src")) + 1)
        self.assertEqual(self.tree.selected_path(), self._p("src/main.c"))

    def test_activate_file_emits(self):
        got = []
        self.tree.fileActivated.connect(got.append)
        self.tree.reveal(self._p("alpha.py"))
        view = self.tree.view
        view.setFocus()
        QTest.keyClick(view, Qt.Key_Return)
        self.assertEqual(got, [self._p("alpha.py")])

    def test_new_rename_delete(self):
        new = self.tree.new_file(self._p("src"), "extra.c")
        self.assertTrue(os.path.isfile(new))
        self.assertIn(new, self.tree.visible_paths())
        with self.assertRaises(FileExistsError):
            self.tree.new_file(self._p("src"), "extra.c")
        with self.assertRaises(ValueError):
            self.tree.new_file(self._p("src"), "../escape.c")
        with self.assertRaises(ValueError):
            self.tree.new_file(os.path.dirname(self.dir), "outside.c")
        folder = self.tree.new_folder(self.dir, "lib")
        self.assertTrue(os.path.isdir(folder))
        renamed = []
        self.tree.fileRenamed.connect(lambda a, b: renamed.append((a, b)))
        moved = self.tree.rename(new, "more.c")
        self.assertEqual(renamed, [(new, moved)])
        self.assertTrue(os.path.isfile(moved) and not os.path.exists(new))
        deleted = []
        self.tree.fileDeleted.connect(deleted.append)
        self.tree.delete(self._p("src"))
        self.assertFalse(os.path.exists(self._p("src")))
        self.assertEqual(deleted, [self._p("src")])
        self.assertNotIn(self._p("src"), self.tree.visible_paths())
        with self.assertRaises(ValueError):
            self.tree.delete(self.dir)

    def test_refresh_sees_external_changes_and_keeps_expansion(self):
        self.tree.expand(self._p("src"))
        with open(self._p("src/late.c"), "w") as f:
            f.write("\n")
        self.tree.refresh()
        visible = self.tree.visible_paths()
        self.assertIn(self._p("src/late.c"), visible)
        self.assertIn(self._p("src/main.c"), visible)

    def test_watcher_refreshes_on_its_own(self):
        with open(self._p("new_top.txt"), "w") as f:
            f.write("x")
        deadline = 3000
        while deadline > 0 and self._p("new_top.txt") not in self.tree.visible_paths():
            QTest.qWait(100)
            deadline -= 100
        self.assertIn(self._p("new_top.txt"), self.tree.visible_paths())

    def test_filter(self):
        self.tree.set_filter("MAIN")
        self.assertEqual(self.tree.visible_paths(), [self._p("src"), self._p("src/main.c")])
        self.tree.set_filter("")
        self.assertNotIn(self._p("src/main.c"), self.tree.visible_paths())

    def test_empty_root(self):
        self.tree.set_root("")
        self.assertEqual(self.tree.root(), "")
        self.assertEqual(self.tree.visible_paths(), [])
        self.assertFalse(self.tree.empty_label.isHidden())
        self.assertEqual(self.roots[-1], "")

    def test_themes(self):
        self.tree.apply_theme("light")
        self.tree.apply_theme("dark")


class _FakeRenderer:
    """Stands in for the workspace's preview renderer: nothing is cached until
    `land` is called, as with the real one."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class _Bus(QObject):
            ready = Signal(str)
        self._bus = _Bus()
        self.ready = self._bus.ready
        self.cache = {}
        self.requests = []

    def image_for(self, widget, width, height, theme, scale=1.0):
        self.requests.append(widget.id)
        return self.cache.get(widget.id)

    def land(self, widget_id):
        image = QImage(40, 20, QImage.Format_ARGB32)
        image.fill(Qt.red)
        self.cache[widget_id] = image
        self.ready.emit(widget_id)


class WidgetPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.ws.add_widget("ShGauge")
        self.ws.add_widget("ShButton")
        self.renderer = _FakeRenderer()
        self.ws.scene.qml_previews = self.renderer
        self.picker = WidgetPicker(self.ws)
        self.addCleanup(self.picker.deleteLater)

    def _ids(self):
        return [w.id for w in self.ws.current_page.widgets]

    def test_lists_page_widgets(self):
        self.assertEqual(self.picker.widget_ids(), self._ids())
        self.assertEqual(self.picker.list.count(), 2)
        self.assertEqual(self.picker.list.item(0).data(Qt.UserRole), self._ids()[0])

    def test_pick_selects_in_designer(self):
        picked = []
        self.picker.widgetPicked.connect(picked.append)
        target = self._ids()[1]
        self.picker.pick(target)
        self.assertEqual(self.ws.selected_widget().id, target)
        self.assertEqual(picked, [target])
        self.assertEqual(self.picker.highlighted_id(), target)

    def test_click_row_picks(self):
        target = self._ids()[0]
        rect = self.picker.list.visualItemRect(self.picker.list.item(0))
        QTest.mouseClick(self.picker.list.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(self.ws.selected_widget().id, target)

    def test_follows_canvas_selection(self):
        target = self._ids()[1]
        self.ws.select_widget(target)
        self.assertEqual(self.picker.highlighted_id(), target)

    def test_rebuilds_on_design_change(self):
        self.ws.add_widget("ShSwitch")
        QTest.qWait(10)
        self.assertEqual(self.picker.widget_ids(), self._ids())
        self.assertEqual(len(self.picker.widget_ids()), 3)

    def test_thumbnails_fill_in_when_ready(self):
        target = self._ids()[0]
        self.assertIsNone(self.picker.thumbnail(target))
        self.assertIn(target, self.renderer.requests)
        self.renderer.land(target)
        QTest.qWait(10)
        self.assertIsNotNone(self.picker.thumbnail(target))

    def test_no_renderer(self):
        self.ws.scene.qml_previews = None
        self.picker.rebuild()
        self.assertEqual(self.picker.widget_ids(), self._ids())
        self.assertIsNone(self.picker.thumbnail(self._ids()[0]))

    def test_filter(self):
        gauge = self._ids()[0]
        self.picker.set_filter("gauge")
        self.assertEqual(self.picker.widget_ids(), [gauge])
        self.picker.set_filter("")
        self.assertEqual(len(self.picker.widget_ids()), 2)

    def test_themes(self):
        self.picker.apply_theme("light")
        self.picker.apply_theme("dark")


class W1QualityTests(unittest.TestCase):
    """W1's own checks beyond the frozen gate: path safety, atomic saves,
    the watcher, the filter, and no QWidget method shadowed."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ide-w1qc-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        _make_project(self.dir)
        self.tree = ProjectTree()
        self.addCleanup(self.tree.deleteLater)
        self.tree.set_root(self.dir)

    def _p(self, rel):
        return os.path.join(self.dir, *rel.split("/"))

    def _outside(self):
        other = os.path.realpath(tempfile.mkdtemp(prefix="ide-w1qc-out-"))
        self.addCleanup(shutil.rmtree, other, True)
        with open(os.path.join(other, "keep.txt"), "w") as f:
            f.write("keep")
        return other

    def _wait_until(self, condition, ms=3000):
        while ms > 0 and not condition():
            QTest.qWait(50)
            ms -= 50
        return condition()

    # ------------------------------------------------------------ path safety

    def test_names_and_outside_paths_refused(self):
        outside = self._outside()
        for bad in ("a/b", "..", "x:y", " "):
            with self.assertRaises(ValueError):
                self.tree.new_folder(self.dir, bad)
            with self.assertRaises(ValueError):
                self.tree.rename(self._p("alpha.py"), bad)
        with self.assertRaises(ValueError):
            self.tree.new_folder(outside, "x")
        with self.assertRaises(ValueError):
            self.tree.new_file(os.path.join(self.dir, "..", os.path.basename(outside)), "x.c")
        with self.assertRaises(ValueError):
            self.tree.rename(os.path.join(outside, "keep.txt"), "moved.txt")
        with self.assertRaises(ValueError):
            self.tree.delete(os.path.join(outside, "keep.txt"))
        with self.assertRaises(ValueError):
            self.tree.delete(os.path.join(self.dir, "src", ".."))
        with self.assertRaises(FileExistsError):
            self.tree.rename(self._p("alpha.py"), "README.md")
        self.assertEqual(sorted(os.listdir(outside)), ["keep.txt"])
        self.assertTrue(os.path.isfile(self._p("alpha.py")))

    def test_symlinked_folder_cannot_lead_outside(self):
        outside = self._outside()
        link = self._p("linked")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted here")
        self.tree.refresh()
        with self.assertRaises(ValueError):
            self.tree.new_file(link, "escape.c")
        with self.assertRaises(ValueError):
            self.tree.delete(os.path.join(link, "keep.txt"))
        self.tree.delete(link)  # the link goes, never its target
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.isfile(os.path.join(outside, "keep.txt")))

    # ------------------------------------------------------------ files

    def test_write_text_failures_leave_nothing(self):
        path = self._p("Zeta.txt")
        with self.assertRaises(OSError):  # the contract says OSError, not UnicodeEncodeError
            pf.write_text(path, "€\n", encoding="latin-1")
        with self.assertRaises(OSError):
            pf.write_text(self._p("missing/new.txt"), "x\n")
        real_replace = os.replace

        def failing_replace(src, dst):
            raise PermissionError("locked")
        os.replace = failing_replace
        try:
            with self.assertRaises(OSError):
                pf.write_text(path, "changed\n")
        finally:
            os.replace = real_replace
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"z\n")
        files = sorted(n for n in os.listdir(self.dir) if not os.path.isdir(self._p(n)))
        self.assertEqual(files, ["README.md", "Zeta.txt", "alpha.py", "project.edsui"])

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions")
    def test_write_text_keeps_permissions(self):
        path = self._p("alpha.py")
        os.chmod(path, 0o755)
        pf.write_text(path, "print('b')\n")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o755)

    def test_newline_is_the_first_line_ending(self):
        path = self._p("mixed.txt")
        with open(path, "wb") as f:
            f.write(b"one\ntwo\r\n")
        self.assertEqual(pf.read_text(path).newline, "\n")
        pf.write_text(path, "a\nb\n", "utf-8", "\r\n")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"a\r\nb\r\n")

    # ------------------------------------------------------------ the tree

    def test_enter_on_folder_toggles_without_activating(self):
        got = []
        self.tree.fileActivated.connect(got.append)
        self.tree.reveal(self._p("src"))
        self.tree.view.setFocus()
        QTest.keyClick(self.tree.view, Qt.Key_Return)
        self.assertIn(self._p("src/main.c"), self.tree.visible_paths())
        QTest.keyClick(self.tree.view, Qt.Key_Return)
        self.assertNotIn(self._p("src/main.c"), self.tree.visible_paths())
        self.assertEqual(got, [])

    def test_rename_folder_keeps_its_expansion(self):
        self.tree.expand(self._p("src"))
        moved = self.tree.rename(self._p("src"), "code")
        self.assertIn(os.path.join(moved, "main.c"), self.tree.visible_paths())

    def test_refresh_keeps_selection(self):
        self.tree.reveal(self._p("src/util.h"))
        with open(self._p("src/aaa.c"), "w") as f:
            f.write("\n")
        self.tree.refresh()
        self.assertEqual(self.tree.selected_path(), self._p("src/util.h"))
        self.assertIn(self._p("src/aaa.c"), self.tree.visible_paths())

    def test_watcher_debounces_and_keeps_state(self):
        self.tree.reveal(self._p("src/main.c"))
        calls = []
        real_refresh = self.tree.refresh

        def counting_refresh():
            calls.append(1)
            real_refresh()
        self.tree.refresh = counting_refresh
        for i in range(20):
            with open(self._p(f"src/burst{i}.c"), "w") as f:
                f.write("\n")
        self.assertTrue(self._wait_until(lambda: self._p("src/burst19.c") in self.tree.visible_paths()))
        QTest.qWait(600)
        settled = len(calls)
        self.assertLessEqual(settled, 3, "a burst of writes coalesces into few refreshes")
        QTest.qWait(700)
        self.assertEqual(len(calls), settled, "a refresh must not trigger another")
        self.assertEqual(self.tree.selected_path(), self._p("src/main.c"))

    def test_watched_paths_follow_expansion_and_root(self):
        def norm(p):
            return os.path.normcase(os.path.abspath(p))

        def watched():
            return {norm(p) for p in self.tree._watcher.directories()}
        self.tree.expand(self._p("src"))
        self.assertEqual(watched(), {norm(self.dir), norm(self._p("src"))})
        src_index = self.tree.view.model().index(1, 0)
        self.assertEqual(src_index.data(Qt.UserRole), self._p("src"))
        self.tree.view.collapse(src_index)
        self.assertEqual(watched(), {norm(self.dir)})
        other = self._outside()
        self.tree.set_root(other)
        self.assertEqual(watched(), {norm(other)})
        self.tree.set_root("")
        self.assertEqual(watched(), set())

    def test_filter_restores_expansion_and_finds_deep_files(self):
        os.makedirs(self._p("a/b/c"))
        with open(self._p("a/b/c/deep.txt"), "w") as f:
            f.write("\n")
        self.tree.refresh()
        self.tree.expand(self._p("assets"))
        self.tree.set_filter("DEEP")
        self.assertEqual(self.tree.visible_paths(),
                         [self._p("a"), self._p("a/b"), self._p("a/b/c"), self._p("a/b/c/deep.txt")])
        self.tree.set_filter("")
        visible = self.tree.visible_paths()
        self.assertIn(self._p("assets/logo.png"), visible)
        self.assertNotIn(self._p("a/b"), visible)

    def test_filter_honours_the_entry_cap(self):
        for i in range(30):
            os.makedirs(self._p(f"d{i:02}"))
            with open(self._p(f"d{i:02}/hit.txt"), "w") as f:
                f.write("\n")
        self.tree.refresh()
        saved = pf._FILTER_MAX_ENTRIES
        pf._FILTER_MAX_ENTRIES = 40
        try:
            self.tree.set_filter("hit")
        finally:
            pf._FILTER_MAX_ENTRIES = saved
        hits = [p for p in self.tree.visible_paths() if p.endswith("hit.txt")]
        self.assertTrue(0 < len(hits) < 30, len(hits))

    def test_no_public_name_shadows_qwidget(self):
        from PySide6.QtWidgets import QWidget
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        picker = WidgetPicker(workspace)
        self.addCleanup(picker.deleteLater)
        for cls in (ProjectTree, WidgetPicker):
            for name in vars(cls):
                if not name.startswith("_") and name not in ("eventFilter", "staticMetaObject"):
                    self.assertFalse(hasattr(QWidget, name), f"{cls.__name__}.{name}")
        for name in ("view", "filter_edit", "empty_label"):
            self.assertFalse(hasattr(QWidget, name), name)
            self.assertIsInstance(getattr(self.tree, name), QWidget)
        for name in ("list", "filter_edit"):
            self.assertFalse(hasattr(QWidget, name), name)
            self.assertIsInstance(getattr(picker, name), QWidget)


class _SizeRecordingRenderer(_FakeRenderer):
    def __init__(self):
        super().__init__()
        self.sizes = {}

    def image_for(self, widget, width, height, theme, scale=1.0):
        self.sizes[widget.id] = (width, height)
        return super().image_for(widget, width, height, theme, scale)


class W1PickerQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.ws.add_widget("ShGauge")
        self.ws.add_widget("ShButton")
        self.renderer = _SizeRecordingRenderer()
        self.ws.scene.qml_previews = self.renderer
        self.picker = WidgetPicker(self.ws)
        self.addCleanup(self.picker.deleteLater)

    def _ids(self):
        return [w.id for w in self.ws.current_page.widgets]

    def test_rebuilds_on_design_change_with_a_registered_type(self):
        # The frozen test adds "ShSwitch", which the registry does not have.
        self.ws.add_widget("ShToggle")
        self.assertEqual(len(self._ids()), 3)
        self.assertEqual(self.picker.widget_ids(), self._ids())

    def test_thumbnail_asked_at_geometry_size(self):
        for widget in self.ws.current_page.widgets:
            self.assertEqual(self.renderer.sizes[widget.id],
                             (int(widget.geometry["width"]), int(widget.geometry["height"])))

    def test_ready_fills_in_without_rebuilding(self):
        from designer.ide.widget_picker import THUMB_SIZE
        target = self._ids()[0]
        self.picker.list.item(0).setData(Qt.UserRole + 50, "same row")
        self.renderer.land(target)
        self.assertEqual(self.picker.list.item(0).data(Qt.UserRole + 50), "same row")
        image = self.picker.thumbnail(target)
        self.assertIsNotNone(image)
        self.assertLessEqual(image.width(), THUMB_SIZE.width())
        self.assertLessEqual(image.height(), THUMB_SIZE.height())

    def test_swapped_out_renderer_is_ignored(self):
        old = self.renderer
        self.ws.scene.qml_previews = None
        self.picker.rebuild()
        old.land(self._ids()[0])
        self.assertIsNone(self.picker.thumbnail(self._ids()[0]))
        self.assertEqual(self.picker.widget_ids(), self._ids())

    def test_filter_does_not_rerequest(self):
        before = len(self.renderer.requests)
        self.picker.set_filter("button")
        self.picker.set_filter("")
        self.assertEqual(len(self.renderer.requests), before)

    def test_canvas_selection_does_not_pick_back(self):
        calls, picked = [], []
        real = self.ws.select_widget
        self.ws.select_widget = lambda wid: (calls.append(wid), real(wid))[1]
        self.picker.widgetPicked.connect(picked.append)
        target = self._ids()[1]
        self.ws.scene.clearSelection()
        self.ws.scene.item_for_id(target).setSelected(True)
        QTest.qWait(10)
        self.assertEqual(self.picker.highlighted_id(), target)
        self.assertEqual((calls, picked), ([], []))
        self.ws.scene.selectionIdsChanged.emit(self._ids())
        self.assertEqual(self.picker.highlighted_id(), "")

    def test_nested_widgets_indented_in_page_order(self):
        from designer.model import DesignerWidget
        from designer.ide.widget_picker import _DEPTH_ROLE
        gauge = self.ws.current_page.widgets[0]
        gauge.children.append(DesignerWidget("Text", "inner", {"x": 0, "y": 0, "width": 30, "height": 10}))
        self.picker.rebuild()
        self.assertEqual(self.picker.widget_ids(), [gauge.id, "inner", self._ids()[1]])
        depths = [self.picker.list.item(i).data(_DEPTH_ROLE) for i in range(self.picker.list.count())]
        self.assertEqual(depths, [0, 1, 0])

    def test_rebuild_keeps_scroll_position(self):
        for _ in range(12):
            self.ws.add_widget("ShButton")
        self.picker.resize(220, 160)
        self.picker.show()
        self.addCleanup(self.picker.hide)
        QTest.qWait(20)
        bar = self.picker.list.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum() // 2)
        kept = bar.value()
        self.picker.rebuild()
        self.assertEqual(bar.value(), kept)


if __name__ == "__main__":
    unittest.main()
