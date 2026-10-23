"""Window close waits asynchronously for image workers to observe Stop."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tools.hmi_deployer.mainwindow import MainWindow


class ReferenceShutdownTests(unittest.TestCase):
    def test_running_image_worker_defers_close_and_stops_once(self):
        worker = SimpleNamespace(reference_target=(800, 600), isRunning=lambda: True, finished=Mock())
        tab = SimpleNamespace(_worker=worker, stop_generation=Mock())
        window = SimpleNamespace(_ai_tab=tab, _finish_reference_close=Mock())
        event = Mock()
        MainWindow.closeEvent(window, event)
        MainWindow.closeEvent(window, event)
        self.assertEqual(event.ignore.call_count, 2)
        tab.stop_generation.assert_called_once()
        worker.finished.connect.assert_called_once_with(window._finish_reference_close)

    def test_finished_worker_retries_close_without_blocking(self):
        window = SimpleNamespace(_closing_reference_worker=True, close=Mock())
        MainWindow._finish_reference_close(window)
        self.assertFalse(window._closing_reference_worker)
        window.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
