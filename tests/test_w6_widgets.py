"""Wave 6 gate C -- the widgets a vehicle cockpit reference needs.
FROZEN (skeleton).

* ShGearIndicator: "orientation" (horizontal | vertical) -- P R N D L in a rail.
* ShVehicleStatus: "axles" (2 | 3) and the middle axle "midLeft"/"midRight"
  (bindable) -- a haul truck's six tyres.
* ShClusterGauge: "accentColor" -- the arc's colour (orange RPM, yellow payload).
* ShEngineBar: "orientation" (vertical | horizontal) and "barColor".
* ShSegmentBar: "barColor".
Each in every layer: the registry, the QML kit and the panel runtime (C).
"""
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ADDED = {
    "ShGearIndicator": ("orientation",),
    "ShVehicleStatus": ("axles", "midLeft", "midRight"),
    "ShClusterGauge": ("accentColor",),
    "ShEngineBar": ("orientation", "barColor"),
    "ShSegmentBar": ("barColor",),
}
COLOURS = {"ShClusterGauge": ("accentColor",), "ShEngineBar": ("barColor",), "ShSegmentBar": ("barColor",)}
BINDABLE = {"ShVehicleStatus": ("midLeft", "midRight")}


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Registry(unittest.TestCase):
    def test_properties_are_declared(self):
        from designer.palette.widget_registry import default_registry
        registry = default_registry()
        for wtype, props in ADDED.items():
            definition = registry.get(wtype)
            for prop in props:
                self.assertIn(prop, definition.properties, f"{wtype}.{prop}")
        for wtype, props in COLOURS.items():
            for prop in props:
                self.assertIn(prop, registry.get(wtype).color_properties, f"{wtype}.{prop} is a colour")
        for wtype, props in BINDABLE.items():
            for prop in props:
                self.assertIn(prop, registry.get(wtype).bindable_properties, f"{wtype}.{prop} binds")
        self.assertEqual(registry.get("ShGearIndicator").defaults.get("orientation"), "horizontal")
        self.assertEqual(int(registry.get("ShVehicleStatus").defaults.get("axles")), 2)


class Layers(unittest.TestCase):
    def test_the_qml_kit_declares_them(self):
        qml_root = os.path.join(ROOT, "ui", "qml")
        found = {}
        for dirpath, _dirs, files in os.walk(qml_root):
            for name in files:
                if name.endswith(".qml"):
                    found[name[:-4]] = os.path.join(dirpath, name)
        for wtype, props in ADDED.items():
            self.assertIn(wtype, found, f"{wtype}.qml")
            text = _read(found[wtype])
            for prop in props:
                self.assertRegex(text, rf"property\s+\w+\s+{prop}\b", f"{wtype}.qml declares {prop}")

    def test_the_panel_runtime_reads_them(self):
        widgets = os.path.join(ROOT, "native", "hmi-ui", "src", "widgets")
        schema = _read(os.path.join(ROOT, "native", "hmi-ui", "src", "gen", "kit_schema.c"))
        for wtype, props in ADDED.items():
            source = _read(os.path.join(widgets, f"w_{wtype.lower()}.c"))
            for prop in props:
                self.assertIn(f'"{prop}"', source, f"w_{wtype.lower()}.c reads {prop}")
                self.assertIn(f'"{prop}"', schema, f"kit_schema.c lists {wtype}.{prop}")


class ValueTileFits(unittest.TestCase):
    def test_a_small_tile_keeps_its_title_and_badge_apart(self):
        """The applied truck design showed "Front-Le" under an OK badge: at a
        compiled size of 124 x 62 the title and the state badge must not overlap."""
        from designer.palette.widget_registry import default_registry
        registry = default_registry()
        self.assertIsNotNone(registry.get("ShValueTile"))
        qml = None
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "ui", "qml")):
            if "ShValueTile.qml" in files:
                qml = _read(os.path.join(dirpath, "ShValueTile.qml"))
        self.assertIsNotNone(qml)
        self.assertTrue(re.search(r"elide\s*:\s*Text\.Elide", qml), "the title elides rather than runs under the badge")


if __name__ == "__main__":
    unittest.main()
