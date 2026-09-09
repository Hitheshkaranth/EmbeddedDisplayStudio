import unittest
from tools.hmi_deployer.readiness_core import audit_readiness, ReadinessItem


class TestAuditReadiness(unittest.TestCase):
    """Tests for the audit_readiness function covering all four rows."""

    def _make_manifest(self, width=None, height=None, tags_required=None):
        """Helper to build a manifest dict with optional nested screen fields."""
        m = {}
        if width is not None or height is not None:
            screen = {}
            if width is not None:
                screen["width"] = width
            if height is not None:
                screen["height"] = height
            m["screen"] = screen
        if tags_required is not None:
            m["tags_required"] = tags_required
        return m

    # -- Bundle row tests --

    def test_bundle_error_when_manifest_is_none(self):
        bundle, _, _, _ = audit_readiness(
            bundle_valid=True,
            manifest=None,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(bundle, ReadinessItem)
        self.assertEqual(bundle.name, "Bundle")
        self.assertEqual(bundle.severity, "error")

    def test_bundle_error_when_bundle_invalid(self):
        manifest = self._make_manifest(width=1920, height=1080)
        bundle, _, _, _ = audit_readiness(
            bundle_valid=False,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(bundle, ReadinessItem)
        self.assertEqual(bundle.name, "Bundle")
        self.assertEqual(bundle.severity, "error")

    def test_bundle_ready_when_valid(self):
        manifest = self._make_manifest(width=1920, height=1080)
        bundle, _, _, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(bundle, ReadinessItem)
        self.assertEqual(bundle.name, "Bundle")
        self.assertEqual(bundle.severity, "ready")

    # -- Target row tests --

    def test_target_ready_when_connected(self):
        manifest = self._make_manifest(width=1920, height=1080)
        _, target, _, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(target, ReadinessItem)
        self.assertEqual(target.name, "Target")
        self.assertEqual(target.severity, "ready")

    def test_target_warning_when_disconnected(self):
        manifest = self._make_manifest(width=1920, height=1080)
        _, target, _, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=False,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(target, ReadinessItem)
        self.assertEqual(target.name, "Target")
        self.assertEqual(target.severity, "warning")

    # -- Display row tests --

    def test_display_ready_on_geometry_match(self):
        manifest = self._make_manifest(width=1920, height=1080)
        _, _, display, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(display, ReadinessItem)
        self.assertEqual(display.name, "Display")
        self.assertEqual(display.severity, "ready")

    def test_display_warning_on_mismatch(self):
        manifest = self._make_manifest(width=1920, height=1080)
        _, _, display, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(3840, 2160),
        )
        self.assertIsInstance(display, ReadinessItem)
        self.assertEqual(display.name, "Display")
        self.assertEqual(display.severity, "warning")

    def test_display_info_when_unavailable_geometry(self):
        manifest = self._make_manifest()  # no width/height
        _, _, display, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(display, ReadinessItem)
        self.assertEqual(display.name, "Display")
        self.assertEqual(display.severity, "info")

    def test_display_info_when_no_screen_key(self):
        manifest = {"tags_required": ["tag1"]}
        _, _, display, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(display, ReadinessItem)
        self.assertEqual(display.name, "Display")
        self.assertEqual(display.severity, "info")

    def test_display_info_when_detected_resolution_none(self):
        manifest = self._make_manifest(width=1920, height=1080)
        _, _, display, _ = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=None,
        )
        self.assertIsInstance(display, ReadinessItem)
        self.assertEqual(display.name, "Display")
        self.assertEqual(display.severity, "info")

    # -- Tags row tests --

    def test_tags_ready_with_nonempty_tags_required(self):
        manifest = self._make_manifest(
            width=1920, height=1080, tags_required=["tag1", "tag2"]
        )
        _, _, _, tags = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(tags, ReadinessItem)
        self.assertEqual(tags.name, "Tags")
        self.assertEqual(tags.severity, "ready")

    def test_tags_info_when_no_tags_required(self):
        manifest = self._make_manifest(width=1920, height=1080)
        _, _, _, tags = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(tags, ReadinessItem)
        self.assertEqual(tags.name, "Tags")
        self.assertEqual(tags.severity, "info")

    def test_tags_info_when_empty_tags_required(self):
        manifest = self._make_manifest(
            width=1920, height=1080, tags_required=[]
        )
        _, _, _, tags = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(tags, ReadinessItem)
        self.assertEqual(tags.name, "Tags")
        self.assertEqual(tags.severity, "info")

    def test_tags_info_when_manifest_none(self):
        _, _, _, tags = audit_readiness(
            bundle_valid=True,
            manifest=None,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(tags, ReadinessItem)
        self.assertEqual(tags.name, "Tags")
        self.assertEqual(tags.severity, "info")

    # -- Return type test --

    def test_returns_exactly_four_items(self):
        manifest = self._make_manifest(width=1920, height=1080)
        result = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 4)
        for item in result:
            self.assertIsInstance(item, ReadinessItem)

    def test_return_order_bundle_target_display_tags(self):
        manifest = self._make_manifest(width=1920, height=1080)
        bundle, target, display, tags = audit_readiness(
            bundle_valid=True,
            manifest=manifest,
            connected=True,
            detected_resolution=(1920, 1080),
        )
        self.assertEqual(bundle.name, "Bundle")
        self.assertEqual(target.name, "Target")
        self.assertEqual(display.name, "Display")
        self.assertEqual(tags.name, "Tags")


if __name__ == "__main__":
    unittest.main()