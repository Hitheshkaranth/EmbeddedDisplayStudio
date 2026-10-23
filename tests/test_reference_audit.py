"""Reference readiness distinguishes configuration from verified operation."""
import copy
import unittest

from designer.model import DesignerProject
from tools.hmi_deployer.reference_audit import audit_reference


def widget(kind, ident, **extra):
    return {"type": kind, "id": ident,
            "geometry": {"x": 10, "y": 10, "width": 160, "height": 40}, **extra}


def project(*widgets):
    return DesignerProject.from_dict({"screen": {"width": 800, "height": 600},
                                     "pages": [{"id": "main", "widgets": list(widgets)}]})


class ReferenceAuditTests(unittest.TestCase):
    def test_unwired_controls_and_static_readings_are_not_ready(self):
        result = audit_reference(project(widget("ShButton", "nav"),
                                         widget("ShToggle", "heater"),
                                         widget("ShKpiTile", "temp")))
        self.assertFalse(result.configuration_ready)
        self.assertEqual(sum(i.kind == "missing_action" for i in result.issues), 2)
        self.assertTrue(any(i.kind == "missing_live_binding" for i in result.issues))

    def test_configured_is_not_runtime_or_visual_verification(self):
        p = project(widget("ShButton", "nav", actions={"clicked": {"kind": "navigate", "page": "main"}}),
                    widget("ShToggle", "heater", bindings={"checked": "plant.heater"},
                           actions={"toggled": {"kind": "toggle", "tag": "plant.heater"}}),
                    widget("ShKpiTile", "temp", bindings={"value": "plant.temp"}))
        before = copy.deepcopy(p.to_dict())
        result = audit_reference(p)
        self.assertTrue(result.configuration_ready, result.issues)
        self.assertEqual(p.to_dict(), before)
        for key in ("runtime_verified", "deployment_verified", "visual_match_verified"):
            self.assertFalse(result.to_dict()[key])

    def test_invalid_navigation_cannot_pass_as_wired(self):
        result = audit_reference(project(widget("ShButton", "nav", actions={
            "clicked": {"kind": "navigate", "page": "missing"}})))
        self.assertFalse(result.configuration_ready)
        self.assertTrue(any(i.kind == "invalid_configuration" for i in result.issues))

    def test_disabled_controls_static_text_and_logo_are_allowed(self):
        result = audit_reference(project(widget("ShButton", "disabled", properties={"enabled": False}),
                                         widget("Text", "label", properties={"text": "Title"}),
                                         widget("Image", "logo")))
        self.assertFalse(any(i.kind in ("missing_action", "missing_live_binding", "raster_diagram")
                             for i in result.issues))

    def test_raster_diagram_is_explicit_without_claiming_no_overlays(self):
        result = audit_reference(project(widget("Image", "pfd")))
        self.assertEqual(result.counts["diagram_images"], 1)
        self.assertTrue(any(i.kind == "raster_diagram" and i.severity == "warning"
                            for i in result.issues))

    def test_whole_reference_cannot_substitute_for_a_process_diagram(self):
        item = widget("Image", "processDiagram", properties={"_crop": [0, 0, 1, 1]})
        item["geometry"].update(width=600, height=300)
        result = audit_reference(project(item))
        self.assertFalse(result.configuration_ready)
        self.assertTrue(any(i.kind == "screenshot_substitution" for i in result.issues))
        self.assertEqual(result.counts["diagram_images"], 1)

    def test_nested_bounds_include_parent_position(self):
        child = widget("Text", "child", properties={"text": "x"})
        parent = widget("Rectangle", "parent", children=[child])
        parent["geometry"]["x"] = 700
        result = audit_reference(project(parent))
        self.assertTrue(any(i.kind == "bounds" and i.widget_id == "child" for i in result.issues))

    def test_text_clipping_is_an_estimate_not_a_verified_failure(self):
        result = audit_reference(project(widget("Text", "label", properties={
            "text": "A considerably longer line than this widget can display", "fontSize": 20})))
        self.assertTrue(any(i.kind == "text_fit_estimate" and i.severity == "warning"
                            for i in result.issues))

    def test_empty_design_is_not_ready(self):
        self.assertFalse(audit_reference(project()).configuration_ready)

    def test_measured_section_fallback_is_not_ready(self):
        p = project(widget("Text", "label", properties={"text": "Label", "_box": [0, 0, 1, 1],
                    "_reference": {"layout": "measured", "width": 800, "height": 600,
                                   "viewport": [0, 0, 1000, 1000]}}))
        result = audit_reference(p)
        self.assertFalse(result.configuration_ready)
        self.assertTrue(any(i.kind == "missing_measured_box" for i in result.issues))

    def test_invalid_measured_metadata_is_not_hidden_by_compiler_fallback(self):
        p = project(widget("Text", "label", properties={"text": "Label", "_wbox": [.1, .1, .4, .2],
                    "_reference": {"layout": "measured", "width": float("nan"), "height": 600,
                                   "viewport": [900, 0, 100, 1000]}}))
        result = audit_reference(p)
        self.assertFalse(result.configuration_ready)
        self.assertTrue({"invalid_reference_size", "invalid_reference_viewport"} <=
                        {i.kind for i in result.issues})

    def test_valid_thin_measured_box_is_ready(self):
        p = project(widget("Rectangle", "pipe", properties={"_wbox": [.1, .1, .4, .101],
                    "_reference": {"layout": "measured", "width": 800, "height": 600,
                                   "viewport": [0, 0, 1000, 1000]}}))
        self.assertTrue(audit_reference(p).configuration_ready)

    def test_fully_wired_generic_layout_is_not_reference_fidelity_ready(self):
        p = project(widget("ShButton", "nav", actions={"clicked": {"kind": "navigate", "page": "main"}}),
                    widget("ShKpiTile", "temp", bindings={"value": "plant.temp"}))
        self.assertTrue(audit_reference(p).configuration_ready)
        result = audit_reference(p, require_measured=True)
        self.assertFalse(result.configuration_ready)
        findings = [i for i in result.issues if i.kind == "missing_reference_geometry"]
        self.assertEqual(len(findings), 1, "One useful geometry error per page, not one per widget")
        self.assertIn("nav, temp", findings[0].message)


if __name__ == "__main__":
    unittest.main()
