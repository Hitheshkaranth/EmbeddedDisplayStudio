"""Wave 6 gate B -- a plan with regions is laid out the way its reference
picture is (designer/layout/reference.py, the "reference layout" family).
FROZEN (skeleton).

The fixture is the haul-truck cockpit the user attached: a status strip with
the clock in the middle, the gear selector in a rail at the left edge, the
speed arc top-left, the truck in the middle, RPM and payload along the bottom,
and Incline / Tires / Fuel / Vitals stacked in a column on the right.
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_w6_contract import reference_project  # noqa: E402


def _walk(widgets, ox=0.0, oy=0.0):
    for w in widgets:
        g = w.geometry
        x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
        yield w, (x, y, float(g.get("width", 0)), float(g.get("height", 0)))
        yield from _walk(w.children, x, y)


def _rects(project):
    return {w.id: r for w, r in _walk(project.pages[0].widgets)}


def _centre(r):
    return r[0] + r[2] / 2.0, r[1] + r[3] / 2.0


class ReferenceLayout(unittest.TestCase):
    W, H = 1024, 768

    def setUp(self):
        self.project = reference_project(self.W, self.H)
        self.rects = _rects(self.project)

    def test_the_family_lays_it_out(self):
        from designer.layout import families
        self.assertIn("reference layout", families.names())
        report = self.project._compile_reports[0] if hasattr(self.project, "_compile_reports") else None
        from designer.layout.compiler import compile_page
        from designer.palette.widget_registry import default_registry
        report = compile_page(self.project, self.project.pages[0], default_registry())
        self.assertEqual(report.layout, "reference layout")

    def test_regions_are_where_the_picture_has_them(self):
        r, W, H = self.rects, self.W, self.H
        gx, gy = _centre(r["gear"])
        self.assertLess(r["gear"][0] + r["gear"][2], W * 0.14, "gear rail hugs the left edge")
        sx, sy = _centre(r["speed"])
        self.assertLess(sx, W * 0.45)
        self.assertLess(sy, H * 0.55, "speed arc in the upper body")
        self.assertGreater(sx, r["gear"][0] + r["gear"][2], "speed sits right of the rail")
        tx, ty = _centre(r["truckPicture"])
        self.assertTrue(W * 0.3 < tx < W * 0.7, "the truck is in the middle")
        for gid in ("rpm", "payload"):
            self.assertGreater(_centre(r[gid])[1], H * 0.55, f"{gid} is in the bottom row")
            self.assertLess(_centre(r[gid])[0], W * 0.68, f"{gid} is not in the right column")
        self.assertLess(_centre(r["rpm"])[0], _centre(r["payload"])[0], "RPM left of payload")
        for wid in ("heading", "tires", "fuel", "coolant"):
            self.assertGreater(_centre(r[wid])[0], W * 0.68, f"{wid} is in the right column")
        order = [_centre(r[w])[1] for w in ("heading", "tires", "fuel", "coolant")]
        self.assertEqual(order, sorted(order), "right column keeps the plan's order top to bottom")

    def test_the_clock_is_centred_in_the_top_strip(self):
        clock = self.rects["clock"]
        cx, cy = _centre(clock)
        self.assertLess(abs(cx - self.W / 2.0), self.W * 0.08)
        self.assertLess(cy, self.H * 0.12)
        self.assertGreater(self.project.pages[0].widgets and
                           next(w for w, _r in _walk(self.project.pages[0].widgets) if w.id == "clock")
                           .properties.get("fontSize", 0), 28, "the clock reads big")

    def test_nothing_leaves_the_glass_or_overlaps(self):
        planned = [wid for wid in ("gear", "speed", "truckPicture", "rpm", "payload", "heading",
                                   "attitude", "tires", "fuel", "coolant", "oil", "trans", "clock")]
        for wid in planned:
            x, y, w, h = self.rects[wid]
            self.assertTrue(w > 8 and h > 8, f"{wid} has a size")
            self.assertTrue(x >= 0 and y >= 0 and x + w <= self.W + 1 and y + h <= self.H + 1, f"{wid} on screen")
        for i, a in enumerate(planned):
            for b in planned[i + 1:]:
                ra, rb = self.rects[a], self.rects[b]
                ix = min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0])
                iy = min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1])
                self.assertFalse(ix > 2 and iy > 2, f"{a} overlaps {b}")

    def test_a_recompile_rebuilds_the_same_screen(self):
        from designer.layout.compiler import compile_page
        from designer.palette.widget_registry import default_registry
        before = {k: v for k, v in self.rects.items()}
        compile_page(self.project, self.project.pages[0], default_registry())
        after = _rects(self.project)
        for wid in ("gear", "speed", "truckPicture", "rpm", "payload", "tires", "coolant", "clock"):
            for a, b in zip(before[wid], after[wid]):
                self.assertLessEqual(abs(a - b), 2, wid)

    def test_other_screen_sizes_keep_the_arrangement(self):
        for size in ((1280, 800), (800, 480)):
            project = reference_project(*size)
            r = _rects(project)
            self.assertGreater(_centre(r["tires"])[0], size[0] * 0.66, size)
            self.assertGreater(_centre(r["rpm"])[1], size[1] * 0.5, size)

    def test_a_plan_without_regions_is_not_this_family(self):
        from designer.layout import families
        from designer.layout.compiler import Section
        plain = [Section("A", "readings", [object()]), Section("B", "readings", [object()])]
        found = families.family_for(plain, [], 1024, 768)
        self.assertNotEqual(found and found[0], "reference layout")


if __name__ == "__main__":
    unittest.main()
