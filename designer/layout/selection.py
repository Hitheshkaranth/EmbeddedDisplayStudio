"""Pure geometry used by the Designer's interactive arrange controls.

The composition pipeline in :mod:`designer.layout.arrange` deliberately
optimises a whole screen.  These helpers are smaller: they make the author’s
explicit multi-selection behave predictably, without guessing at a layout.
"""
from __future__ import annotations


def bounds(rectangles: list[dict]) -> tuple[float, float, float, float]:
    """Return the enclosing ``(left, top, right, bottom)`` of rectangles."""
    left = min(float(rect["x"]) for rect in rectangles)
    top = min(float(rect["y"]) for rect in rectangles)
    right = max(float(rect["x"]) + float(rect["width"]) for rect in rectangles)
    bottom = max(float(rect["y"]) + float(rect["height"]) for rect in rectangles)
    return left, top, right, bottom


def arrange(rectangles: list[dict], mode: str, key_index: int = 0) -> list[dict]:
    """Return arranged copies of ``rectangles``.

    Edges and centres align to the selection's enclosing bounds, matching the
    predictable default used by design tools.  Matching a size deliberately
    uses the first selected/key item.  Distribution preserves the outer two
    items and equalises *empty space*, not their x/y coordinates; that matters
    whenever the selection contains mixed-size instruments.
    """
    result = [dict(rectangle) for rectangle in rectangles]
    if len(result) < 2:
        return result
    key = result[max(0, min(int(key_index), len(result) - 1))]
    left, top, right, bottom = bounds(result)

    if mode == "left":
        for rect in result:
            rect["x"] = left
    elif mode == "right":
        for rect in result:
            rect["x"] = right - float(rect["width"])
    elif mode == "top":
        for rect in result:
            rect["y"] = top
    elif mode == "bottom":
        for rect in result:
            rect["y"] = bottom - float(rect["height"])
    elif mode == "hcenter":
        centre = (left + right) / 2
        for rect in result:
            rect["x"] = centre - float(rect["width"]) / 2
    elif mode == "vcenter":
        centre = (top + bottom) / 2
        for rect in result:
            rect["y"] = centre - float(rect["height"]) / 2
    elif mode == "same_width":
        for rect in result:
            rect["width"] = key["width"]
    elif mode == "same_height":
        for rect in result:
            rect["height"] = key["height"]
    elif mode == "distribute_h" and len(result) > 2:
        ordered = sorted(enumerate(result), key=lambda pair: (float(pair[1]["x"]), pair[0]))
        first, last = ordered[0][1], ordered[-1][1]
        space = (float(last["x"]) - (float(first["x"]) + float(first["width"]))
                 - sum(float(rect["width"]) for _, rect in ordered[1:-1]))
        gap = space / (len(ordered) - 1)
        cursor = float(first["x"]) + float(first["width"]) + gap
        for _, rect in ordered[1:-1]:
            rect["x"] = cursor
            cursor += float(rect["width"]) + gap
    elif mode == "distribute_v" and len(result) > 2:
        ordered = sorted(enumerate(result), key=lambda pair: (float(pair[1]["y"]), pair[0]))
        first, last = ordered[0][1], ordered[-1][1]
        space = (float(last["y"]) - (float(first["y"]) + float(first["height"]))
                 - sum(float(rect["height"]) for _, rect in ordered[1:-1]))
        gap = space / (len(ordered) - 1)
        cursor = float(first["y"]) + float(first["height"]) + gap
        for _, rect in ordered[1:-1]:
            rect["y"] = cursor
            cursor += float(rect["height"]) + gap
    return result
