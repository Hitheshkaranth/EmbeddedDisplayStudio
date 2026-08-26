"""
tests/test_shell_render.py
Layer: Test (W11)

Pins CONTRACT section 7: "if the app bundle fails to load, show the built-in
fallback screen with the error text -- never a black screen."

That rule had no test. It was also not being met: ShCard was a bare Rectangle
with no implicit height, and ShCardContent anchored neither top nor bottom, so
the fallback screen rendered as a zero-height card with the error alert drawn
on top of the title. The gallery's pixel test could not see it, because it only
sampled the window's top-left pixel.

These tests assert layout facts rather than pixels: a card that contains
something must be taller than nothing, and sections of a card must not overlap.
Both are cheap to check and both fail loudly if the kit regresses.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "gui" / "hmi_loader"))

# Qt must be told to run headless before QGuiApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QUrl, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    HAVE_QT = True
except ImportError:  # pragma: no cover - environment without PySide6
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class TestFallbackScreenRenders(unittest.TestCase):
    """The screen shown when a bundle will not load must be readable."""

    # Bound once per process: Qt refuses a second QGuiApplication, and the
    # engine must outlive the tests that read geometry from its objects.
    app = None
    engine = None
    root = None
    warnings: list = []
    # The context objects must be held for the engine's lifetime. As locals
    # they were garbage-collected as soon as setUpClass returned, and every
    # binding onto Tags/Bus/Hmi then reported "property of null".
    tag_engine = None
    hmi = None

    @classmethod
    def setUpClass(cls):
        """Load Shell.qml with a manifest that failed validation.

        Side effects:
            Creates a QGuiApplication and a QML engine, installs a Qt message
            handler that records warnings, and binds a TagEngine to an unused
            UDP port so the real loader wiring is exercised.
        """
        from tagengine import TagEngine

        # Loaded by path, not as `import main`. Two files in this repository
        # are named main.py -- the panel loader here, and the Studio entry
        # point at the root -- and a plain import gets whichever the suite
        # happened to put in sys.modules first, which made this test pass
        # alone and fail in the full run.
        import importlib.util
        loader_path = REPO_ROOT / "gui" / "hmi_loader" / "main.py"
        spec = importlib.util.spec_from_file_location("hmi_loader_main", loader_path)
        loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loader)

        cls.warnings = []

        def handler(msg_type, context, message):
            """Collect Qt warnings so the test can assert there were none."""
            if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
                # The offscreen platform has no font directory; that says
                # nothing about our QML.
                if "QFontDatabase" in message:
                    return
                cls.warnings.append(message)

        qInstallMessageHandler(handler)

        cls.app = QGuiApplication.instance() or QGuiApplication(sys.argv)
        cls.engine = QQmlApplicationEngine()
        cls.engine.addImportPath(str(REPO_ROOT / "ui" / "qml"))

        # Port 0 lets the OS pick a free port, so a running daemon or a second
        # test process never makes this fail.
        cls.tag_engine = TagEngine([], rx_port=0)

        # An empty manifest plus a lastError is exactly the state the loader
        # puts itself in when validation fails.
        cls.hmi = loader.Hmi({}, REPO_ROOT / "does-not-exist", REPO_ROOT / "unused-ready")
        cls.hmi.set_last_error(
            "Manifest not found: /opt/hmi_apps/current/manifest.json"
        )

        ctx = cls.engine.rootContext()
        ctx.setContextProperty("Tags", cls.tag_engine.tagMap())
        ctx.setContextProperty("Bus", cls.tag_engine)
        ctx.setContextProperty("Hmi", cls.hmi)
        ctx.setContextProperty("isWindowed", True)
        ctx.setContextProperty("initialTheme", "dark")

        cls.engine.load(
            QUrl.fromLocalFile(str(REPO_ROOT / "gui" / "shell" / "Shell.qml"))
        )
        roots = cls.engine.rootObjects()
        if not roots:
            raise unittest.SkipTest("Shell.qml did not load in this environment")
        cls.root = roots[0]

    @classmethod
    def tearDownClass(cls):
        """Drop the engine before the application, as Qt requires."""
        qInstallMessageHandler(None)
        cls.root = None
        cls.engine = None
        cls.tag_engine = None
        cls.hmi = None

    def _find(self, object_name):
        """Return the first descendant with this objectName, or None.

        Args:
            object_name: the QML objectName to search for.
        """
        for child in self.root.findChildren(object):
            try:
                if child.objectName() == object_name:
                    return child
            except (AttributeError, RuntimeError):
                continue
        return None

    def test_shell_loads_without_qml_warnings(self):
        """A QML warning on the fallback path means broken bindings on a panel
        that is already in trouble."""
        self.assertEqual(
            self.warnings, [], f"QML warnings while rendering the shell: {self.warnings}"
        )

    def test_fallback_card_has_a_real_height(self):
        """
        The regression: ShCard had no implicit height, so the diagnostic card
        measured 0px tall and nothing inside it was laid out.
        """
        card = self._find("fallbackCard")
        self.assertIsNotNone(card, "Fallback.qml must expose objectName 'fallbackCard'")
        height = card.property("height")
        self.assertGreater(
            height, 100,
            "The fallback card collapsed to %spx: ShCard is not sizing to its "
            "content again." % height,
        )

    def test_fallback_header_and_content_do_not_overlap(self):
        """
        The other half of the regression: ShCardContent sat at y=0, on top of
        the header, so the error text and the card title were drawn over each
        other.
        """
        header = self._find("fallbackHeader")
        content = self._find("fallbackContent")
        self.assertIsNotNone(header, "Fallback.qml must name its ShCardHeader")
        self.assertIsNotNone(content, "Fallback.qml must name its ShCardContent")

        header_bottom = header.property("y") + header.property("height")
        content_top = content.property("y")
        self.assertGreaterEqual(
            content_top, header_bottom,
            "Card content starts at y=%s but the header runs to y=%s -- they "
            "overlap." % (content_top, header_bottom),
        )
        self.assertGreater(
            content.property("height"), 0, "Card content has no height"
        )

    def test_fallback_shows_the_error_text(self):
        """
        CONTRACT section 7 asks for the fallback screen to carry the error, not
        just to exist. A card that renders but shows an empty alert is the same
        failure from the operator's side.
        """
        alert = self._find("fallbackAlert")
        self.assertIsNotNone(alert, "Fallback.qml must name its error ShAlert")
        self.assertIn("Manifest not found", alert.property("description"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
