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
import math

#: The tokens a palette may hold.
PALETTE_TOKENS = ("background", "card", "border", "header", "inset", "foreground",
                  "mutedForeground", "secondary", "success", "primary")

_SAMPLE_W, _SAMPLE_H = 128, 96


def reference_content_rect(image):
    """Conservative pixel viewport for a light screen inside a dark device.

    All four dark margins must end at a predominantly light interior. Plain
    screenshots and ambiguous/dark screens retain their entire image. Coordinates
    use exclusive right/bottom edges, matching QImage.copy and crop fractions.
    """
    if image is None or image.isNull():
        return (0, 0, 0, 0)
    width, height = image.width(), image.height()
    if min(width, height) < 64:
        return (0, 0, width, height)
    from PySide6.QtCore import Qt
    small = image.scaled(240, 180, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    def light(x, y):
        c = small.pixelColor(x, y)
        return min(c.red(), c.green(), c.blue()) > 135
    # Ignore rounded corners and camera notches when measuring each edge.
    rows = [sum(light(x, y) for x in range(24, 216)) / 192 for y in range(180)]
    cols = [sum(light(x, y) for y in range(18, 162)) / 144 for x in range(240)]
    def margin(values):
        if values[1] > .15:
            return None
        for i in range(2, int(len(values) * .15)):
            if all(v > .72 for v in values[i:i + 3]):
                return i
        return None
    left, top, right, bottom = (margin(cols), margin(rows), margin(cols[::-1]), margin(rows[::-1]))
    if any(v is None for v in (left, top, right, bottom)):
        return (0, 0, width, height)
    return (round(left / 240 * width), round(top / 180 * height),
            round((240 - right) / 240 * width), round((180 - bottom) / 180 * height))


def _measured(widget):
    reference = widget.properties.get("_reference", {})
    return isinstance(reference, dict) and reference.get("layout") == "measured"


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
    left, top, right, bottom = reference_content_rect(image)
    if (left, top, right, bottom) != (0, 0, image.width(), image.height()):
        width, height = image.width(), image.height()
        exclude = [((l * width - left) / (right - left), (t * height - top) / (bottom - top),
                    (r * width - left) / (right - left), (b * height - top) / (bottom - top))
                   for l, t, r, b in exclude]
        image = image.copy(left, top, right - left, bottom - top)
    pad = 1.5 / min(_SAMPLE_W, _SAMPLE_H)
    colours = _bins(image, [(l - pad, t - pad, r + pad, b + pad) for l, t, r, b in exclude])
    if not colours:
        return {}
    neutrals = _merge([c for c in colours if c["neutral"]])
    light_surfaces = [c for c in colours if c["lum"] > .55 and not c["vivid"]]
    if sum(c["share"] for c in light_surfaces) > .55:
        # A blank white sketch is not evidence of a designed theme.
        if sum(c["share"] for c in colours if c["lum"] < .3 or c["vivid"]) < .005:
            return {}
        background = _hex(max(light_surfaces, key=lambda c: c["share"])["rgb"])
        card = mix(background, "#ffffff", .55)
        palette = {"background": background, "card": card, "border": shade(background, -.12),
                   "header": card, "inset": mix(background, "#ffffff", .25),
                   "foreground": "#172333", "mutedForeground": "#475569",
                   "secondary": shade(background, -.035)}
        for token, candidates in (
                ("success", [c for c in colours if c["vivid"] and 85 <= c["hue"] <= 160]),
                ("primary", [c for c in colours if c["vivid"] and not 85 <= c["hue"] <= 160])):
            if candidates and sum(c["share"] for c in candidates) >= .002:
                palette[token] = _hex(max(candidates, key=lambda c: c["share"])["rgb"])
        return palette
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
    trim_crops(image, project)
    align_spots(image, project)
    snap_spots(image, project)
    palette = palette_from_image(image, exclude)
    if not palette:
        return {}
    project.screen.palette = palette
    project.screen.background = palette["background"]
    project.screen.theme = "light" if _lum(_rgb(palette["background"])) > .5 else "dark"
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
            if not spot or widget.properties.get(_SPOT_FIT) or _measured(widget):
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


def _unlike(value, median, limit) -> bool:
    """True when a line of brightness `value` is not of a picture whose
    median is `median`: for a light drawing only a darker line is (its
    white background is lighter than its mid-tone median and still its
    own), for a dark one only a lighter line."""
    return value < median - limit if median >= 110 else value > median + limit


def _edge_band(means, median, limit, most):
    """How many lines from the start of `means` are of another panel: `limit`
    or more off the picture's `median`, at most `most` of them. One line
    like the picture inside the band (a bright button's row) does not end
    it; two in a row do."""
    count = 0
    while count < most:
        if not _unlike(means[count], median, limit) and not _unlike(means[count + 1], median, limit):
            break
        count += 1
    return count


def trim_crops(image, project, limit=60.0, outer=0.3) -> int:
    """Each large picture cut from the reference trimmed of the bands at its
    edges that belong to the panels around it; returns how many changed.

    A model's box for a drawing runs a few percent into its neighbours:
    Ornith's kiln drawing took in the top of the control panel under it,
    which then showed in the picture as a dark strip of buttons. A band is
    lines (rows or columns) from the edge inward whose brightness is
    `limit` or more off the picture's own, within the `outer` part.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from .compiler import BOX_MARK, CROP_FIT_MARK, CROP_MARK
    if image is None or image.isNull():
        return 0
    W, H = image.width(), image.height()
    changed = 0
    for page in project.pages:
        for widget in page.walk():
            crop = widget.properties.get(CROP_MARK)
            if widget.type not in ("Image", "ShAnimatedImage") or not crop or _measured(widget):
                continue
            l, t, r, b = crop
            if (r - l) * (b - t) < 0.08 or widget.properties.get(CROP_FIT_MARK):
                continue                    # a logo or an icon, or fitted already
            part = image.copy(int(l * W), int(t * H), max(4, int((r - l) * W)), max(4, int((b - t) * H)))
            part = part.scaled(96, 96, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)                 .convertToFormat(QImage.Format_RGB32)
            lum = [[0.0] * 96 for _ in range(96)]
            for y in range(96):
                for x in range(96):
                    p = part.pixel(x, y)
                    lum[y][x] = 0.2126 * ((p >> 16) & 255) + 0.7152 * ((p >> 8) & 255) + 0.0722 * (p & 255)
            rows = [sum(line) / 96.0 for line in lum]
            cols = [sum(lum[y][x] for y in range(96)) / 96.0 for x in range(96)]
            middle = sorted(v for line in lum[24:72] for v in line[24:72])
            median = middle[len(middle) // 2]
            most = int(96 * outer)
            cut = [_edge_band(cols, median, limit, most), _edge_band(rows, median, limit, most),
                   _edge_band(cols[::-1], median, limit, most), _edge_band(rows[::-1], median, limit, most)]
            # A line or two is antialiasing at the cut, not a panel.
            cut = [n if n >= 3 else 0 for n in cut]
            fw, fh = (r - l) / 96.0, (b - t) / 96.0
            fitted = [l + cut[0] * fw, t + cut[1] * fh, r - cut[2] * fw, b - cut[3] * fh]
            others = [tuple(w.properties[BOX_MARK]) for w in page.walk()
                      if w.properties.get(BOX_MARK) and w.properties.get(BOX_MARK) != widget.properties.get(BOX_MARK)]
            fitted = _grow(image, fitted, median, limit, others)
            if max(abs(u - v) for u, v in zip(fitted, crop)) < 0.004:
                continue
            widget.properties[CROP_MARK] = [round(v, 4) for v in fitted]
            widget.properties[CROP_FIT_MARK] = True
            changed += 1
    return changed


def _grow(image, crop, median, limit, others, reach=0.12):
    """`crop` grown outward, side by side, while the lines beyond it are of
    the picture (within `limit` of its `median` brightness), at most `reach`
    of the image and never into another block's box (`others`).

    A side grows only to an edge it finds: a light process drawing on a
    dark dashboard, whose box the model drew short (Ornith left a kiln
    drawing's left column of readings outside it), grows to its panel's
    edge; a photo as dark as the screen around it stays as cut."""
    rows, gw, gh = _luma_grid(image, (0, 0, image.width(), image.height()), most=400)
    l, t, r, b = crop
    x0, x1 = int(l * gw), min(gw - 1, int(r * gw))
    y0, y1 = int(t * gh), min(gh - 1, int(b * gh))

    def col(x):
        return sum(rows[y][x] for y in range(y0, y1 + 1)) / float(y1 - y0 + 1)

    def row(y):
        return sum(rows[y][x0:x1 + 1]) / float(x1 - x0 + 1)

    def overlap(a, o):
        return max(0.0, min(a[2], o[2]) - max(a[0], o[0])) * max(0.0, min(a[3], o[3]) - max(a[1], o[1]))

    def blocking(box):
        """The other blocks `box` would take most of (a tab bar over
        the drawing); a rail drawn a little wide only clips its edge."""
        return [o for o in others if overlap(box, o) >= 0.6 * max(1e-6, (o[2] - o[0]) * (o[3] - o[1]))
                and overlap(crop, o) < 0.3 * max(1e-6, (o[2] - o[0]) * (o[3] - o[1]))]

    def walk(start, step, stop, line, scale):
        """The last line of the picture before its panel's edge, or `start`
        when no edge is met within reach (a photo as dark as the screen
        around it would grow without end)."""
        edge, misses, at = start, 0, start
        while 0 <= at + step < stop and abs(at + step - start) <= reach * scale:
            at += step
            if not _unlike(line(at), median, limit):
                edge, misses = at, 0
            else:
                misses += 1
                if misses >= 2:
                    return edge
        return edge if at + step < 0 or at + step >= stop else start

    nl = walk(x0, -1, gw, col, gw) / float(gw)
    nr = (walk(x1, 1, gw, col, gw) + 1) / float(gw)
    nt = walk(y0, -1, gh, row, gh) / float(gh)
    nb = (walk(y1, 1, gh, row, gh) + 1) / float(gh)
    grown = [l, t, r, b]
    for side, value in ((0, nl), (1, nt), (2, nr), (3, nb)):
        trial = list(grown)
        trial[side] = min(value, grown[side]) if side < 2 else max(value, grown[side])
        hits = blocking(trial)
        if hits:
            # Up to the block in the way, no further.
            edge = (max(o[2] for o in hits), max(o[3] for o in hits),
                    min(o[0] for o in hits), min(o[1] for o in hits))[side]
            trial[side] = min(edge, grown[side]) if side < 2 else max(edge, grown[side])
            if blocking(trial):
                continue
        grown = trial
    return grown


def _luma_grid(image, rect, most=480):
    """(rows of luma 0..255, width, height) of `rect` (x, y, w, h in pixels)
    of `image`, scaled down to at most `most` pixels across."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    part = image.copy(*rect)
    if part.width() > most:
        part = part.scaledToWidth(most, Qt.SmoothTransformation)
    part = part.convertToFormat(QImage.Format_RGB32)
    w, h = part.width(), part.height()
    raw = bytes(part.constBits())[:part.bytesPerLine() * h]
    stride = part.bytesPerLine()
    rows = []
    for y in range(h):
        line = raw[y * stride:y * stride + 4 * w]
        # Format_RGB32 is B, G, R, A in memory on little-endian machines.
        rows.append([0.0722 * line[i] + 0.7152 * line[i + 1] + 0.2126 * line[i + 2]
                     for i in range(0, 4 * w, 4)])
    return rows, w, h


def printed_boxes(rows, w, h, dark=70.0) -> list:
    """The value boxes a process drawing prints: dark filled rectangles
    (a number in a black box) of a reading's size, as (x0, y0, x1, y1) in
    the grid's pixels."""
    seen = [[False] * w for _ in range(h)]
    parts = []
    for y0 in range(h):
        for x0 in range(w):
            if seen[y0][x0] or rows[y0][x0] >= dark:
                continue
            stack, count = [(x0, y0)], 0
            seen[y0][x0] = True
            lx, ly, hx, hy = x0, y0, x0, y0
            while stack:
                x, y = stack.pop()
                count += 1
                lx, ly, hx, hy = min(lx, x), min(ly, y), max(hx, x), max(hy, y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and rows[ny][nx] < dark:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if hy - ly + 1 >= 0.02 * h:
                parts.append([lx, ly, hx + 1, hy + 1, count])
    boxes = []
    for lx, ly, hx, hy, count in parts:
        bw, bh = hx - lx, hy - ly
        if not (0.025 * w <= bw <= 0.2 * w and 0.025 * h <= bh <= 0.14 * h):
            continue
        if not (1.1 <= bw / float(bh) <= 7.0) or count < 0.45 * bw * bh:
            continue
        boxes.append((lx, ly, hx, hy))
    return boxes


def _fit_axis(pairs):
    """(scale, offset) of the least-squares line through `pairs` [(a, b)],
    the scale kept within 0.7..1.4; (1, mean shift) when it cannot say."""
    n = len(pairs)
    if n == 0:
        return 1.0, 0.0
    ma = sum(a for a, _b in pairs) / n
    mb = sum(b for _a, b in pairs) / n
    var = sum((a - ma) ** 2 for a, _b in pairs)
    if n < 3 or var < 1e-6:
        return 1.0, mb - ma
    scale = sum((a - ma) * (b - mb) for a, b in pairs) / var
    scale = min(1.6, max(0.6, scale))
    return scale, mb - scale * ma


#: On a reading align_spots seated on a printed box: snap_spots leaves it
#: (grown from the box's middle it stopped at the digits, a third short).
_SPOT_FIT = "_wboxFit"

#: How far (a share of the reference's width or height) a fitted spot may
#: be from the printed box it takes.
_SPOT_REACH = 0.06


def _assign(cost):
    """Hungarian method: [(row, column)] pairing every row of the n x m
    matrix `cost` (n <= m) with its own column for the least total cost."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u, v, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1)
    owner = [0] * (m + 1)
    for i in range(1, n + 1):
        owner[0], j0 = i, 0
        least, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = owner[j0], inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                c = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if c < least[j]:
                    least[j], way[j] = c, j0
                if least[j] < delta:
                    delta, j1 = least[j], j
            for j in range(m + 1):
                if used[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    least[j] -= delta
            j0 = j1
            if owner[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            owner[j0] = owner[j1]
            j0 = j1
    return [(owner[j] - 1, j - 1) for j in range(1, m + 1) if owner[j]]


def _match(spots, centres, shift, reach):
    """[(spot, box)] one box each for the least total distance, with the
    spots moved by `shift` ((sx, ox), (sy, oy)); pairs further than `reach`
    are left out."""
    (sx, ox), (sy, oy) = shift
    placed = [(sx * x + ox, sy * y + oy) for x, y in spots]
    far = 10.0 * reach * reach + 1.0

    def d2(i, j):
        return (placed[i][0] - centres[j][0]) ** 2 + (placed[i][1] - centres[j][1]) ** 2

    flip = len(spots) > len(centres)
    rows, cols = (centres, placed) if flip else (placed, centres)
    cost = [[min(far, d2(j, i) if flip else d2(i, j)) for j in range(len(cols))] for i in range(len(rows))]
    pairs = [(j, i) if flip else (i, j) for i, j in _assign(cost)]
    return [(i, j) for i, j in pairs if d2(i, j) <= reach * reach]


#: Stretches a model's spots may be off by, per axis (Ornith measured one
#: kiln dashboard's heights on 0..768 and its drawing's on 0..1000).
_STRETCHES = (0.75, 0.85, 1.0, 1.15, 1.3, 1.45)


def _fit_spots(spots, centres):
    """((x scale, x shift), (y scale, y shift)) laying the model's `spots`
    onto the printed `centres` (both in the reference's fractions).

    A model's spots are off together, by a shift and often a stretch: for
    every stretch in _STRETCHES on each axis, every shift that puts some
    spot on some box is tried; the fit seating the most spots within 3 %
    wins (the plainer one on a tie), then is refined by least squares on
    the spots it seats."""
    tol = 0.03
    cells = {}
    for cx, cy in centres:
        cells.setdefault((int(cx / tol), int(cy / tol)), []).append((cx, cy))

    def seated(fx, fy):
        count = 0
        for x, y in spots:
            px, py = fx[0] * x + fx[1], fy[0] * y + fy[1]
            gx, gy = int(px / tol), int(py / tol)
            if any((px - cx) ** 2 + (py - cy) ** 2 <= tol * tol
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1) for cx, cy in cells.get((gx + dx, gy + dy), ())):
                count += 1
        return count

    best, best_key = ((1.0, 0.0), (1.0, 0.0)), None
    for kx in _STRETCHES:
        for ky in _STRETCHES:
            plain = abs(kx - 1.0) + abs(ky - 1.0)
            shifts = {(round(cx - kx * x, 3), round(cy - ky * y, 3)) for x, y in spots for cx, cy in centres}
            for ox, oy in shifts:
                fx, fy = (kx, ox), (ky, oy)
                # The spots, so placed, still lie over the picture.
                if not all(-0.1 <= fx[0] * x + fx[1] <= 1.1 and -0.1 <= fy[0] * y + fy[1] <= 1.1
                           for x, y in spots):
                    continue
                key = (seated(fx, fy), -plain, -abs(ox) - abs(oy))
                if best_key is None or key > best_key:
                    best, best_key = (fx, fy), key
    fit = best
    for _round in range(3):
        pairs = _match(spots, centres, fit, _SPOT_REACH)
        if len(pairs) < 4:
            break
        fx = _fit_axis([(spots[i][0], centres[j][0]) for i, j in pairs])
        fy = _fit_axis([(spots[i][1], centres[j][1]) for i, j in pairs])
        lo, hi = min(_STRETCHES) * 0.9, max(_STRETCHES) * 1.1
        if not (lo <= fx[0] <= hi and lo <= fy[0] <= hi):
            break
        fit = (fx, fy)
    return fit


def align_spots(image, project) -> int:
    """The readings laid over a process drawing moved onto the value boxes
    it prints; returns how many moved.

    A model's spots are rough and mostly off together: Ornith's kiln values
    sat a box's height or more off their printed ones, too far for
    snap_spots to find. The printed boxes are found first (printed_boxes),
    the spots are fitted onto them (_fit_spots), and each reading takes its
    own box, the readings and boxes paired for the least total distance so
    a row of five zone temperatures keeps its order."""
    from .compiler import CROP_MARK, WIDGET_BOX_MARK
    if image is None or image.isNull():
        return 0
    W, H = image.width(), image.height()
    moved = 0
    for page in project.pages:
        widgets = list(page.walk())
        for picture in widgets:
            crop = picture.properties.get(CROP_MARK)
            if picture.type not in ("Image", "ShAnimatedImage") or not crop or _measured(picture):
                continue
            l, t, r, b = crop
            if (r - l) * (b - t) < 0.08:
                continue
            spots = []
            for widget in widgets:
                spot = widget.properties.get(WIDGET_BOX_MARK)
                if not spot or widget is picture or _measured(widget):
                    continue
                mx, my = (spot[0] + spot[2]) / 2.0, (spot[1] + spot[3]) / 2.0
                if l - 0.03 <= mx <= r + 0.03 and t - 0.03 <= my <= b + 0.03:
                    spots.append((widget, mx, my))
            if len(spots) < 3:
                continue
            rows, gw, gh = _luma_grid(image, (int(l * W), int(t * H), max(4, int((r - l) * W)),
                                               max(4, int((b - t) * H))))
            # Values are printed in near-black boxes; a dark-blue heading
            # plate is not one. Lighter boxes only when there are too few.
            boxes = printed_boxes(rows, gw, gh, dark=35.0)
            if len(boxes) < 0.6 * len(spots):
                boxes = printed_boxes(rows, gw, gh, dark=70.0)
            if len(boxes) < 3:
                continue
            frames = [(l + x0 / gw * (r - l), t + y0 / gh * (b - t), l + x1 / gw * (r - l), t + y1 / gh * (b - t))
                      for x0, y0, x1, y1 in boxes]
            centres = [((f[0] + f[2]) / 2.0, (f[1] + f[3]) / 2.0) for f in frames]
            points = [(x, y) for _w, x, y in spots]
            fit = _fit_spots(points, centres)
            pairs = dict(_match(points, centres, fit, _SPOT_REACH))
            placed = [(fit[0][0] * x + fit[0][1], fit[1][0] * y + fit[1][1]) for x, y in points]
            gaps = sorted(math.hypot(placed[i][0] - centres[j][0], placed[i][1] - centres[j][1])
                          for i, j in pairs.items())
            odd = max(0.04, 3.0 * gaps[len(gaps) // 2]) if gaps else 0.0
            for i, (widget, x, y) in enumerate(spots):
                j = pairs.get(i)
                twin = any(k != i and math.hypot(x - u, y - v) < 0.015 for k, (u, v) in enumerate(points))
                if j is not None and not twin and math.hypot(placed[i][0] - centres[j][0],
                                                             placed[i][1] - centres[j][1]) <= odd:
                    widget.properties[WIDGET_BOX_MARK] = [round(v, 4) for v in frames[j]]
                    widget.properties[_SPOT_FIT] = True
                    moved += 1
                else:
                    # Two readings on one spot (Ornith put a kiln's outlet
                    # temperature and its coal feed together), one far off
                    # the fit, or none near: which printed box is its own is
                    # not known, and laid on a guess it would show its value
                    # over another's. The drawing still prints it.
                    widget.properties.pop(WIDGET_BOX_MARK, None)
    return moved
