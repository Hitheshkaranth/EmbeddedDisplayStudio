"""A reference picture's colours, as the theme tokens a design is drawn with.

A design followed from a picture took the kit's own dark theme: near-black
cards, blue buttons, a grey nothing like the picture's. The picture's
colours are the cheapest part of its look to copy and the most visible, so
they are sampled from it (outside the parts cut into the design as
pictures, whose oranges would win every count) and stored on the screen as
`palette`: {token: "#rrggbb"}. style.theme_colour reads it before the kit's
tokens, so every card, strip and heading the compiler draws takes it, and
apply_palette gives the kit widgets that draw their own colours (value
boxes, buttons, lamps) theirs.

    palette_from_image(qimage, exclude=[(l, t, r, b), ...]) -> {token: hex}

Tokens: background, card, border, header (a card's title band), inset (a
value box), foreground, mutedForeground, secondary (a button), success (the
picture's signal green), and primary when the picture has a strong accent.
No numpy: a 128x96 copy is counted pixel by pixel.
"""
from __future__ import annotations

import colorsys

#: The tokens a palette may hold.
PALETTE_TOKENS = ("background", "card", "border", "header", "inset", "foreground",
                  "mutedForeground", "secondary", "success", "primary")

_SAMPLE_W, _SAMPLE_H = 128, 96


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _rgb(colour: str):
    value = colour.lstrip("#")[-6:]
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb) -> float:
    """Relative luminance (WCAG), 0..1."""
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two hex colours."""
    la, lb = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def shade(colour: str, amount: float) -> str:
    """The colour lighter (amount > 0) or darker by `amount` of HLS lightness."""
    r, g, b = (c / 255.0 for c in _rgb(colour))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l + amount))
    return _hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, s)))


def mix(a: str, b: str, t: float) -> str:
    """`a` moved towards `b` by t (0..1)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def _bins(image, exclude):
    """{bin: [count, r, g, b]} over the picture outside `exclude`."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    small = image.scaled(_SAMPLE_W, _SAMPLE_H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
        .convertToFormat(QImage.Format_RGB32)
    bins = {}
    total = 0
    for y in range(small.height()):
        fy = (y + 0.5) / small.height()
        for x in range(small.width()):
            fx = (x + 0.5) / small.width()
            if any(l <= fx <= r and t <= fy <= b for l, t, r, b in exclude):
                continue
            pixel = small.pixel(x, y)
            r, g, b = (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255
            key = (r // 10, g // 10, b // 10)
            entry = bins.setdefault(key, [0, 0, 0, 0])
            entry[0] += 1
            entry[1] += r
            entry[2] += g
            entry[3] += b
            total += 1
    colours = []
    for count, r, g, b in bins.values():
        rgb = (r / count, g / count, b / count)
        h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in rgb))
        spread = max(rgb) - min(rgb)
        colours.append({"rgb": rgb, "count": count, "share": count / max(1, total),
                        "lum": _lum(rgb), "hue": h * 360.0, "light": l,
                        "neutral": spread < 26, "vivid": spread > 90 and max(rgb) > 160})
    return colours


def _merge(colours, near=0.012):
    """Neutral colours of about one luminance counted together, so a grey
    that dithers over three bins is still the picture's most common grey."""
    groups = []
    for colour in sorted(colours, key=lambda c: c["lum"]):
        if groups and abs(groups[-1]["lum"] - colour["lum"]) <= near:
            group = groups[-1]
            total = group["count"] + colour["count"]
            group["rgb"] = tuple((a * group["count"] + b * colour["count"]) / total
                                 for a, b in zip(group["rgb"], colour["rgb"]))
            group["count"] = total
            group["share"] += colour["share"]
            group["lum"] = _lum(group["rgb"])
        else:
            groups.append(dict(colour))
    return groups


def palette_from_image(image, exclude=()) -> dict:
    """The picture's colours as theme tokens; {} when it is too small or too
    plain to say (a sketch on white keeps the kit's theme)."""
    if image is None or image.isNull() or image.width() < 32 or image.height() < 32:
        return {}
    # A little past each excluded box: the copy's edge pixels blend it with
    # its surroundings (a furnace's orange came back as a brown accent).
    pad = 1.5 / min(_SAMPLE_W, _SAMPLE_H)
    colours = _bins(image, [(l - pad, t - pad, r + pad, b + pad) for l, t, r, b in exclude])
    if not colours:
        return {}
    neutrals = _merge([c for c in colours if c["neutral"]])
    dark = sorted((c for c in neutrals if c["lum"] < 0.12 and c["share"] >= 0.01),
                  key=lambda c: -c["share"])
    if not dark:
        return {}          # a light picture: the kit's light theme is the better guess
    top = sorted(dark[:2], key=lambda c: c["lum"])
    background = _hex(top[0]["rgb"])
    card = _hex(top[1]["rgb"]) if len(top) > 1 and top[1]["lum"] - top[0]["lum"] > 0.004 \
        else shade(background, 0.035)
    card_lum = _lum(_rgb(card))
    bands = [c for c in neutrals if card_lum + 0.015 < c["lum"] < card_lum + 0.16 and c["share"] >= 0.004]
    header = _hex(max(bands, key=lambda c: c["share"])["rgb"]) if bands else shade(card, 0.06)
    insets = [c for c in neutrals if c["lum"] < _lum(_rgb(background)) * 0.6 and c["share"] >= 0.003]
    inset = _hex(min(insets, key=lambda c: c["lum"])["rgb"]) if insets else shade(background, -0.06)
    lights = [c for c in neutrals if c["lum"] > 0.6 and c["share"] >= 0.002]
    foreground = _hex(max(lights, key=lambda c: c["share"])["rgb"]) if lights else "#ececec"
    if contrast(foreground, card) < 7.0:
        foreground = "#f2f4f5"
    palette = {
        "background": background,
        "card": card,
        "border": shade(card, 0.09),
        "header": header,
        "inset": inset,
        "foreground": foreground,
        "mutedForeground": mix(foreground, card, 0.38),
        "secondary": mix(card, header, 0.6),
    }
    vivid = [c for c in colours if c["vivid"]]
    greens = [c for c in vivid if 85 <= c["hue"] <= 160]
    if greens and sum(c["share"] for c in greens) >= 0.002:
        palette["success"] = _hex(max(greens, key=lambda c: c["share"])["rgb"])
    accents = [c for c in vivid if not 85 <= c["hue"] <= 160]
    if accents:
        best = max(accents, key=lambda c: c["share"])
        if best["share"] >= 0.01:
            palette["primary"] = _hex(best["rgb"])
    return palette


def apply_reference_palette(project, references, registry=None) -> dict:
    """Take the first reference picture's palette for `project` and lay its
    planned pages out again in it; returns the palette ({} when the picture
    gives none, and the project is left as it was)."""
    import base64
    from PySide6.QtGui import QImage
    from .compiler import CROP_MARK, compile_page, is_planned
    if not references:
        return {}
    try:
        image = QImage.fromData(base64.b64decode(references[0].data))
    except Exception:
        return {}
    # The parts cut into the design as pictures are not its chrome: a
    # furnace's flames would make the whole screen orange.
    exclude = [tuple(w.properties[CROP_MARK]) for page in project.pages for w in page.walk()
               if w.properties.get(CROP_MARK)]
    snap_spots(image, project)
    palette = palette_from_image(image, exclude)
    if not palette:
        return {}
    project.screen.palette = palette
    project.screen.background = palette["background"]
    for page in project.pages:
        if is_planned(page):
            compile_page(project, page, registry)
    return palette


def snap_spots(image, project) -> int:
    """Each reading laid over a picture moved onto the value box the picture
    prints for it; returns how many moved.

    A model places a drawing's live values a few percent off (a kiln's zone
    temperatures sat half a box above their printed ones, both showing). In
    a process picture a value is printed in a dark box, so the darkest box
    around the model's spot is the one: grown from the spot's middle while
    the rows and columns it takes in are mostly dark.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from .compiler import WIDGET_BOX_MARK
    if image is None or image.isNull():
        return 0
    W, H = image.width(), image.height()
    moved = 0
    for page in project.pages:
        for widget in page.walk():
            spot = widget.properties.get(WIDGET_BOX_MARK)
            if not spot:
                continue
            l, t, r, b = spot
            bw, bh = (r - l), (b - t)
            # The window: the spot and as much again around it.
            wl, wt = max(0.0, l - bw), max(0.0, t - bh)
            wr, wb = min(1.0, r + bw), min(1.0, b + bh)
            px, py = int(wl * W), int(wt * H)
            pw, ph = max(4, int((wr - wl) * W)), max(4, int((wb - wt) * H))
            window = image.copy(px, py, pw, ph)
            scale = min(1.0, 120.0 / max(pw, ph))
            if scale < 1.0:
                window = window.scaled(max(4, int(pw * scale)), max(4, int(ph * scale)),
                                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            window = window.convertToFormat(QImage.Format_RGB32)
            cw, ch = window.width(), window.height()
            lum = [[0.0] * cw for _ in range(ch)]
            values = []
            for y in range(ch):
                for x in range(cw):
                    p = window.pixel(x, y)
                    v = 0.2126 * ((p >> 16) & 255) + 0.7152 * ((p >> 8) & 255) + 0.0722 * (p & 255)
                    lum[y][x] = v
                    values.append(v)
            values.sort()
            median = values[len(values) // 2]
            limit = min(70.0, median * 0.6)
            dark = [[lum[y][x] < limit for x in range(cw)] for y in range(ch)]
            cx = int((((l + r) / 2.0) - wl) / max(1e-6, wr - wl) * cw)
            cy = int((((t + b) / 2.0) - wt) / max(1e-6, wb - wt) * ch)
            cx, cy = min(max(cx, 0), cw - 1), min(max(cy, 0), ch - 1)
            x0, x1, y0, y1 = cx, cx, cy, cy

            def share_col(x):
                return sum(dark[y][x] for y in range(y0, y1 + 1)) / float(y1 - y0 + 1)

            def share_row(y):
                return sum(dark[y][x] for x in range(x0, x1 + 1)) / float(x1 - x0 + 1)

            grown = True
            while grown:
                grown = False
                if x0 > 0 and share_col(x0 - 1) > 0.55:
                    x0 -= 1
                    grown = True
                if x1 < cw - 1 and share_col(x1 + 1) > 0.55:
                    x1 += 1
                    grown = True
                if y0 > 0 and share_row(y0 - 1) > 0.55:
                    y0 -= 1
                    grown = True
                if y1 < ch - 1 and share_row(y1 + 1) > 0.55:
                    y1 += 1
                    grown = True
            fw = (x1 - x0 + 1) / float(cw) * (wr - wl)
            fh = (y1 - y0 + 1) / float(ch) * (wb - wt)
            if not (0.35 * bw <= fw <= 2.5 * bw and 0.35 * bh <= fh <= 2.5 * bh):
                continue            # no box of the reading's size there: keep the model's
            nl = wl + x0 / float(cw) * (wr - wl)
            nt = wt + y0 / float(ch) * (wb - wt)
            widget.properties[WIDGET_BOX_MARK] = [round(nl, 4), round(nt, 4),
                                                  round(nl + fw, 4), round(nt + fh, 4)]
            moved += 1
    return moved
