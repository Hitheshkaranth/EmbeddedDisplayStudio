"""The interactive Arrange menu uses bounds and actual gaps, not centres."""
import unittest

from designer.layout.selection import arrange, bounds


class SelectionArrangeTests(unittest.TestCase):
    def test_aligns_every_item_to_the_selection_boundary(self):
        rectangles = [
            {"x": 40, "y": 15, "width": 30, "height": 10},
            {"x": 10, "y": 25, "width": 20, "height": 20},
            {"x": 80, "y": 5, "width": 10, "height": 40},
        ]
        result = arrange(rectangles, "right")
        self.assertEqual([rect["x"] + rect["width"] for rect in result], [90, 90, 90])
        self.assertEqual(bounds(rectangles), (10.0, 5.0, 90.0, 45.0))

    def test_horizontal_distribution_equalises_empty_space_for_mixed_widths(self):
        rectangles = [
            {"x": 0, "y": 0, "width": 20, "height": 10},
            {"x": 35, "y": 0, "width": 50, "height": 10},
            {"x": 150, "y": 0, "width": 30, "height": 10},
            {"x": 250, "y": 0, "width": 40, "height": 10},
        ]
        result = arrange(rectangles, "distribute_h")
        ordered = sorted(result, key=lambda rect: rect["x"])
        gaps = [ordered[index + 1]["x"] - (ordered[index]["x"] + ordered[index]["width"])
                for index in range(len(ordered) - 1)]
        self.assertEqual(ordered[0]["x"], 0)
        self.assertEqual(ordered[-1]["x"], 250)
        self.assertEqual(gaps, [50, 50, 50])

    def test_vertical_distribution_preserves_outer_items(self):
        rectangles = [
            {"x": 0, "y": 10, "width": 10, "height": 30},
            {"x": 0, "y": 90, "width": 10, "height": 10},
            {"x": 0, "y": 250, "width": 10, "height": 60},
        ]
        result = arrange(rectangles, "distribute_v")
        self.assertEqual([rect["y"] for rect in result], [10, 140, 250])

    def test_matching_size_uses_the_key_item_and_does_not_mutate_input(self):
        rectangles = [
            {"x": 0, "y": 0, "width": 20, "height": 30},
            {"x": 50, "y": 0, "width": 50, "height": 70},
        ]
        result = arrange(rectangles, "same_height")
        self.assertEqual([rect["height"] for rect in result], [30, 30])
        self.assertEqual(rectangles[1]["height"], 70)


if __name__ == "__main__":
    unittest.main()
