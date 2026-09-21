"""
tests/native/test_conformance_faces.py
Black-box conformance test — the native/Canvas face switch.
"""
import os
import unittest

from .loader_harness import LoaderHarness, is_native


class TestConformanceFaces(unittest.TestCase):
    def setUp(self):
        self.harness = LoaderHarness(
            apps_dir=os.path.join(os.path.dirname(__file__), "fixtures", "faces-app"),
        )
        self.addCleanup(self.harness.stop)

    def test_switch_matches_loader(self):
        self.harness.start()
        line = self.harness.wait_for(r"PROBE faces", timeout=20)
        if is_native():
            self.assertIn("native=true", line)
        else:
            self.assertIn("native=false", line)

    def test_env_forces_canvas(self):
        if not is_native():
            self.skipTest("HMI_GUI_CMD not set; skip env-force test")
        old = os.environ.get("HMI_NATIVE_FACES")
        self.addCleanup(lambda: self._restore(old))
        os.environ["HMI_NATIVE_FACES"] = "0"
        self.harness.stop()
        self.harness = LoaderHarness(
            apps_dir=os.path.join(os.path.dirname(__file__), "fixtures", "faces-app"),
        )
        self.addCleanup(self.harness.stop)
        self.harness.start()
        line = self.harness.wait_for(r"PROBE faces", timeout=20)
        self.assertIn("native=false", line)

    @staticmethod
    def _restore(old):
        if old is None:
            os.environ.pop("HMI_NATIVE_FACES", None)
        else:
            os.environ["HMI_NATIVE_FACES"] = old

    def test_widgets_load_without_warnings(self):
        self.harness.start()
        self.harness.wait_for(r"PROBE faces", timeout=20)
        bad = []
        for line in self.harness.lines():
            if "QML Warning" in line:
                if "Member data of the object" not in line and "font" not in line:
                    bad.append(line)
        self.assertFalse(bad, "QML warnings detected:\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
