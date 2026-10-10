"""AI Design's review pass: the screen as built, checked against its picture.

A reference run is a guess at a picture: a crop that takes in a neighbour, a
label the picture already prints drawn again beside it, a logo that is the
plant's printed name next to the name itself, a status cut to "OPERATIO".
The compiler can measure some of that (overlaps, text wider than its box,
the same words twice) but cannot see the picture; the model can, though it
is a poor judge of geometry. So the pass is both:

    layout_findings(project, page, registry)   what the layout measures
    review_prompt() / review_brief(...)       the model is shown the
                                               reference, the render and
                                               the findings, and answers
                                               with fixes (REVIEW_SCHEMA)
    parse_review(text)                         the fixes from its reply
    apply_review(project, fixes, registry)     the fixes it may make: remove
                                               unbound decoration, re-crop a
                                               picture, set a declared
                                               property; then a recompile

The AI tab keeps a reviewed design only when its findings did not grow.
"""
from __future__ import annotations

import json
import re

#: The reply the review asks for (structured output).
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {"type": "array", "items": {"type": "string"}},
        "fixes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["remove", "crop", "set"]},
                "id": {"type": "string"},
                "crop": {"type": "array", "items": {"type": "number"}},
                "property": {"type": "string"},
                "value": {},
            },
            "required": ["op", "id"],
        }},
    },
    "required": ["issues", "fixes"],
}

#: Review rounds after a reference run, at most.
MAX_ROUNDS = 2

_PICTURES = ("Image", "ShAnimatedImage")
#: What the review may remove: words and pictures, never a reading, a lamp, a
#: button or a dial (a plan's buttons carry empty actions and its readings
#: often no binding yet, so "unbound" does not tell decoration apart).
_DECORATION = ("Text", "Rectangle") + _PICTURES
_SHOWN = ("text", "label", "title", "caption", "value")


def _walk(widgets, ox=0.0, oy=0.0, parent=None):
    for widget in widgets:
        g = widget.geometry
        x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
        yield widget, (x, y, float(g.get("width", 0)), float(g.get("height", 0))), parent
        yield from _walk(widget.children, x, y, widget)


def _chrome(widget) -> bool:
    from designer.layout.compiler import CHROME_MARK
    return bool(widget.properties.get(CHROME_MARK))


def _words(widget) -> str:
    """What the widget prints, for the brief and for spotting it twice."""
    props = widget.properties
    return " ".join(str(props[k]) for k in _SHOWN if props.get(k) not in (None, "")).strip()


def _text_need(widget) -> float:
    """About how wide the widget's words are drawn, or 0 when it does not
    print a line of text the layout sizes."""
    props = widget.properties
    if widget.type == "Text":
        lines = str(props.get("text") or "").split("\n")
        size = float(props.get("fontSize") or 14)
        return max(len(line) for line in lines) * size * (0.66 if props.get("bold") else 0.58)
    if widget.type == "ShAnnunciator":
        return len(str(props.get("text") or "")) * 12 * 0.62 + 16
    if widget.type == "ShButton":
        return len(str(props.get("text") or "")) * 14 * 0.58 + 16
    if widget.type == "ShDataField" and props.get("stacked") is False:
        value = str(props.get("value", "") or "") + str(props.get("units", "") or "")
        return len(str(props.get("label") or "")) * 12 * 0.6 + 8 + len(value) * 14 * 0.62
    return 0.0


def layout_findings(project, page=None, registry=None) -> list:
    """What the layout itself can tell is wrong: [{"kind", "ids", "message"}].

    kinds: "overlap" (two widgets drawn over each other), "clipped" (words
    wider than their box), "twice" (two widgets printing the same words).
    """
    page = page or project.pages[0]
    items = [(w, r, p) for w, r, p in _walk(page.widgets)]
    leaves = [(w, r) for w, r, _p in items if not w.children and not _chrome(w)
              and r[2] > 1 and r[3] > 1]
    found = []
    for i, (a, ra) in enumerate(leaves):
        for b, rb in leaves[i + 1:]:
            ix = min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0])
            iy = min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1])
            if ix <= 2 or iy <= 2:
                continue
            small = min(ra[2] * ra[3], rb[2] * rb[3])
            if ix * iy >= max(40.0, 0.08 * small):
                found.append({"kind": "overlap", "ids": [a.id, b.id],
                              "message": f"{a.id} and {b.id} overlap ({int(ix)}x{int(iy)} px)"})
    for widget, r, _p in items:
        need = _text_need(widget)
        if need and need > r[2] + 6:
            props = [k for k in ("text", "label", "value") if widget.properties.get(k) not in (None, "")]
            found.append({"kind": "clipped", "ids": [widget.id],
                          "message": f"{widget.id}: its words ({', '.join(props)}) need about "
                                     f"{int(need)} px, it has {int(r[2])}"})
    seen = {}
    for widget, _r, _p in items:
        words = re.sub(r"[^a-z0-9]+", " ", _words(widget).lower()).strip()
        if len(words) < 4 or widget.type in ("ShProcessValue",):
            continue
        if words in seen and seen[words] is not widget:
            found.append({"kind": "twice", "ids": [seen[words].id, widget.id],
                          "message": f"{seen[words].id} and {widget.id} both print \"{_words(widget)}\""})
        else:
            seen[words] = widget
    return found


def review_prompt() -> str:
    """The review's system prompt."""
    return (
        "You review an embedded HMI screen against the reference picture it was made from. "
        "Image 1 is the reference. Image 2 is the screen as built. Find what is wrong in image 2 "
        "compared with image 1, and fix only that:\n"
        "- words drawn twice: a picture cut from the reference that already shows words (a "
        "logo that is really the printed plant name, a drawing with its labels) next to a "
        "widget printing the same words. In the top strip remove the picture; elsewhere "
        "remove the widget.\n"
        "- labels drawn over, beside or under a picture that the picture itself prints: "
        "remove them.\n"
        "- a picture whose crop shows parts of other blocks (a card, the top strip, the "
        "banner): give its crop around that picture alone, tighter than before.\n"
        "- text cut off: shorten it with \"set\" (\"STATUS: ONLINE\"), never by removing it.\n"
        "The measured findings below are facts about image 2; use them.\n"
        "Never remove a reading, a button, a dial or the main picture. Ids from the list only. "
        "When nothing is wrong, answer with no fixes.\n"
        'Reply as JSON: {"issues": ["<one line each>"], "fixes": [{"op": "remove", "id": "<id>"}, '
        '{"op": "crop", "id": "<picture id>", "crop": [left, top, right, bottom]}, '
        '{"op": "set", "id": "<id>", "property": "<name>", "value": <value>}]}. Crops are on a '
        "0..1000 scale of image 1's width and height.")


def strip_pictures(project, page=None) -> list:
    """The pictures in the top strip cut from the reference (logos), at most
    two: the review is shown each one as cut, since judged from the whole
    screenshot Ornith found the logo that was really the plant's printed
    name in one run and missed it in the next."""
    from designer.layout.compiler import CROP_MARK, SECTION_MARK
    page = page or project.pages[0]
    return [w for w, _r, _p in _walk(page.widgets) if w.type in _PICTURES
            and w.properties.get(CROP_MARK)
            and str(w.properties.get(SECTION_MARK) or "").endswith("|header")][:2]


def cut_images(reference, pictures) -> list:
    """Each picture's crop of the reference (a BriefImage) as a BriefImage."""
    import base64
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage
    from designer.layout.compiler import CROP_MARK
    from tools.hmi_deployer.ai_design import encode_brief_image
    image = QImage.fromData(base64.b64decode(reference.data))
    out = []
    for widget in pictures:
        l, t, r, b = widget.properties[CROP_MARK]
        rect = QRect(int(l * image.width()), int(t * image.height()),
                     max(1, int((r - l) * image.width())), max(1, int((b - t) * image.height())))
        out.append(encode_brief_image(image.copy(rect), f"{widget.id}.png"))
    return out


def review_brief(project, page=None, findings=None, shown=()) -> str:
    """The review's user message: the widgets (id, type, box, words, crop)
    and the measured findings. `shown`: the strip pictures sent as images 3
    and on (strip_pictures), each asked about by name."""
    from designer.layout.compiler import CROP_MARK
    page = page or project.pages[0]
    lines = []
    for widget, r, _p in _walk(page.widgets):
        if _chrome(widget) or widget.children:
            continue
        line = f"- {widget.id} ({widget.type}) at x={int(r[0])} y={int(r[1])} w={int(r[2])} h={int(r[3])}"
        words = _words(widget)
        if words:
            line += " prints " + json.dumps(words, ensure_ascii=False)
        crop = widget.properties.get(CROP_MARK)
        if crop:
            line += " cut from the reference at " + json.dumps([int(round(v * 1000)) for v in crop])
        if widget.bindings:
            line += " (live)"
        lines.append(line)
    text = (f"The screen is {project.screen.width}x{project.screen.height}. Widgets:\n"
            + "\n".join(lines))
    findings = findings if findings is not None else layout_findings(project, page)
    if findings:
        text += "\n\nMeasured findings:\n" + "\n".join("- " + f["message"] for f in findings)
    for number, widget in enumerate(shown, 3):
        text += (f"\n\nImage {number} is picture {widget.id} as cut. Is it a logo mark, or words "
                 "(a name, a title)? If it shows words that a Text in the list also prints, remove "
                 f"{widget.id}.")
    return text


def parse_review(text: str) -> list:
    """The fixes in a review reply ([] when there are none or it is not JSON)."""
    if not text:
        return []
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        try:
            from designer.layout.intake import loads_lenient as loads
            data = loads(text[start:end + 1])
        except Exception:
            return []
    fixes = data.get("fixes") if isinstance(data, dict) else None
    return [f for f in fixes or [] if isinstance(f, dict) and f.get("op") and f.get("id")]


def apply_review(project, fixes, registry, page=None, findings=None) -> list:
    """Apply the fixes the review may make, in place; returns the ones made,
    as one line each. The page is recompiled when any was.

    remove: an unbound, actionless widget that is not the page's main
    picture -- a picture (a logo that is printed words: the model sees what
    a picture shows), or a widget a measured finding names (an overlap, the
    same words twice). Left to judge text by eye, Ornith removed the plant's
    name once the logo beside it had gone. crop: a picture cut from the
    reference, re-cut on Apply (its source is cleared). set: a property the
    widget's type declares, never a geometry or a compiler mark.
    """
    from designer.layout.compiler import CROP_MARK, compile_page, crop_of
    page = page or project.pages[0]
    findings = findings if findings is not None else layout_findings(project, page, registry)
    named = {wid for f in findings if f["kind"] in ("overlap", "twice") for wid in f["ids"]}
    widgets = {w.id: (w, r, p) for w, r, p in _walk(page.widgets)}
    pictures = sorted((r[2] * r[3], w.id) for w, r, _p in widgets.values() if w.type in _PICTURES)
    main_picture = pictures[-1][1] if pictures else None
    made = []
    for fix in fixes:
        op, wid = str(fix.get("op")), str(fix.get("id"))
        if wid not in widgets:
            continue
        widget, _r, parent = widgets[wid]
        if _chrome(widget):
            continue
        if op == "remove":
            if widget.type not in _DECORATION or widget.bindings or widget.actions \
                    or wid == main_picture or widget.children:
                continue
            if widget.type not in _PICTURES and wid not in named:
                continue
            siblings = parent.children if parent is not None else page.widgets
            if widget in siblings:
                siblings.remove(widget)
                made.append(f"removed {wid}")
        elif op == "crop" and widget.type in _PICTURES and widget.properties.get(CROP_MARK):
            crop = crop_of(fix.get("crop"))
            if crop and crop != widget.properties.get(CROP_MARK):
                widget.properties[CROP_MARK] = crop
                widget.properties["source"] = ""
                made.append(f"re-cropped {wid}")
        elif op == "set":
            prop = str(fix.get("property") or "")
            definition = registry.get(widget.type) if registry is not None else None
            value = fix.get("value")
            if definition is None or prop.startswith("_") or prop not in definition.properties \
                    or prop in ("x", "y", "width", "height") or isinstance(value, (dict, list)):
                continue
            if widget.properties.get(prop) != value:
                widget.properties[prop] = value
                made.append(f"set {wid}.{prop}")
    if made:
        compile_page(project, page, registry)
    return made
