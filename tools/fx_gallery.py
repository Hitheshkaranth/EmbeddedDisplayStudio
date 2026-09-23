"""tools/fx_gallery.py -- render every ui.python.fx effect into one PNG sheet.

    python tools/fx_gallery.py [out.png] [--only beam,orb,...]

Each effect gets a row per theme (dark, light) with frames at a few moments,
on the Studio's own background colour, so the ports can be judged by eye
against the Libraries.dev originals. Effects whose module is not written yet
show "not implemented". Runs offscreen.
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel  # noqa: E402

BG = {"dark": QColor("#09090b"), "light": QColor("#ffffff")}
CARD = {"dark": QColor("#18181b"), "light": QColor("#f4f4f5")}
FG = {"dark": QColor("#ecedee"), "light": QColor("#020817")}
TIMES = (0.2, 0.9, 1.7, 2.6)


def _drive(widget, seconds, step=1 / 30, base=1000.0):
    t = base
    while t < base + seconds:
        t += step
        widget._tick(t)
    return t


def _card_under(painter, rect, theme, radius=16):
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(CARD[theme])
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def cell_beam(size, variant):
    def draw(painter, rect, theme, t):
        from ui.python.fx.beam import BorderBeam
        host = QFrame()
        host.resize(int(rect.width()), int(rect.height()))
        beam = BorderBeam(host, size=size, variant=variant)
        beam.set_theme(theme)
        beam.set_active(True)
        end = _drive(beam, 1.5 + t)
        _card_under(painter, rect, theme, 32 if size == "sm" else 16)
        painter.drawImage(rect.topLeft(), beam.render_at(end))
    return draw


def cell_glow(painter, rect, theme, t):
    from ui.python.fx.glow import WorkingGlow
    glow = WorkingGlow(height=10)
    glow.resize(int(rect.width()), 10)
    glow.set_theme(theme)
    glow.start()
    end = _drive(glow, 0.8 + t)
    _card_under(painter, rect, theme, 10)
    painter.drawImage(int(rect.left()), int(rect.bottom() - 12), glow.render_at(end))


def cell_orb(state, size):
    def draw(painter, rect, theme, t):
        from ui.python.fx.orb import ThinkingOrb
        orb = ThinkingOrb(state=state, size=size)
        orb.set_theme(theme)
        image = orb.render_at(1000.0 + t)
        painter.drawImage(int(rect.center().x() - size / 2), int(rect.center().y() - size / 2), image)
    return draw


def cell_avatar(shape, state):
    def draw(painter, rect, theme, t):
        from ui.python.fx.avatar import BotAvatar
        avatar = BotAvatar(shape=shape, size=72, state=state, seed=0.4)
        avatar.set_theme(theme)
        end = _drive(avatar, 1.0 + t, step=1 / 60)
        painter.drawImage(int(rect.center().x() - 36), int(rect.center().y() - 36), avatar.render_at(end))
    return draw


def cell_metal(preset):
    def draw(painter, rect, theme, t):
        from ui.python.fx.metal import paint_metal
        path = QPainterPath()
        pill = QRectF(rect.left() + 10, rect.center().y() - 20, rect.width() - 20, 40)
        path.addRoundedRect(pill, 20, 20)
        paint_metal(painter, path, 1000.0 + t, preset=preset, theme=theme)
    return draw


def cell_ring(painter, rect, theme, t):
    from ui.python.fx.metal import MetalRing
    label = QLabel("ED")
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(f"color: {FG[theme].name()}; font-weight: 700;")
    ring = MetalRing(label)
    ring.set_theme(theme)
    ring.resize(56, 56)
    ring.show()
    image = ring.render_at(1000.0 + t)
    painter.drawImage(int(rect.center().x() - 28), int(rect.center().y() - 28), image)
    ring.hide()


def cell_mosaic(phase):
    def draw(painter, rect, theme, t):
        from ui.python.fx.mosaic import MosaicView
        view = MosaicView()
        view.resize(int(rect.width()), int(rect.height()))
        view.set_theme(theme)
        view.set_loading()
        end = _drive(view, 0.4 + t, step=1 / 15)
        if phase == "reveal":
            image = QImage(160, 100, QImage.Format_ARGB32)
            image.fill(QColor("#1f6feb"))
            p = QPainter(image)
            p.setPen(QColor("#ffffff"))
            p.setFont(QFont("Segoe UI", 20, QFont.Bold))
            p.drawText(image.rect(), Qt.AlignCenter, "preview")
            p.end()
            view.set_image(image)
            end = _drive(view, 0.3 + t * 0.8, step=1 / 15, base=end)
        painter.drawImage(rect.topLeft(), view.render_at(end))
    return draw


def cell_liquid(painter, rect, theme, t):
    from ui.python.fx.liquid import LiquidTabBar
    from ui.python.fx import FxClock
    bar = LiquidTabBar()
    for name in ("Designer", "AI Design", "Code", "Console"):
        bar.addTab(name)
    bar.set_theme(theme)
    bar.resize(int(rect.width()), 36)
    bar.show()
    bar.setCurrentIndex(3)
    clock_t = 1000.0
    for _ in range(int(t * 60)):
        clock_t += 1 / 60
        entry = FxClock.instance()._subs.get(id(bar))
        if entry is None:
            break
        entry[1](clock_t)
    painter.drawImage(int(rect.left()), int(rect.center().y() - 18), bar.grab().toImage())
    bar.hide()


ROWS = [
    ("beam md colorful", "beam", cell_beam("md", "colorful"), 300, 150),
    ("beam sm ocean", "beam", cell_beam("sm", "ocean"), 200, 64),
    ("beam line sunset", "beam", cell_beam("line", "sunset"), 300, 110),
    ("working glow", "glow", cell_glow, 300, 60),
    ("orb breathing 32", "orb", cell_orb("breathing", 32), 80, 80),
    ("orb working 64", "orb", cell_orb("working", 64), 80, 80),
    ("orb connecting 64", "orb", cell_orb("connecting", 64), 80, 80),
    ("orb shaping 20", "orb", cell_orb("shaping", 20), 80, 80),
    ("avatar clover", "avatar", cell_avatar("clover", "default"), 90, 90),
    ("avatar droid working", "avatar", cell_avatar("droid", "working"), 90, 90),
    ("avatar blob sleeping", "avatar", cell_avatar("blob", "sleeping"), 90, 90),
    ("metal chromatic", "metal", cell_metal("chromatic"), 200, 70),
    ("metal gold", "metal", cell_metal("gold"), 200, 70),
    ("metal ring", "metal", cell_ring, 80, 80),
    ("mosaic loading", "mosaic", cell_mosaic("loading"), 240, 150),
    ("mosaic reveal", "mosaic", cell_mosaic("reveal"), 240, 150),
    ("liquid tabs", "liquid", cell_liquid, 380, 60),
]


def main(argv):
    out = next((a for a in argv if a.endswith(".png")), "fx_gallery.png")
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    app = QApplication.instance() or QApplication(sys.argv)
    rows = [r for r in ROWS if only is None or r[1] in only]
    label_w, pad = 170, 12
    width = label_w + max(len(TIMES) * (w + pad) for _n, _m, _f, w, _h in rows) + pad
    height = sum(2 * (h + pad) for *_r, h in rows) + pad
    sheet = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor("#27272a"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.Antialiasing)
    y = pad
    failures = []
    for name, module, draw, w, h in rows:
        for theme in ("dark", "light"):
            painter.fillRect(QRectF(0, y - pad / 2, width, h + pad), BG[theme])
            painter.setPen(FG[theme])
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(QRectF(8, y, label_w - 12, h), Qt.AlignVCenter | Qt.TextWordWrap,
                             f"{name}\n{theme}")
            for i, t in enumerate(TIMES):
                rect = QRectF(label_w + i * (w + pad), y, w, h)
                painter.save()
                try:
                    draw(painter, rect, theme, t)
                except NotImplementedError:
                    painter.setPen(QColor("#71717a"))
                    painter.drawText(rect, Qt.AlignCenter, "not implemented")
                except Exception:
                    failures.append((name, theme, traceback.format_exc(limit=3)))
                    painter.setPen(QColor("#ef4444"))
                    painter.drawText(rect, Qt.AlignCenter, "error")
                painter.restore()
            y += h + pad
    painter.end()
    sheet.save(out)
    print(f"saved {out} ({width}x{height})")
    for name, theme, tb in failures:
        print(f"--- {name} [{theme}]\n{tb}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
