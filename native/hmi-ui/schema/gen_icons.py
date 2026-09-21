"""Rasterise the kit's Tabler icons for the C runtime.

    python native/hmi-ui/schema/gen_icons.py          # writes ui/qml/Shadcn/icons/<name>.png
    python native/hmi-ui/schema/gen_icons.py --check  # exit 1 if any icon is missing/stale

ui/qml/Shadcn/TablerIcons.js holds every icon as an SVG document (ShIcon.qml
inlines them as data: URLs). LVGL has no SVG renderer in this build, so each
icon is rendered once, white on transparent, at ICON_PX, with Qt's SVG
renderer -- the same rasteriser the Studio uses -- and the runtime scales
and recolours the PNG (src/icons.c). The directory travels with the kit
(deploy/provision_panel.py copies ui/qml).
"""
import hashlib
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
JS = os.path.join(REPO, "ui", "qml", "Shadcn", "TablerIcons.js")
OUT = os.path.join(REPO, "ui", "qml", "Shadcn", "icons")
ICON_PX = 96


def icons():
    text = open(JS, encoding="utf-8").read()
    for m in re.finditer(r'^\s*"([a-z0-9-]+)":\s*"(<svg.*?</svg>)",?\s*$', text, re.M):
        yield m.group(1), m.group(2).replace("currentColor", "#ffffff")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication([])
    check = "--check" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    stale, n = [], 0
    for name, svg in icons():
        n += 1
        path = os.path.join(OUT, f"{name}.png")
        digest = hashlib.sha1(svg.encode()).hexdigest()[:12]
        stamp = os.path.join(OUT, f".{name}.sha")
        if os.path.exists(path) and os.path.exists(stamp) and open(stamp).read().strip() == digest:
            continue
        if check:
            stale.append(name)
            continue
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        img = QImage(ICON_PX, ICON_PX, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p)
        p.end()
        img.save(path)
        open(stamp, "w").write(digest + "\n")
    if check:
        for s in stale:
            print("stale:", s)
        print(f"{n} icons, {len(stale)} stale")
        return 1 if stale else 0
    print(f"wrote {n} icons to {os.path.relpath(OUT, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
