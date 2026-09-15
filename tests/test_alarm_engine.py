"""
tests/test_alarm_engine.py
Purpose: Tests for manifest alarm validation, TagEngine history, and alarm evaluation.
Implements CONTRACT sections 4 (validation) and 9 (alarm semantics).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Must be set BEFORE PySide6 imports
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QCoreApplication


class TestAlarmTagsHelper(unittest.TestCase):
    """Test schema.manifest.alarm_tags() function."""

    def test_alarm_tags_returns_empty_for_none(self):
        from schema.manifest import alarm_tags
        self.assertEqual(alarm_tags(None), [])

    def test_alarm_tags_returns_empty_for_no_alarms(self):
        from schema.manifest import alarm_tags
        self.assertEqual(alarm_tags({}), [])

    def test_alarm_tags_returns_unique_tag_names(self):
        from schema.manifest import alarm_tags
        manifest = {
            "alarms": [
                {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}},
                {"tag": "ai.temperature", "critical": {"op": ">", "value": 200}},
                {"tag": "ai.pressure", "critical": {"op": ">", "value": 150}},
            ]
        }
        result = alarm_tags(manifest)
        self.assertEqual(result, ["ai.pressure", "ai.temperature"])

    def test_alarm_tags_preserves_order(self):
        from schema.manifest import alarm_tags
        manifest = {
            "alarms": [
                {"tag": "z_tag"},
                {"tag": "a_tag"},
                {"tag": "m_tag"},
            ]
        }
        result = alarm_tags(manifest)
        self.assertEqual(result, ["z_tag", "a_tag", "m_tag"])

    def test_alarm_tags_skips_invalid_tags(self):
        from schema.manifest import alarm_tags
        manifest = {
            "alarms": [
                {"tag": 123},  # not a string
                {"tag": "valid_tag"},
            ]
        }
        result = alarm_tags(manifest)
        self.assertEqual(result, ["valid_tag"])


class TestAlarmValidation(unittest.TestCase):
    """Test alarm validation in schema.manifest.validate_bundle()."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_bundle(self, name, manifest_data, create_entry=True):
        bundle_path = os.path.join(self.temp_dir.name, name)
        os.makedirs(bundle_path)

        if manifest_data is not None:
            with open(os.path.join(bundle_path, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest_data, f)

        if create_entry and isinstance(manifest_data, dict) and "entry" in manifest_data:
            entry_path = os.path.join(bundle_path, manifest_data["entry"])
            os.makedirs(os.path.dirname(entry_path), exist_ok=True)
            with open(entry_path, "w", encoding="utf-8") as f:
                f.write("import QtQuick\n")

        return bundle_path

    def _valid_base_manifest(self):
        return {
            "schema": 1,
            "name": "test-app",
            "version": "1.0.0",
            "entry": "main.qml",
            "tags_required": ["ai.pressure"],
        }

    def test_alarm_validation_accepts_valid_warning(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ]
        bundle = self._create_bundle("valid_warning", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is True)

    def test_alarm_validation_accepts_valid_critical(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"tag": "ai.pressure", "critical": {"op": "<=", "value": 0}}
        ]
        bundle = self._create_bundle("valid_critical", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is True)

    def test_alarm_validation_accepts_both_warning_and_critical(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {
                "tag": "ai.pressure",
                "warning": {"op": ">", "value": 100},
                "critical": {"op": ">", "value": 150},
            }
        ]
        bundle = self._create_bundle("both_thresholds", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is True)

    def test_alarm_validation_rejects_unknown_op(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"tag": "ai.pressure", "warning": {"op": "~=", "value": 100}}
        ]
        bundle = self._create_bundle("bad_op", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is False)
        self.assertTrue(any("~=" in str(e) for e in errors))

    def test_alarm_validation_rejects_non_numeric_value(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"tag": "ai.pressure", "warning": {"op": ">", "value": "high"}}
        ]
        bundle = self._create_bundle("bad_value", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is False)
        self.assertTrue(any("value" in str(e).lower() for e in errors))

    def test_alarm_validation_rejects_missing_tag(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"warning": {"op": ">", "value": 100}}
        ]
        bundle = self._create_bundle("missing_tag", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is False)
        self.assertTrue(any("tag" in str(e) for e in errors))

    def test_alarm_validation_rejects_tag_not_matching_regex(self):
        from schema.manifest import validate_bundle, _ALARM_TAG_RE
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"tag": "invalid tag!", "warning": {"op": ">", "value": 100}}
        ]
        bundle = self._create_bundle("bad_tag_regex", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is False)
        self.assertTrue(any("tag" in str(e).lower() for e in errors))

    def test_alarm_validation_requires_at_least_one_threshold(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"tag": "ai.pressure", "label": "Pressure Alarm"}
        ]
        bundle = self._create_bundle("no_threshold", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is False)
        self.assertTrue(any("warning" in str(e).lower() and "critical" in str(e).lower() for e in errors))

    def test_alarm_validation_allows_label_and_unit(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {
                "tag": "ai.pressure",
                "label": "Pressure",
                "unit": " bar",
                "warning": {"op": ">", "value": 100},
            }
        ]
        bundle = self._create_bundle("label_unit", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is True)

    def test_alarm_validation_allows_list_of_alarms(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = [
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}},
            {"tag": "ai.temperature", "critical": {"op": ">", "value": 200}},
        ]
        bundle = self._create_bundle("multiple_alarms", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is True)

    def test_alarm_validation_rejects_alarm_not_a_list(self):
        from schema.manifest import validate_bundle
        manifest = self._valid_base_manifest()
        manifest["alarms"] = "not a list"
        bundle = self._create_bundle("bad_alarms_type", manifest)
        ok, errors = validate_bundle(bundle)
        self.assertTrue(ok is False)
        self.assertTrue(any("alarm" in str(e).lower() for e in errors))


class TestTagEngineHistory(unittest.TestCase):
    """Test TagEngine history ring buffer."""

    @classmethod
    def setUpClass(cls):
        """Create the QCoreApplication once for all tests in this class."""
        cls.app = QCoreApplication.instance()
        if not cls.app:
            cls.app = QCoreApplication(sys.argv)

    def _create_engine(self, expected_tags=None, history_depth=600):
        from gui.hmi_loader.tagengine import TagEngine
        return TagEngine(expected_tags or [], history_depth=history_depth)

    def test_history_empty_for_unknown_tag(self):
        engine = self._create_engine([])
        result = engine.history("unknown_tag", 10)
        self.assertEqual(result, [])

    def test_history_records_numeric_values(self):
        engine = self._create_engine(["ai.val"])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 42.0}})
        hist = engine.history("ai.val", 10)
        self.assertEqual(hist, [42.0])

    def test_history_converts_bool_to_0_1(self):
        engine = self._create_engine(["do.output"])
        engine._handle_telemetry({"kind": "tags", "tags": {"do.output": True}})
        hist = engine.history("do.output", 10)
        self.assertEqual(hist, [1])

        engine2 = self._create_engine(["do.output2"])
        engine2._handle_telemetry({"kind": "tags", "tags": {"do.output2": False}})
        hist2 = engine2.history("do.output2", 10)
        self.assertEqual(hist2, [0])

    def test_history_skips_null(self):
        engine = self._create_engine(["ai.val"])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": None}})
        hist = engine.history("ai.val", 10)
        self.assertEqual(hist, [])

    def test_history_ring_buffer_respects_depth(self):
        engine = self._create_engine(["ai.val"], history_depth=3)
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 1}})
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 2}})
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 3}})
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 4}})
        hist = engine.history("ai.val", 100)
        self.assertEqual(hist, [2, 3, 4])

    def test_history_returns_oldest_first(self):
        engine = self._create_engine(["ai.val"])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 1}})
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 2}})
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 3}})
        hist = engine.history("ai.val", 10)
        self.assertEqual(hist, [1, 2, 3])

    def test_history_respects_n_parameter(self):
        engine = self._create_engine(["ai.val"])
        for i in range(5):
            engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": i + 1}})
        hist = engine.history("ai.val", 2)
        self.assertEqual(hist, [4, 5])

    def test_history_version_increments_per_frame(self):
        engine = self._create_engine(["ai.val"])
        ver1 = engine.get_history_version()
        self.assertEqual(ver1, 0)
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 1}})
        ver2 = engine.get_history_version()
        self.assertEqual(ver2, 1)
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 2}})
        ver3 = engine.get_history_version()
        self.assertEqual(ver3, 2)

    def test_history_underscore_alias(self):
        engine = self._create_engine(["ai.val"])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 42}})
        hist = engine.history("ai_val", 10)
        self.assertEqual(hist, [42])


class TestAlarmEvaluation(unittest.TestCase):
    """Test TagEngine alarm evaluation logic."""

    @classmethod
    def setUpClass(cls):
        """Create the QCoreApplication once for all tests in this class."""
        cls.app = QCoreApplication.instance()
        if not cls.app:
            cls.app = QCoreApplication(sys.argv)

    def _create_engine_with_alarms(self, alarm_defs):
        from gui.hmi_loader.tagengine import TagEngine
        engine = TagEngine([], alarm_defs=alarm_defs)
        return engine

    def test_alarm_activates_on_threshold_breach(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 50}})
        self.assertEqual(engine.get_alarm_count(), 0)

        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        self.assertEqual(engine.get_alarm_count(), 1)
        alarms = engine.get_active_alarms()
        self.assertEqual(alarms[0]["severity"], "warning")
        self.assertEqual(alarms[0]["tag"], "ai.pressure")
        self.assertEqual(alarms[0]["acknowledged"], False)

    def test_alarm_critical_takes_priority(self):
        engine = self._create_engine_with_alarms([
            {
                "tag": "ai.pressure",
                "warning": {"op": ">", "value": 100},
                "critical": {"op": ">", "value": 150},
            }
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 200}})
        alarms = engine.get_active_alarms()
        self.assertEqual(alarms[0]["severity"], "critical")

    def test_alarm_persists_across_frames_and_notifies_only_on_change(self):
        """An alarm that stays tripped stays listed; identical frames are silent.

        The first cut kept only alarms that were new or escalated on this
        frame, so a steady over-limit reading was listed on odd frames and
        dropped on even ones, and the change signal fired on every frame
        regardless.
        """
        engine = self._create_engine_with_alarms([
            {"tag": "ai.val", "label": "Val", "warning": {"op": ">", "value": 10},
             "critical": {"op": ">", "value": 20}},
        ])
        fired = []
        engine.activeAlarmsChanged.connect(lambda: fired.append(len(engine.get_active_alarms())))
        for value in (15, 15, 16, 15):
            engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": value}})
            self.assertEqual([a["severity"] for a in engine.get_active_alarms()], ["warning"], value)
        self.assertEqual(fired, [1], "one activation, then silence for a steady alarm")
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 25}})
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 26}})
        self.assertEqual([a["severity"] for a in engine.get_active_alarms()], ["critical"])
        self.assertEqual(fired, [1, 1], "escalation notifies once")
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 5}})
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 5}})
        self.assertEqual(engine.get_active_alarms(), [])
        self.assertEqual(fired, [1, 1, 0], "clearing notifies once")

    def test_alarm_clears_when_value_returns_to_normal(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        self.assertEqual(engine.get_alarm_count(), 1)

        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 50}})
        self.assertEqual(engine.get_alarm_count(), 0)

    def test_alarm_null_clears(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        self.assertEqual(engine.get_alarm_count(), 1)

        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": None}})
        self.assertEqual(engine.get_alarm_count(), 0)

    def test_alarm_severity_escalation(self):
        engine = self._create_engine_with_alarms([
            {
                "tag": "ai.pressure",
                "warning": {"op": ">", "value": 100},
                "critical": {"op": ">", "value": 200},
            }
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        self.assertEqual(engine.get_active_alarms()[0]["severity"], "warning")

        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 250}})
        self.assertEqual(engine.get_active_alarms()[0]["severity"], "critical")

    def test_alarm_deescalation(self):
        engine = self._create_engine_with_alarms([
            {
                "tag": "ai.pressure",
                "warning": {"op": ">", "value": 100},
                "critical": {"op": ">", "value": 200},
            }
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 250}})
        self.assertEqual(engine.get_active_alarms()[0]["severity"], "critical")

        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        self.assertEqual(engine.get_active_alarms()[0]["severity"], "warning")

    def test_acknowledge_marks_alarm(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        engine.acknowledge("ai.pressure")
        self.assertEqual(engine.get_active_alarms()[0]["acknowledged"], True)

    def test_acknowledge_uses_underscore_alias(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        engine.acknowledge("ai_pressure")
        self.assertEqual(engine.get_active_alarms()[0]["acknowledged"], True)

    def test_acknowledge_preserves_timestamp(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        initial_timestamp = engine.get_active_alarms()[0]["timestamp"]
        engine.acknowledge("ai.pressure")
        self.assertEqual(engine.get_active_alarms()[0]["timestamp"], initial_timestamp)

    def test_alarms_sorted_critical_first(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.temp", "critical": {"op": ">", "value": 200}},
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}},
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.temp": 250, "ai.pressure": 150}})
        alarms = engine.get_active_alarms()
        self.assertEqual(alarms[0]["severity"], "critical")
        self.assertEqual(alarms[0]["tag"], "ai.temp")
        self.assertEqual(alarms[1]["severity"], "warning")
        self.assertEqual(alarms[1]["tag"], "ai.pressure")

    def test_alarms_with_label(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "label": "Pressure Alarm", "unit": " bar",
             "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        alarms = engine.get_active_alarms()
        self.assertEqual(alarms[0]["label"], "Pressure Alarm")
        self.assertIn("Pressure Alarm", alarms[0]["message"])

    def test_alarm_no_evaluation_without_alarms(self):
        engine = self._create_engine_with_alarms([])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        self.assertEqual(engine.get_alarm_count(), 0)

    def test_alarm_no_evaluation_for_unknown_tag(self):
        engine = self._create_engine_with_alarms([
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.temperature": 150}})
        self.assertEqual(engine.get_alarm_count(), 0)


class TestAlarmHistoryIntegration(unittest.TestCase):
    """Test that alarm tags also get recorded in history."""

    @classmethod
    def setUpClass(cls):
        """Create the QCoreApplication once for all tests in this class."""
        cls.app = QCoreApplication.instance()
        if not cls.app:
            cls.app = QCoreApplication(sys.argv)

    def test_alarm_tag_in_history(self):
        from gui.hmi_loader.tagengine import TagEngine
        engine = TagEngine([], alarm_defs=[
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        hist = engine.history("ai.pressure", 10)
        self.assertEqual(hist, [150])

    def test_alarm_tag_underscore_alias_in_history(self):
        from gui.hmi_loader.tagengine import TagEngine
        engine = TagEngine([], alarm_defs=[
            {"tag": "ai.pressure", "warning": {"op": ">", "value": 100}}
        ])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.pressure": 150}})
        hist = engine.history("ai_pressure", 10)
        self.assertEqual(hist, [150])


class TestBackwardCompatibility(unittest.TestCase):
    """Test that TagEngine still works without alarms parameter."""

    @classmethod
    def setUpClass(cls):
        """Create the QCoreApplication once for all tests in this class."""
        cls.app = QCoreApplication.instance()
        if not cls.app:
            cls.app = QCoreApplication(sys.argv)

    def test_tagengine_works_without_alarms(self):
        from gui.hmi_loader.tagengine import TagEngine
        engine = TagEngine(["ai.val"], history_depth=600)
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 42}})
        self.assertEqual(engine.tagMap().value("ai.val"), 42)
        self.assertEqual(engine.get_alarm_count(), 0)

    def test_tagengine_works_with_empty_alarms(self):
        from gui.hmi_loader.tagengine import TagEngine
        engine = TagEngine(["ai.val"], alarm_defs=[])
        engine._handle_telemetry({"kind": "tags", "tags": {"ai.val": 42}})
        self.assertEqual(engine.tagMap().value("ai.val"), 42)
        self.assertEqual(engine.get_alarm_count(), 0)