"""Tests for deploy bookkeeping that outlives a single attempt."""

import os
import shutil
import tempfile
import unittest

from tools.hmi_deployer.mainwindow import MainWindow


class Window:
    """The state _discard_packaging_dir touches, without building a window."""

    def __init__(self, packaging_dir=None):
        self._packaging_dir = packaging_dir


class TestDiscardPackagingDir(unittest.TestCase):
    """Each attempt cleans up after itself, and only after itself."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hmi-deploy-state-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def make(self, name):
        path = os.path.join(self.root, name)
        os.makedirs(path)
        with open(os.path.join(path, "app.tar.gz"), "w", encoding="utf-8") as handle:
            handle.write("payload")
        return path

    def test_a_late_step_does_not_delete_the_next_deploy(self):
        """The exact failure: the checksum had nothing left to send.

        A deploy whose install step returns minutes late used to remove
        whatever directory the window had on record, which by then belonged to
        the deploy that replaced it -- so its tarball uploaded and the sidecar
        beside it was already gone.
        """
        first = self.make("first")
        second = self.make("second")
        window = Window(packaging_dir=second)

        MainWindow._discard_packaging_dir(window, first)

        self.assertFalse(os.path.exists(first), "the late step must clean up its own")
        self.assertTrue(os.path.exists(second), "the running deploy keeps its files")
        self.assertEqual(window._packaging_dir, second)

    def test_removing_the_recorded_directory_clears_the_record(self):
        """Nothing should point at a directory that is gone."""
        current = self.make("current")
        window = Window(packaging_dir=current)

        MainWindow._discard_packaging_dir(window, current)

        self.assertFalse(os.path.exists(current))
        self.assertIsNone(window._packaging_dir)

    def test_no_argument_removes_the_recorded_directory(self):
        """Callers that own the window's state keep the old behaviour."""
        current = self.make("current")
        window = Window(packaging_dir=current)

        MainWindow._discard_packaging_dir(window)

        self.assertFalse(os.path.exists(current))
        self.assertIsNone(window._packaging_dir)

    def test_nothing_recorded_is_not_an_error(self):
        """A deploy that failed before packaging has nothing to remove."""
        window = Window(packaging_dir=None)

        MainWindow._discard_packaging_dir(window)

        self.assertIsNone(window._packaging_dir)

    def test_a_missing_directory_is_not_an_error(self):
        """Tidying up must never be the thing that fails a deployment."""
        gone = os.path.join(self.root, "never-existed")
        window = Window(packaging_dir=gone)

        MainWindow._discard_packaging_dir(window, gone)

        self.assertIsNone(window._packaging_dir)


if __name__ == "__main__":
    unittest.main()
