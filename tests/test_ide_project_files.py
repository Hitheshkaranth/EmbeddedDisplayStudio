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


if __name__ == "__main__":
    unittest.main()
