"""Canvas painter for ShStationLine -- mirrors ui/qml/Shadcn/ShStationLine.qml at rest.

A vertical route timeline: stations at even steps from 0.09 h to 0.84 h on a
4 px line at x = 0.14 w (grey above the current station, accent from it down,
a faint stub above the first node); passed stations a grey dot and dim text,
the current one a glowing accent ring holding the train icon, the ones ahead
an accent dot, the terminus a hollow accent ring. Same geometry as
native/hmi-ui/src/widgets/w_shstationline.c.
"""
import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen

from designer.canvas.widget_previews import WEIGHT_SEMIBOLD, _number, _prop

MAX_STATIONS = 8
_ICON_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "ui", "qml", "Shadcn", "icons", "train.png")
_icon_cache = {}

GREY_LINE = "#3f3f46"
GREY_DOT = "#52525b"
DIM = "#71717a"
MUTED = "#a1a1aa"
WHITE = "#fafafa"
DARK = "#18181b"


def _split(value, keep_empty):
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = str(value if value is not None else "").split(",")
    parts = [p.strip() for p in parts]
    if not keep_empty:
        parts = [p for p in parts if p]
    return parts[:MAX_STATIONS]


def _train_icon(size, color):
    key = (size, color)
    if key not in _icon_cache:
        src = QImage(os.path.normpath(_ICON_PATH))
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        if not src.isNull():
            p = QPainter(img)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRectF(0, 0, size, size), src)
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(img.rect(), QColor(color))
            p.end()
        _icon_cache[key] = img
    return _icon_cache[key]


def _wrap(metrics, text, width, max_lines=2):
    """Word-wrap to at most max_lines, eliding the last (Text.WordWrap + maximumLineCount)."""
    words = text.split()
    lines, line = [], ""
    for i, word in enumerate(words):
        trial = f"{line} {word}" if line else word
        if metrics.horizontalAdvance(trial) <= width or not line:
            line = trial
            continue
        lines.append(line)
        line = word
        if len(lines) == max_lines - 1:
            rest = " ".join([word] + words[i + 1:])
            lines.append(metrics.elidedText(rest, Qt.ElideRight, int(width)))
            return lines
    if line:
        lines.append(metrics.elidedText(line, Qt.ElideRight, int(width)))
    return lines or [""]


def _circle(painter, cx, cy, r, fill, opacity=1.0, border=0, border_color=None):
    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.setBrush(QColor(fill))
    if border:
        painter.setPen(QPen(QColor(border_color), border))
        half = border / 2.0
        painter.drawEllipse(QRectF(cx - r + half, cy - r + half, 2 * r - border, 2 * r - border))
    else:
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    painter.restore()


def paint(painter, rect, props, ctx):
    names = _split(_prop(props, "stations", "Attiguppe,Vijayanagar,Hosahalli,Magadi Road,KSR Bengaluru"), False)
    subs = _split(props.get("details", "COMPLETED,P-412,NEXT · 1.1 km,UPCOMING · 2.3 km,Majestic"), True)
    current = int(round(_number(props, "current", 1)))
    accent = QColor(str(_prop(props, "accent", "#a855f7")))
    if not accent.isValid():
        accent = QColor("#a855f7")
    n = len(names)
    if n == 0:
        return
    last = n - 1

    W, H = max(1.0, rect.width()), max(1.0, rect.height())
    ox, oy = rect.left(), rect.top()
    k = min(W / 520.0, H / 680.0)
    line_x = round(W * 0.14)
    line_w = max(2, round(4 * k))
    top, bottom = round(H * 0.09), round(H * 0.84)
    text_x = round(W * 0.24)
    text_w = max(10, round(W - text_x - W * 0.04))
    name_fs, sub_fs = max(8, round(34 * k)), max(7, round(22 * k))
    name_line_h = round(name_fs * 1.21)
    gap = round(2 * k)
    dot_r, ring_r = max(3, round(13 * k)), max(6, round(38 * k))
    ring_w, term_r = max(2, round(4 * k)), max(4, round(16 * k))
    icon_sz = max(6, round(36 * k))
    stub = round(H * 0.06)

    def node_y(i):
        return round(top + i * (bottom - top) / (n - 1)) if n > 1 else top

    split = node_y(0) if current <= 0 else (node_y(last) if current >= last else node_y(current))

    painter.save()
    painter.translate(ox, oy)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    lx = line_x - line_w // 2
    painter.save()
    painter.setOpacity(painter.opacity() * 0.5)
    painter.fillRect(QRectF(lx, node_y(0) - stub, line_w, stub), QColor(GREY_LINE))
    painter.restore()
    if n > 1:
        painter.fillRect(QRectF(lx, node_y(0), line_w, split - node_y(0)), QColor(GREY_LINE))
        painter.fillRect(QRectF(lx, split, line_w, node_y(last) - split), accent)

    name_font = QFont(painter.font())
    name_font.setPixelSize(name_fs)
    sub_font = QFont(painter.font())
    sub_font.setPixelSize(sub_fs)
    sub_font.setWeight(QFont.Normal)

    for i, name in enumerate(names):
        cy = node_y(i)
        passed, here = i < current, i == current
        if passed:
            _circle(painter, line_x, cy, dot_r, GREY_DOT)
        elif here:
            for extra, opacity in ((22, 0.07), (14, 0.10), (7, 0.16)):
                _circle(painter, line_x, cy, ring_r + round(extra * k), accent, opacity)
            _circle(painter, line_x, cy, ring_r, DARK, 1.0, ring_w, accent)
            painter.drawImage(QRectF(line_x - icon_sz // 2, cy - icon_sz // 2, icon_sz, icon_sz),
                              _train_icon(icon_sz, WHITE))
        elif i == last:
            _circle(painter, line_x, cy, term_r, DARK, 1.0, ring_w, accent)
        else:
            _circle(painter, line_x, cy, dot_r, accent)

        name_font.setWeight(QFont.Bold if here else WEIGHT_SEMIBOLD)
        painter.setFont(name_font)
        painter.setPen(QColor(DIM if passed else WHITE))
        name_y = cy - round(name_fs * 0.6)
        lines = _wrap(QFontMetrics(name_font), name, text_w)
        for j, text in enumerate(lines):
            painter.drawText(QRectF(text_x, name_y + j * name_line_h, text_w, name_line_h),
                             Qt.AlignLeft | Qt.AlignVCenter, text)
        sub = subs[i] if i < len(subs) else ""
        if sub:
            painter.setFont(sub_font)
            painter.setPen(QColor(DIM) if passed else (accent if here else QColor(MUTED)))
            sub_y = name_y + len(lines) * name_line_h + gap
            metrics = QFontMetrics(sub_font)
            painter.drawText(QRectF(text_x, sub_y, text_w, metrics.height()), Qt.AlignLeft | Qt.AlignTop,
                             metrics.elidedText(sub, Qt.ElideRight, int(text_w)))
    painter.restore()
