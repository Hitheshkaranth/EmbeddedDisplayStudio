"""A relay must never be destroyed while its ssh thread is still running.

Qt aborts the process when a running QThread is destroyed. The relay is torn
down at exactly the moment that is most likely -- _stop_all_senders() calls
stop() and immediately rebinds self.relay to None -- and stop()'s join is
bounded, so a wedged ssh outlasts it. With the worker parented to the relay,
dropping the relay then took the whole Studio down with an access violation on
the main thread, while the worker sat in its read loop.
"""
import gc
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tools.hmi_deployer import telemetry
from tools.hmi_deployer.ssh import SshWorker


class RelayWorkerLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        telemetry._RETIRED_WORKERS.clear()

    def _relay_with_a_live_worker(self, wedged: bool):
        """A relay whose worker runs a real, silent, long-lived child.

        Silent matters: the worker blocks in readline exactly as it does
        against a live telemetry stream.
        """
        relay = telemetry.TelemetryRelay("192.0.2.1", "root", 22, "", None)
        relay.worker.cancel()          # drop the unstarted real ssh worker
        worker = SshWorker([sys.executable, "-c", "import time; time.sleep(20)"],
                           timeout_s=0)
        relay.worker = worker
        if wedged:
            # Simulate an ssh the terminate() cannot reach, which is what makes
            # the bounded wait in stop() time out.
            worker.cancel = lambda: None
        relay.start()
        self.assertTrue(worker.isRunning())

        def cleanup():
            SshWorker.cancel(worker)
            worker.wait(5000)
        self.addCleanup(cleanup)
        return relay, worker

    def test_worker_is_not_a_qt_child_of_the_relay(self):
        """Parenting is what let the relay's destructor delete a live thread."""
        relay = telemetry.TelemetryRelay("192.0.2.1", "root", 22, "", None)
        self.addCleanup(relay.stop)
        self.assertIsNone(relay.worker.parent())

    def test_a_running_worker_is_guarded_from_the_moment_it_starts(self):
        _relay, worker = self._relay_with_a_live_worker(wedged=False)
        self.assertIn(worker, telemetry._RETIRED_WORKERS)

    def test_dropping_a_relay_whose_stop_timed_out_leaves_the_thread_alive(self):
        relay, worker = self._relay_with_a_live_worker(wedged=True)

        relay.stop()                      # cancel is a no-op, so the join times out
        self.assertTrue(worker.isRunning(), "the wedged worker should still be running")

        del relay
        gc.collect()                      # this is where the process used to abort

        self.assertIn(worker, telemetry._RETIRED_WORKERS)
        self.assertTrue(worker.isRunning())

    def test_a_second_stop_still_guards_a_thread_the_first_one_left_running(self):
        relay, worker = self._relay_with_a_live_worker(wedged=True)
        relay.stop()
        telemetry._RETIRED_WORKERS.clear()   # as if the guard had been released

        relay.stop()                          # idempotent path must re-guard

        self.assertIn(worker, telemetry._RETIRED_WORKERS)

    def test_a_finished_worker_is_released_again(self):
        """The guard must not become a permanent leak for healthy workers."""
        relay = telemetry.TelemetryRelay("192.0.2.1", "root", 22, "", None)
        relay.worker.cancel()
        worker = SshWorker([sys.executable, "-c", "pass"], timeout_s=0)
        relay.worker = worker
        relay.start()
        worker.wait(5000)
        # Let the queued finished() reach the release slot on this thread.
        for _ in range(50):
            self.app.processEvents()
            if worker not in telemetry._RETIRED_WORKERS:
                break
        self.assertNotIn(worker, telemetry._RETIRED_WORKERS)
        relay.stop()


if __name__ == "__main__":
    unittest.main()
