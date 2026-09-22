"""
tools/hmi_deployer/ai_tab.py -- AI Design tab widget

Chat-style generation console modelled on OpenDesign's chat pane
(``apps/web/src/components/chat``).  Each turn is:

    user brief
    ┌ execution shell ─────────────────────────────────────────┐
    │ ◌ Thinking…                                       12.3s  │  <- head: orb + status word + elapsed
    │   → POST …/v1/chat/completions · qwen3 · 412 chars       │  <- request row
    │   ▸ Thinking                                    ~1.2k    │  <- foldable, live scrolling window
    │   ▸ Response                                    3.4k     │  <- foldable, streamed answer
    │   ✓ Parsed design · 7 widgets                            │  <- tool rows
    │   ✓ Canvas changes                          +7 −0 ~0     │
    │   ⌁ 1.1k in · 3.4k out · 47.9 tok/s · 12.3s              │  <- usage / rate
    └──────────────────────────────────────────────────────────┘
    conclusion prose + "7 widgets: ShGauge x2, …"

Rules borrowed from OpenDesign: the shell is open while running and folds
once the turn concludes (unless the user toggled it); numbers we only
estimate carry a tilde and are replaced by provider-reported usage when it
arrives; nothing is shown as "0.0s".

Networking runs on a worker thread; the connector's event stream is relayed
to the UI through a signal so the canvas stays responsive while a local
model streams.
"""
import copy
import os
import re
import tempfile
import time

from PySide6.QtCore import Qt, Signal, QTimer, QThread, QSettings, QSize, QEvent, QRectF, QPointF, QRect, QPoint
from PySide6.QtGui import (
    QFont, QTextCursor, QKeyEvent, QPainter, QPen, QColor, QConicalGradient,
    QLinearGradient, QBrush, QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGraphicsView, QHBoxLayout, QLabel, QLayout,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QToolButton, QVBoxLayout, QWidget, QMessageBox,
)

from tools.hmi_deployer.ai_design import BYOK_PRESETS, ProviderConfig
from tools.hmi_deployer.ai_generator import (
    build_system_prompt, diff_projects, merge_project_section, summarize_widgets,
)

try:
    from ui.python.shadcn import color as _token, icon as _icon
except ImportError:  # pragma: no cover - the Studio always ships ui/
    from PySide6.QtGui import QIcon
    def _icon(_name, size=18, color=None): return QIcon()
    _FALLBACK = {"background": "#09090b", "card": "#18181b", "border": "#27272a",
                 "foreground": "#ecedee", "mutedForeground": "#a1a1aa", "muted": "#27272a",
                 "primary": "#006fee", "primaryForeground": "#ffffff", "success": "#22c55e",
                 "warning": "#f59e0b", "destructive": "#ef4444", "info": "#3b82f6",
                 "accent": "#27272a", "input": "#27272a"}
    def _token(name, theme="dark"): return _FALLBACK.get(name, "#888888")


def _rgba(hex_color: str, alpha: float) -> str:
    """``#rrggbb`` token + alpha -> ``rgba(r,g,b,a)`` for QSS tints."""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.2f})"


def _icon_file(name: str, size: int, color: str) -> str:
    """Render a Tabler icon to a PNG on disk and return a QSS-safe path.

    ``QComboBox::down-arrow`` and friends only take ``image: url(...)``, so
    the arrow has to exist as a file; one per (name, size, colour) is cached
    in the temp dir.  Forward slashes: QSS chokes on Windows backslashes.
    """
    key = color.lstrip("#").replace("(", "").replace(")", "").replace(",", "_").replace(".", "")
    path = os.path.join(tempfile.gettempdir(), f"eds-ai-{name}-{size}-{key}.png")
    if not os.path.exists(path):
        _icon(name, size, color).pixmap(size, size).save(path, "PNG")
    return path.replace("\\", "/")


# ---------------------------------------------------------------------------
# Number formatting -- same thresholds as OpenDesign's runtime/chat/format.ts
# ---------------------------------------------------------------------------

def format_elapsed(ms) -> str:
    """Tool rows: ``0.4s`` / ``18.2s`` / ``1m 12s``; None when unknown."""
    if ms is None or not ms >= 0:
        return None
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    m, s = int(ms // 60_000), int(round((ms % 60_000) / 1000))
    return f"{m}m {s}s"


def format_shell_elapsed(ms) -> str:
    """Shell head: coarser -- ``3.2s`` / ``31s`` / ``1m 12s``; under 1s shows nothing."""
    if ms is None or not ms >= 1000:
        return None
    if ms < 10_000:
        return f"{ms / 1000:.1f}s"
    if ms < 60_000:
        return f"{int(round(ms / 1000))}s"
    m, s = int(ms // 60_000), int(round((ms % 60_000) / 1000))
    return f"{m}m {s}s"


def format_tokens(count, estimated=False) -> str:
    """``950`` / ``1k`` / ``3.3k`` (rounded, not truncated); ``~`` marks estimates."""
    if count is None or not count > 0:
        return None
    if count < 1000:
        text = str(int(round(count)))
    else:
        text = f"{count / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"~{text}" if estimated else text


def format_rate(tps) -> str:
    if tps is None or not tps > 0:
        return None
    return f"{tps:.1f} tok/s" if tps < 100 else f"{int(round(tps))} tok/s"


def estimate_tokens(chars: int) -> int:
    """~4 chars/token; only used until the provider reports real usage."""
    return max(0, int(chars / 4 + 0.5))


_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _strip_json_objects(text: str) -> str:
    """Remove balanced JSON-object spans (``{...}``), leave the rest of the prose.

    A greedy brace-to-brace regex would eat everything between the first and last brace,
    so prose like "bound to {rpm} and {label}" lost its middle.  Here only a
    span that is actually a JSON object (the design payload) is removed.
    """
    import json
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] != "{":
            out.append(text[i])
            i += 1
            continue
        depth, j = 0, i
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        span = text[i:j + 1] if j < n else None
        parsed = None
        if span:
            try:
                parsed = json.loads(span)
            except ValueError:
                parsed = None
        if isinstance(parsed, dict):
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def conclusion_prose(text: str, limit: int = 600) -> str:
    """The model's own words minus the payload -- what OpenDesign calls the 'say'."""
    prose = _CODE_FENCE_RE.sub("", text or "")
    prose = _strip_json_objects(prose)
    prose = re.sub(r"\n{3,}", "\n\n", prose).strip()
    if len(prose) > limit:
        prose = prose[:limit].rstrip() + "…"
    return prose


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class GenerationWorker(QThread):
    """Runs ``connector.generate_events`` off the UI thread."""
    event = Signal(dict)

    def __init__(self, connector, brief, model, parent=None):
        super().__init__(parent)
        self.connector, self.brief, self.model = connector, brief, model

    def run(self):
        try:
            for ev in self.connector.generate_events(self.brief, self.model):
                self.event.emit(ev)
        except Exception as exc:  # pragma: no cover - belt and braces
            self.event.emit({"type": "error", "message": str(exc)})
            self.event.emit({"type": "turn_end", "stopped": False})


class ProbeWorker(QThread):
    """Reachability + model discovery for the current endpoint."""
    result = Signal(dict)

    def __init__(self, connector, parent=None):
        super().__init__(parent)
        self.connector = connector

    def run(self):
        self.result.emit(self.connector.probe())


# ---------------------------------------------------------------------------
# Primitives (OpenDesign: Foldable / ToolRow / Orb / Chip)
# ---------------------------------------------------------------------------

class Orb(QWidget):
    """OpenDesign's orb: a soft glowing sphere with an arc sweeping round it
    while a turn runs; a filled dot with a check / cross once it settles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._angle = 0
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._state = "idle"
        self._theme = "dark"

    def set_state(self, state: str, theme: str = None):
        """state: running | ok | fail | stopped | idle."""
        if theme:
            self._theme = theme
        self._state = state
        if state == "running":
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._angle = (self._angle + 9) % 360
        self._pulse = (self._pulse + 0.05) % 2.0
        self.update()

    def paintEvent(self, _event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        centre = rect.center()
        tone = {"ok": "success", "fail": "destructive", "stopped": "warning",
                "running": "primary"}.get(self._state, "mutedForeground")
        colour = QColor(_token(tone, self._theme))
        if self._state == "running":
            # Breathing glow under a sweeping conic arc.
            glow = QColor(colour)
            glow.setAlphaF(0.18 + 0.12 * math.sin(self._pulse * math.pi))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(rect)
            core = QColor(colour)
            core.setAlphaF(0.55)
            p.setBrush(core)
            p.drawEllipse(rect.adjusted(4, 4, -4, -4))
            grad = QConicalGradient(centre, -self._angle)
            grad.setColorAt(0.0, colour)
            faded = QColor(colour)
            faded.setAlphaF(0.0)
            grad.setColorAt(0.75, faded)
            grad.setColorAt(1.0, faded)
            p.setPen(QPen(QBrush(grad), 2.0, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawArc(rect, 0, 360 * 16)
            return
        p.setPen(Qt.NoPen)
        p.setBrush(colour)
        p.drawEllipse(rect)
        fg = QColor(_token("primaryForeground", self._theme))
        p.setPen(QPen(fg, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cx, cy = centre.x(), centre.y()
        if self._state == "ok":
            p.drawPolyline([QPointF(cx - 3.5, cy - 0.3), QPointF(cx - 1, cy + 2.2), QPointF(cx + 3.6, cy - 2.6)])
        elif self._state == "fail":
            p.drawLine(QPointF(cx - 3, cy - 3), QPointF(cx + 3, cy + 3))
            p.drawLine(QPointF(cx + 3, cy - 3), QPointF(cx - 3, cy + 3))
        elif self._state == "stopped":
            p.setBrush(fg)
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(cx - 2.5, cy - 2.5, 5, 5))


class Chip(QLabel):
    """Small rounded pill for one fact: ``3 widgets`` / ``+3 -0 ~0`` / ``48 tok/s``.

    ``tone`` picks the tint: neutral | info | ok | warn | fail.
    """

    def __init__(self, text: str = "", tone: str = "neutral", parent=None):
        super().__init__(parent)
        self.setObjectName("chip")
        self._theme = "dark"
        self.setProperty("tone", tone)
        self.setText(text)
        self.setAlignment(Qt.AlignVCenter)

    def set_tone(self, tone: str):
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)

    def retheme(self, theme):
        self._theme = theme


class FlowLayout(QLayout):
    """Left-to-right layout that wraps -- so a row of chips never forces the
    conversation wider than its pane (the classic Qt flow-layout example)."""

    def __init__(self, parent=None, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._items = []
        self._h, self._v = h_spacing, v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect, dry):
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            w = item.sizeHint().width()
            if x + w > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._v
                line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x += w + self._h
            line_h = max(line_h, item.sizeHint().height())
        return y + line_h - rect.y()

    def clear(self):
        while self._items:
            item = self._items.pop()
            if item.widget() is not None:
                item.widget().deleteLater()


class FadeOverlay(QWidget):
    """Top/bottom gradient masks over a live stream pane (OpenDesign's
    thinking window fades at both edges so the tail reads as 'flowing')."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._colour = QColor("#09090b")

    def set_colour(self, hex_color: str):
        self._colour = QColor(hex_color)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        h = self.height()
        solid = QColor(self._colour)
        clear = QColor(self._colour)
        clear.setAlpha(0)
        top = QLinearGradient(0, 0, 0, 18)
        top.setColorAt(0, solid)
        top.setColorAt(1, clear)
        p.fillRect(QRectF(0, 0, self.width(), 18), top)
        bottom = QLinearGradient(0, h - 22, 0, h)
        bottom.setColorAt(0, clear)
        bottom.setColorAt(1, solid)
        p.fillRect(QRectF(0, h - 22, self.width(), 22), bottom)


class Foldable(QFrame):
    """Header row that toggles a body; the whole row is the hit area.

    ``set_lifecycle_open`` mirrors OpenDesign's rule: the fold follows the
    run's lifecycle until the user toggles it by hand, then it is theirs.
    """
    toggled = Signal(bool)

    def __init__(self, title: str = "", variant: str = "flat", parent=None, head_widget: QWidget = None):
        super().__init__(parent)
        self.setObjectName("foldFlat" if variant == "flat" else "foldBoxed")
        self._open = False
        self._user_toggled = False
        self._theme = "dark"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("foldHead")
        self.header.setCursor(Qt.PointingHandCursor)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(8, 6, 8, 6)
        head.setSpacing(8)
        self.chevron = QLabel()
        self.chevron.setFixedSize(14, 14)
        head.addWidget(self.chevron)
        if head_widget is not None:
            self.title_widget = head_widget
            head.addWidget(head_widget, 1)
            self.title = None
        else:
            self.title = QLabel(title)
            self.title.setObjectName("foldTitle")
            head.addWidget(self.title, 1)
            self.title_widget = self.title
        self.right = QLabel("")
        self.right.setObjectName("foldRight")
        self.right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.right)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("foldBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(24, 2, 8, 8)
        self.body_layout.setSpacing(4)
        self.body.setVisible(False)
        outer.addWidget(self.body)

        self.header.mousePressEvent = self._on_head_press
        self._render_chevron()

    def _on_head_press(self, _event):
        self._user_toggled = True
        self.set_open(not self._open)

    def set_open(self, open_: bool):
        self._open = bool(open_)
        self.body.setVisible(self._open)
        self._render_chevron()
        self.toggled.emit(self._open)

    def is_open(self) -> bool:
        return self._open

    def set_lifecycle_open(self, open_: bool):
        if not self._user_toggled:
            self.set_open(open_)

    def set_right(self, text):
        self.right.setText(text or "")

    def set_title(self, text):
        if self.title is not None:
            self.title.setText(text)

    def add(self, widget: QWidget):
        self.body_layout.addWidget(widget)

    def retheme(self, theme):
        self._theme = theme
        self._render_chevron()

    def _render_chevron(self):
        name = "chevron-down" if self._open else "chevron-right"
        self.chevron.setPixmap(_icon(name, 14, _token("mutedForeground", self._theme)).pixmap(14, 14))


class ElidedLabel(QLabel):
    """Single-line label that elides in the middle instead of widening the pane.

    Long URLs and paths must not force a horizontal scrollbar on the whole
    conversation; the full text stays in the tooltip.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)
        super().setText(text)

    def setText(self, text):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def text(self):
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        if self.wordWrap():
            super().setText(self._full)
            return
        width = max(20, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, width))


class ToolRow(QWidget):
    """One line of the execution record: icon · title · meta (right).

    A single icon carries both what the row is and how it went: the kind
    icon is tinted muted while pending, primary while running, green when
    ok and red on failure.
    """
    TONES = {"ok": "success", "fail": "destructive", "running": "primary",
             "pending": "mutedForeground", "stopped": "warning"}

    def __init__(self, icon_name: str, title: str, meta: str = "", status: str = "pending", parent=None):
        super().__init__(parent)
        self.setObjectName("toolRow")
        self._icon_name = icon_name
        self._status = status
        self._theme = "dark"
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(14, 14)
        row.addWidget(self.icon)
        self.title = ElidedLabel(title)
        self.title.setObjectName("toolTitle")
        row.addWidget(self.title, 1)
        self.meta = QLabel(meta or "")
        self.meta.setObjectName("toolMeta")
        self.meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.meta)
        self._render_icon()

    def set_status(self, status):
        self._status = status
        self._render_icon()

    def set_meta(self, text):
        self.meta.setText(text or "")

    def set_title(self, text):
        self.title.setText(text)

    def retheme(self, theme):
        self._theme = theme
        self._render_icon()

    def _render_icon(self):
        name = "circle-x" if self._status == "fail" else self._icon_name
        tone = self.TONES.get(self._status, "mutedForeground")
        self.icon.setPixmap(_icon(name, 14, _token(tone, self._theme)).pixmap(14, 14))


class StreamPane(QPlainTextEdit):
    """Read-only monospace pane that follows the stream while it is live.

    Live = fixed-height window that keeps its tail in view (the reader is not
    scrolling it).  Settled = grows to its content up to a cap and scrolls
    normally, because now the reader is the one driving.
    """

    def __init__(self, live_height=96, max_height=260, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("streamPane")
        self.setFrameShape(QFrame.NoFrame)
        mono = QFont()
        mono.setFamilies(["Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "monospace"])
        mono.setStyleHint(QFont.Monospace)
        mono.setPixelSize(12)
        self.setFont(mono)
        self._live_height, self._max_height = live_height, max_height
        self._live = True
        self.setFixedHeight(live_height)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fade = FadeOverlay(self)

    def set_surface(self, hex_color: str):
        self.fade.set_colour(hex_color)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fade.setGeometry(self.viewport().geometry())

    def append_delta(self, delta: str):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(delta)
        if self._live:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def settle(self):
        self._live = False
        self.fade.hide()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        doc_h = int(self.document().size().height() * self.fontMetrics().lineSpacing()) + 12
        self.setFixedHeight(max(28, min(self._max_height, doc_h)))
        self.verticalScrollBar().setValue(0)


# ---------------------------------------------------------------------------
# Execution shell -- one turn's process record
# ---------------------------------------------------------------------------

class ExecutionShell(Foldable):
    """The record card: head (orb · status · elapsed) over rows of what happened."""

    STATUS_WORDS = {
        "sending": "Sending request…",
        "connecting": "Connecting…",
        "thinking": "Thinking…",
        "writing": "Writing…",
        "parsing": "Parsing design…",
        "done": "Done",
        "failed": "Failed",
        "stopped": "Cancelled",
    }

    def __init__(self, parent=None):
        # Head widgets are built before the QFrame exists, so keep them local
        # until super().__init__ has run (PySide forbids touching self before).
        head = QWidget()
        head.setObjectName("shellHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        orb = Orb()
        hl.addWidget(orb)
        status_word = QLabel(self.STATUS_WORDS["sending"])
        status_word.setObjectName("shellStatus")
        hl.addWidget(status_word, 1)
        super().__init__(variant="flat", parent=parent, head_widget=head)
        self.orb, self.status_word = orb, status_word
        self.setObjectName("executionShell")
        self.body_layout.setContentsMargins(26, 4, 10, 10)

        self.started = time.monotonic()
        self.first_output_at = None
        self.finished_at = None
        self.running = True
        self._status = "sending"
        self.orb.set_state("running")

        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

        # Rows are created lazily: a provider that never thinks never shows a
        # thinking row, a run that fails before the answer never shows one.
        self.request_row = None
        self.thinking_fold = None
        self.thinking_pane = None
        self.response_fold = None
        self.response_pane = None
        self.parse_row = None
        self.polish_row = None
        self.changes_fold = None
        self.usage_row = None
        self.error_row = None
        self._tool_rows = {}
        self._rows = []

        self.thinking_chars = 0
        self.output_chars = 0
        self.thinking_tokens_reported = None
        self.truncated = False
        self.usage = None            # provider-reported {input_tokens, output_tokens, thinking_tokens}
        self.rate_reported = None    # provider-measured tok/s (Ollama)
        self.set_open(True)

    # -- lifecycle ---------------------------------------------------------

    def set_status(self, key: str):
        self._status = key
        self.status_word.setText(self.STATUS_WORDS.get(key, key))
        self.status_word.setProperty("tone", {"failed": "fail", "done": "ok", "stopped": "warn"}.get(key, ""))
        self.status_word.style().unpolish(self.status_word)
        self.status_word.style().polish(self.status_word)

    def finish(self, outcome: str):
        """outcome: done | failed | stopped."""
        self.running = False
        self.finished_at = time.monotonic()
        self._clock.stop()
        self.set_status(outcome)
        self.orb.set_state({"done": "ok", "failed": "fail", "stopped": "stopped"}[outcome], self._theme)
        for pane in (self.thinking_pane, self.response_pane):
            if pane is not None:
                pane.settle()
        if self.thinking_fold is not None:
            self.thinking_fold.set_lifecycle_open(False)
        if self.response_fold is not None:
            self.response_fold.set_lifecycle_open(False)
        self._tick()
        self._refresh_usage_row()

    def elapsed_ms(self):
        end = self.finished_at or time.monotonic()
        return (end - self.started) * 1000.0

    def _tick(self):
        self.set_right(format_shell_elapsed(self.elapsed_ms()) or "")
        if self.running:
            self._refresh_usage_row()

    # -- rows ----------------------------------------------------------------

    def _add_row(self, widget):
        # The usage line arrives mid-stream (provider usage chunk) but reads
        # as the record's footer, so later rows slot in above it.
        if self.usage_row is not None and widget is not self.usage_row:
            index = self.body_layout.indexOf(self.usage_row)
            self.body_layout.insertWidget(index, widget)
        else:
            self.add(widget)
        self._rows.append(widget)
        return widget

    def note_request(self, provider: str, model: str, url: str, brief: str, mode: str):
        title = f"POST {url}"
        meta = f"{model} · {len(brief)} chars"
        self.request_row = self._add_row(ToolRow("upload", title, meta, "ok"))
        self.request_row.setToolTip(f"provider={provider} mode={mode}\nmodel={model}")
        self.set_status("sending")

    def note_status(self, label: str):
        if label == "truncated":
            self.truncated = True
            # The recovery card below the shell is the single source of the
            # explanatory copy. Keeping this stream record quiet prevents the
            # same limit warning appearing twice in one failed turn.
            return
        if label == "connecting":
            self.set_status("connecting")
        elif label == "streaming" and self._status in ("sending", "connecting"):
            self.set_status("writing")
        if self.request_row is not None and label == "streaming":
            self.request_row.set_status("ok")

    def append_thinking(self, delta: str):
        if self.thinking_fold is None:
            self.thinking_fold = Foldable("Thinking", variant="boxed")
            self.thinking_fold.retheme(self._theme)
            self.thinking_pane = StreamPane(live_height=96, max_height=220)
            self.thinking_pane.set_surface(_token("background", self._theme))
            self.thinking_fold.add(self.thinking_pane)
            self.thinking_fold.set_open(True)
            self._add_row(self.thinking_fold)
        if self.first_output_at is None:
            self.first_output_at = time.monotonic()
        self.set_status("thinking")
        self.thinking_chars += len(delta)
        self.thinking_pane.append_delta(delta)
        self._refresh_thinking_count()

    def note_thinking_tokens(self, tokens):
        self.thinking_tokens_reported = tokens
        self._refresh_thinking_count()

    def _refresh_thinking_count(self):
        if self.thinking_fold is None:
            return
        if self.thinking_tokens_reported:
            text = format_tokens(self.thinking_tokens_reported)
        else:
            text = format_tokens(estimate_tokens(self.thinking_chars), estimated=True)
        self.thinking_fold.set_right(text or "")

    def append_delta(self, delta: str):
        if self.response_fold is None:
            self.response_fold = Foldable("Response", variant="boxed")
            self.response_fold.retheme(self._theme)
            self.response_pane = StreamPane(live_height=140, max_height=320)
            self.response_pane.set_surface(_token("background", self._theme))
            self.response_fold.add(self.response_pane)
            self.response_fold.set_open(True)
            self._add_row(self.response_fold)
            if self.thinking_fold is not None:
                # The model has started answering: fold the reasoning away
                # unless the reader is holding it open.
                self.thinking_fold.set_lifecycle_open(False)
        if self.first_output_at is None:
            self.first_output_at = time.monotonic()
        self.set_status("writing")
        self.output_chars += len(delta)
        self.response_pane.append_delta(delta)
        self.response_fold.set_right(format_tokens(estimate_tokens(self.output_chars), estimated=True) or "")

    def note_tool(self, event: dict):
        """Daemon-mode agent tool calls (Read / Write / Bash …)."""
        tool_id = event.get("id") or event.get("toolUseId") or f"tool{len(self._tool_rows)}"
        if event["type"] == "tool_use":
            name = event.get("name") or "tool"
            inp = event.get("input") or {}
            path = inp.get("file_path") or inp.get("path") or ""
            title = event.get("description") or event.get("title") or name
            row = ToolRow("terminal-2" if name.lower() in ("bash", "shell") else "file-code",
                          title, path.split("/")[-1] if path else "", "running")
            self._tool_rows[tool_id] = self._add_row(row)
        else:
            row = self._tool_rows.get(tool_id)
            if row is not None:
                row.set_status("fail" if event.get("isError") or event.get("is_error") else "ok")

    def note_usage(self, event: dict):
        self.usage = event.get("usage") or {}
        if event.get("tokensPerSecond"):
            self.rate_reported = event["tokensPerSecond"]
        self._refresh_usage_row()
        if self.response_fold is not None and self.usage.get("output_tokens"):
            self.response_fold.set_right(format_tokens(self.usage["output_tokens"]) or "")
        if self.thinking_fold is not None and self.usage.get("thinking_tokens"):
            self.thinking_tokens_reported = self.usage["thinking_tokens"]
            self._refresh_thinking_count()

    def note_parse(self, project, summary: str):
        if project is not None:
            self.parse_row = self._add_row(ToolRow("file-code", f"Parsed design · {summary}", "", "ok"))
        else:
            self.parse_row = self._add_row(ToolRow("file-code", "Could not parse a design from the response", "", "fail"))

    def note_changes(self, diff: dict, applied: bool):
        added, removed, changed = diff["added"], diff["removed"], diff["changed"]
        meta = f"+{len(added)} −{len(removed)} ~{len(changed)}"
        title = "Canvas changes" if applied else "Canvas changes (not applied)"
        self.changes_fold = Foldable(title, variant="boxed")
        self.changes_fold.retheme(self._theme)
        self.changes_fold.set_right(meta)
        lines = []
        lines += [f"+ {w['id']}  ({w['type']})" for w in added]
        lines += [f"− {w['id']}  ({w['type']})" for w in removed]
        lines += [f"~ {w['id']}  ({w['type']})" for w in changed]
        body = QLabel("\n".join(lines) if lines else "No widget differences from the current canvas.")
        body.setObjectName("changesList")
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setWordWrap(True)
        self.changes_fold.add(body)
        self._add_row(self.changes_fold)

    def note_polish(self, report):
        """``Composed: hero-centre, 62 -> 88`` -- what the layout pass did.

        The model's geometry is a draft; designer.layout.polish composes it
        before it reaches the canvas, and a record that does not say so
        leaves the author wondering why the screen is not what was sent.
        """
        if report is None:
            return None
        try:
            from designer.layout.polish import summary
            title = summary(report)
        except Exception:
            title = f"Composed: {getattr(report, 'archetype', '') or 'as drawn'}"
        meta = ""
        try:
            issues = [i for i in report.after.issues if i.severity == "error"]
            meta = f"{len(issues)} defect{'s' if len(issues) != 1 else ''} left" if issues else ""
        except Exception:
            pass
        gain = getattr(report, "gain", 0.0) or 0.0
        self.polish_row = self._add_row(ToolRow("layout-grid", title, meta,
                                                "ok" if gain >= 0 else "pending"))
        return self.polish_row

    def note_error(self, message: str):
        self.error_row = self._add_row(ToolRow("alert-triangle", message, "", "fail"))
        self.error_row.title.setWordWrap(True)

    # -- metrics -------------------------------------------------------------

    def metrics(self) -> dict:
        """Everything the usage row and the session strip need, in one place."""
        usage = self.usage or {}
        exact_out = usage.get("output_tokens")
        exact_in = usage.get("input_tokens")
        est_out = estimate_tokens(self.output_chars + self.thinking_chars)
        out_tokens = exact_out if exact_out else est_out
        elapsed = self.elapsed_ms()
        ttft = None
        if self.first_output_at is not None:
            ttft = (self.first_output_at - self.started) * 1000.0
        rate = self.rate_reported
        if rate is None and self.first_output_at is not None and out_tokens:
            end = self.finished_at or time.monotonic()
            span = end - self.first_output_at
            if span > 0.25:
                rate = out_tokens / span
        return {
            "input_tokens": exact_in,
            "output_tokens": out_tokens,
            "output_estimated": not exact_out,
            "total_tokens": (exact_in or 0) + out_tokens if (exact_in or out_tokens) else 0,
            "rate": rate,
            "ttft_ms": ttft,
            "elapsed_ms": elapsed,
        }

    def _refresh_usage_row(self):
        m = self.metrics()
        if not m["output_tokens"] and not m["input_tokens"]:
            return
        parts = []
        if m["input_tokens"]:
            parts.append(f"{format_tokens(m['input_tokens'])} in")
        out = format_tokens(m["output_tokens"], estimated=m["output_estimated"])
        if out:
            parts.append(f"{out} out")
        if m["input_tokens"] and m["output_tokens"]:
            parts.append(f"{format_tokens(m['total_tokens'], estimated=m['output_estimated'])} total")
        rate = format_rate(m["rate"])
        if rate:
            parts.append(rate)
        if m["ttft_ms"] is not None and m["ttft_ms"] >= 100:
            parts.append(f"TTFT {format_elapsed(m['ttft_ms'])}")
        if not self.running:
            done = format_elapsed(m["elapsed_ms"])
            if done:
                parts.append(done)
        text = " · ".join(parts)
        if self.usage_row is None:
            self.usage_row = self._add_row(ToolRow("activity", text, "", "pending"))
            self.usage_row.title.setObjectName("toolMeta")
        else:
            self.usage_row.set_title(text)

    def retheme(self, theme):
        super().retheme(theme)
        self.orb.set_state(self.orb._state, theme)
        for row in self._rows:
            if hasattr(row, "retheme"):
                row.retheme(theme)
        for pane in (self.thinking_pane, self.response_pane):
            if pane is not None:
                pane.set_surface(_token("background", theme))


# ---------------------------------------------------------------------------
# Variants = the same section, composed differently
# ---------------------------------------------------------------------------

class VariantThumb(QFrame):
    """One composition, drawn by the panel's own renderer. Click to take it."""

    clicked = Signal()

    def __init__(self, pixmap, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("variantThumb")
        self.setCursor(Qt.PointingHandCursor)
        col = QVBoxLayout(self)
        col.setContentsMargins(4, 4, 4, 6)
        col.setSpacing(4)
        art = QLabel()
        art.setPixmap(pixmap)
        art.setAlignment(Qt.AlignCenter)
        col.addWidget(art)
        self.caption = ElidedLabel(title)
        self.caption.setObjectName("variantCaption")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setToolTip(title)
        col.addWidget(self.caption)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class VariantStrip(QWidget):
    """Up to three compositions of the same widgets, offered under the turn.

    Composition is a judgement call the critic can only narrow, not settle,
    so the ones it liked are shown rather than argued about: whichever is
    clicked replaces what is on the canvas.
    """

    picked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("variantStrip")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, 0)
        col.setSpacing(6)
        self.heading = QLabel("Other compositions")
        self.heading.setObjectName("toolMeta")
        col.addWidget(self.heading)
        host = QWidget()
        self.row = QHBoxLayout(host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.row.addStretch(1)
        col.addWidget(host)
        self.setVisible(False)

    def clear(self):
        while self.row.count() > 1:
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.setVisible(False)

    def show_variants(self, items):
        """items: (archetype_id, score, QImage, project), best first."""
        self.clear()
        for archetype, score, image, project in list(items)[:3]:
            pixmap = QPixmap.fromImage(image).scaled(QSize(132, 92), Qt.KeepAspectRatio,
                                                     Qt.SmoothTransformation)
            thumb = VariantThumb(pixmap, f"{archetype} · {score:.0f}")
            thumb.clicked.connect(lambda p=project: self.picked.emit(p))
            self.row.insertWidget(self.row.count() - 1, thumb)
        self.setVisible(self.row.count() > 1)


# ---------------------------------------------------------------------------
# Turn = brief + shell + conclusion
# ---------------------------------------------------------------------------

class TurnWidget(QWidget):
    applyRequested = Signal(object)
    editRequested = Signal(str)   # "Edit brief & retry": put the brief back in the composer
    variantPicked = Signal(object)  # a composition from the strip, for the canvas

    def __init__(self, brief: str, parent=None):
        super().__init__(parent)
        self.setObjectName("turn")
        self.brief_text = brief
        self.project = None
        self._theme = "dark"
        self._chips = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        bubble_row = QHBoxLayout()
        bubble_row.addStretch(1)
        self.bubble = QLabel(brief)
        self.bubble.setObjectName("userBubble")
        self.bubble.setWordWrap(True)
        self.bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.bubble.setMaximumWidth(440)
        bubble_row.addWidget(self.bubble)
        col.addLayout(bubble_row)

        self.shell = ExecutionShell()
        col.addWidget(self.shell)

        # Conclusion: avatar / prose / metric chips / actions -- OpenDesign's
        # "say" block under the record card.
        self.card = QFrame()
        self.card.setObjectName("assistantCard")
        self.card.setVisible(False)
        card = QHBoxLayout(self.card)
        card.setContentsMargins(2, 2, 2, 2)
        card.setSpacing(12)
        self.avatar = QLabel()
        self.avatar.setObjectName("assistantAvatar")
        self.avatar.setFixedSize(26, 26)
        self.avatar.setAlignment(Qt.AlignCenter)
        card.addWidget(self.avatar, 0, Qt.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(8)
        self.conclusion = QLabel("")
        self.conclusion.setObjectName("conclusion")
        self.conclusion.setWordWrap(True)
        self.conclusion.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(self.conclusion)
        self.chip_host = QWidget()
        self.chip_host.setObjectName("chipHost")
        self.chip_row = FlowLayout(self.chip_host)
        body.addWidget(self.chip_host)
        self.variant_strip = VariantStrip()
        self.variant_strip.picked.connect(self.variantPicked)
        body.addWidget(self.variant_strip)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        self.apply_btn = QPushButton("Apply to canvas")
        self.apply_btn.setObjectName("secondaryAction")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.setVisible(False)
        self.apply_btn.clicked.connect(lambda: self.applyRequested.emit(self.project))
        actions.addWidget(self.apply_btn)
        actions.addStretch(1)
        body.addLayout(actions)
        card.addLayout(body, 1)
        col.addWidget(self.card)

        # Failure card: the shell folds on failure like OpenDesign's, so the
        # reason and the next step must live outside it where they stay visible.
        self.error_card = QFrame()
        self.error_card.setObjectName("errorCard")
        self.error_card.setVisible(False)
        ec = QHBoxLayout(self.error_card)
        ec.setContentsMargins(14, 12, 14, 12)
        ec.setSpacing(12)
        self.error_icon = QLabel()
        self.error_icon.setObjectName("errorIcon")
        self.error_icon.setFixedSize(28, 28)
        self.error_icon.setAlignment(Qt.AlignCenter)
        ec.addWidget(self.error_icon, 0, Qt.AlignTop)
        ebody = QVBoxLayout()
        ebody.setSpacing(6)
        self.error_title = QLabel("")
        self.error_title.setObjectName("errorTitle")
        self.error_title.setWordWrap(True)
        self.error_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ebody.addWidget(self.error_title)
        self.error_text = QLabel("")
        self.error_text.setObjectName("errorText")
        self.error_text.setWordWrap(True)
        self.error_text.setTextFormat(Qt.RichText)
        self.error_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ebody.addWidget(self.error_text)
        eactions = QHBoxLayout()
        eactions.setContentsMargins(0, 4, 0, 0)
        self.edit_btn = QPushButton("Edit brief && retry")
        self.edit_btn.setObjectName("secondaryAction")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.clicked.connect(lambda: self.editRequested.emit(self.brief_text))
        eactions.addWidget(self.edit_btn)
        eactions.addStretch(1)
        ebody.addLayout(eactions)
        ec.addLayout(ebody, 1)
        col.addWidget(self.error_card)
        self._render_avatar()

    def show_error(self, message: str, hint="", tips=None):
        """``hint`` is one sentence under the title; ``tips`` a list rendered as bullets."""
        self.error_title.setText(message)
        parts = []
        if hint:
            parts.append(hint)
        if tips:
            parts.append("<ul style='margin:0 0 0 14px; -qt-list-indent:1;'>"
                         + "".join(f"<li style='margin:2px 0;'>{t}</li>" for t in tips) + "</ul>")
        self.error_text.setText("".join(f"<p style='margin:0 0 4px 0;'>{p}</p>" if not p.startswith("<ul") else p
                                        for p in parts))
        self.error_text.setVisible(bool(parts))
        self.error_icon.setPixmap(_icon("alert-triangle", 15, _token("destructive", self._theme)).pixmap(15, 15))
        self.edit_btn.setIcon(_icon("pencil", 13, _token("foreground", self._theme)))
        self.error_card.setVisible(True)

    def show_variants(self, items):
        """Offer other compositions of this section; nothing shown for none."""
        self.variant_strip.show_variants(items)
        self.card.setVisible(self.card.isVisible() or self.variant_strip.isVisible())

    def conclude(self, project, prose: str, chips: list):
        """chips: list of (text, tone)."""
        self.project = project
        self.conclusion.setText(prose)
        self.conclusion.setVisible(bool(prose))
        self.chip_row.clear()
        self._chips = []
        for text, tone in chips:
            chip = Chip(text, tone)
            self.chip_row.addWidget(chip)
            self._chips.append(chip)
        self.chip_host.setVisible(bool(chips))
        self.apply_btn.setVisible(project is not None)
        self.apply_btn.setIcon(_icon("device-desktop", 14, _token("foreground", self._theme)))
        self.card.setVisible(bool(prose) or bool(chips) or self.variant_strip.isVisible())

    def retheme(self, theme):
        self._theme = theme
        self.shell.retheme(theme)
        self._render_avatar()
        if self.error_card.isVisible():
            self.error_icon.setPixmap(_icon("alert-triangle", 15, _token("destructive", theme)).pixmap(15, 15))
            self.edit_btn.setIcon(_icon("pencil", 13, _token("foreground", theme)))
        if self.apply_btn.isVisible():
            self.apply_btn.setIcon(_icon("device-desktop", 14, _token("foreground", theme)))

    def _render_avatar(self):
        self.avatar.setPixmap(_icon("bolt", 14, _token("primaryForeground", self._theme)).pixmap(14, 14))


# ---------------------------------------------------------------------------
# Empty-state prompt card
# ---------------------------------------------------------------------------

class PromptCard(QFrame):
    """icon · title / blurb · chevron -- the whole card is the hit area.

    A QFrame rather than a QPushButton: a button ignores the size of a
    child layout, so the card collapsed to its text-less minimum.
    """
    clicked = Signal(str)

    def __init__(self, icon_name: str, title: str, blurb: str, brief: str, parent=None):
        super().__init__(parent)
        self.setObjectName("promptCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(brief)
        self._brief = brief
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        self.icon = QLabel()
        self.icon.setObjectName("promptCardIcon")
        self.icon.setFixedSize(32, 32)
        self.icon.setAlignment(Qt.AlignCenter)
        row.addWidget(self.icon)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("promptCardTitle")
        text.addWidget(self.title)
        self.blurb = QLabel(blurb)
        self.blurb.setObjectName("promptCardBlurb")
        text.addWidget(self.blurb)
        self.meta = QLabel("Use this brief")
        self.meta.setObjectName("promptCardMeta")
        text.addWidget(self.meta)
        row.addLayout(text, 1)
        self.arrow = QLabel()
        self.arrow.setFixedSize(14, 14)
        row.addWidget(self.arrow)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self._brief)
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# Composer input: Ctrl+Enter sends
# ---------------------------------------------------------------------------

class BriefInput(QPlainTextEdit):
    """Grows with its text between one and six lines, like a chat composer."""
    submitted = Signal()
    MIN_LINES, MAX_LINES = 1, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(lambda _s: self._fit())
        self._fit()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        line = self.fontMetrics().lineSpacing()
        pad = int(self.document().documentMargin() * 2) + 4
        lines = max(self.MIN_LINES, int(self.document().size().height() + 0.5))
        self.setFixedHeight(min(self.MAX_LINES, lines) * line + pad)


class PreviewView(QGraphicsView):
    """Read-only second view onto the Designer's scene: same bezel, grid and
    widgets as the Designer tab, always fitted to the pane."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewView")
        self.setInteractive(False)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def attach(self, scene):
        self.setScene(scene)
        scene.sceneRectChanged.connect(lambda _r: self.refit())
        self.refit()
        # The first fit can happen before this view has a viewport. Repeat it
        # on the next event turn so a newly opened AI tab frames the whole
        # physical panel instead of inheriting a tiny pre-layout transform.
        QTimer.singleShot(0, self.refit)

    def refit(self):
        scene = self.scene()
        if scene is not None and not scene.sceneRect().isEmpty():
            self.fitInView(scene.sceneRect().adjusted(-8, -8, 8, 8), Qt.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        self.refit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit()

class PreviewEmptyState(QFrame):
    """A purposeful canvas empty state, rather than a line of orphaned text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewEmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(10)
        layout.addStretch(1)
        self.icon = QLabel()
        self.icon.setObjectName("previewEmptyIcon")
        self.icon.setFixedSize(48, 48)
        self.icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon, 0, Qt.AlignHCenter)
        title = QLabel("Your canvas is ready")
        title.setObjectName("previewEmptyTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        body = QLabel("Generate a direction on the left, then refine every detail in Designer.")
        body.setObjectName("previewEmptyBody")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        layout.addWidget(body)
        layout.addStretch(1)


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

class AIDesignTab(QWidget):
    """AI-powered design tab: model picker, generation console, canvas hand-off."""

    MAX_SECTION_RUNS = 8
    SECTION_REQUEST = (
        "Build this design in sections. Return section 1 now as one complete, valid JSON "
        "design section containing at most 8 widgets. Include the section object with index, "
        "label, complete, and next fields. Do not emit later sections in this response."
    )

    generateRequested = Signal(object)  # DesignerProject ready to place on the canvas
    canvasFocusRequested = Signal()     # user pressed "Apply to canvas": show the Designer
    statusMessage = Signal(str)

    def __init__(self, connector=None, generator=None, parent=None):
        super().__init__(parent)
        self.connector = connector
        self.generator = generator
        self.workspace = None
        self.streaming = False
        self.last_project = None
        self.turns: list[TurnWidget] = []
        self._worker = None
        self._active_turn = None
        self._probe = None
        self._probe_pending = False
        self._probe_ok = None
        self._probe_models: list[str] = []
        self._section_run = 0
        self._section_project = None
        self._queued_section_request = None
        self._root_brief = ""
        # The panel's own renderer, for the variant thumbnails: None until
        # asked for, False when there is no hmi-ui binary to ask.
        self._variant_renderer_cache = None
        self._theme = "dark"
        self._icon_slots = []  # (widget, icon_name, size, token) re-rendered on theme change
        self.settings = QSettings("MIL-HMI", "Deployer")

        # Session totals (what the footer strip shows).
        self.session = {"runs": 0, "input_tokens": 0, "output_tokens": 0, "estimated": False, "last_rate": None}

        self._build_ui()
        self._populate_providers()
        self.apply_theme(self._theme)
        self._load_defaults()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    EXAMPLES = [
        ("gauge", "Engine dashboard", "RPM and temperature gauges, fuel bar, start/stop",
         "Engine dashboard: large RPM gauge bound to eng.rpm, coolant and oil temperature gauges "
         "(eng.coolant_c, eng.oil_c), a fuel level bar, Start/Stop buttons and a status strip."),
        ("bell", "Alarm overview", "Alarm table, acknowledge-all, fault annunciators",
         "Alarm overview page: full-width alarm table bound to plc.alarms, an acknowledge-all "
         "button, and four annunciator tiles for the highest-priority faults."),
        ("droplet", "Pump control", "Two pump cards with run toggles, flow and pressure",
         "Pump control screen: two pump cards side by side, each with a run toggle, a flow "
         "numeric display bound to pump.N.flow, a pressure gauge and a running status dot."),
        ("gauge", "Automotive cluster", "Instrument cluster with RPM, speed, fuel and coolant",
         "Automotive cluster: instrument cluster with RPM arc gauge, speed readout, fuel level, "
         "coolant temperature, gear indicator, drive mode selector, trip info telltales and "
         "ambient readout — dark palette with redline bands."),
    ]

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # Console on the left, the Designer's own canvas on the right -- the
        # same scene (bezel, grid, widgets) the Designer tab shows, so what the
        # model places is visible without leaving the conversation.
        self.split = QSplitter(Qt.Horizontal)
        self.split.setObjectName("aiSplitter")
        self.split.setHandleWidth(1)
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split)

        console = QFrame()
        console.setObjectName("aiConsole")
        console.setMinimumWidth(380)
        layout = QVBoxLayout(console)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.split.addWidget(console)

        # -- top bar: provider / model / connection ---------------------------
        top_bar = QFrame()
        top_bar.setObjectName("aiTopBar")
        top = QVBoxLayout(top_bar)
        top.setContentsMargins(16, 12, 16, 10)
        top.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("providerSelector")
        self.provider_combo.setMinimumWidth(140)
        self.provider_combo.setCursor(Qt.PointingHandCursor)
        row1.addWidget(self._labelled("Provider", self.provider_combo))

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("modelSelector")
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.setMinimumWidth(160)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row1.addWidget(self._labelled("Model", self.model_combo), 1)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setObjectName("iconButton")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setToolTip("Test the connection and refresh the model list")
        self.refresh_btn.clicked.connect(self.probe_connection)
        self._icon_slots.append((self.refresh_btn, "refresh", 14, "foreground"))
        row1.addWidget(self.refresh_btn, 0, Qt.AlignBottom)
        top.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.setContentsMargins(2, 0, 0, 0)
        self.status_dot = QLabel()
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setProperty("tone", "neutral")
        row2.addWidget(self.status_dot)
        self.status_lbl = QLabel("Not checked")
        self.status_lbl.setObjectName("connectionStatus")
        row2.addWidget(self.status_lbl, 1)
        self.endpoint_toggle = QToolButton()
        self.endpoint_toggle.setObjectName("linkButton")
        self.endpoint_toggle.setText("Endpoint")
        self.endpoint_toggle.setCursor(Qt.PointingHandCursor)
        self.endpoint_toggle.setCheckable(True)
        self.endpoint_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.endpoint_toggle.toggled.connect(self._toggle_endpoint)
        self._icon_slots.append((self.endpoint_toggle, "chevron-right", 12, "mutedForeground"))
        row2.addWidget(self.endpoint_toggle)
        top.addLayout(row2)

        self.endpoint_box = QFrame()
        self.endpoint_box.setObjectName("endpointBox")
        self.endpoint_box.setVisible(False)
        ep = QHBoxLayout(self.endpoint_box)
        ep.setContentsMargins(12, 10, 12, 12)
        ep.setSpacing(10)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("http://host:port")
        self.base_url.editingFinished.connect(self._endpoint_edited)
        ep.addWidget(self._labelled("Base URL", self.base_url), 2)
        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("paste key")
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.editingFinished.connect(self._endpoint_edited)
        self.api_key_box = self._labelled("API key", self.api_key)
        ep.addWidget(self.api_key_box, 1)
        top.addWidget(self.endpoint_box)
        layout.addWidget(top_bar)

        # -- conversation ------------------------------------------------------
        self.chat_area = QScrollArea()
        self.chat_area.setWidgetResizable(True)
        self.chat_area.setObjectName("chatArea")
        self.chat_area.setFrameShape(QFrame.NoFrame)
        self.chat_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_widget = QWidget()
        self.chat_widget.setObjectName("chatSurface")
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(16, 18, 16, 18)
        self.chat_layout.setSpacing(24)
        # The hero takes the whole height while it is the only thing here
        # (stretch 1 vs a 0-stretch spacer); once turns arrive it is hidden
        # and the spacer keeps the turns pinned to the top.
        self.empty_hint = self._build_hero()
        self.chat_layout.addWidget(self.empty_hint, 1)
        self.chat_layout.addStretch(0)
        self.chat_area.setWidget(self.chat_widget)
        layout.addWidget(self.chat_area, 1)

        # -- composer ----------------------------------------------------------
        composer = QFrame()
        composer.setObjectName("aiInputBar")
        comp = QVBoxLayout(composer)
        comp.setContentsMargins(16, 12, 16, 12)
        comp.setSpacing(8)

        self.composer_card = QFrame()
        self.composer_card.setObjectName("composerCard")
        self.composer_card.setProperty("focused", "false")
        cc = QVBoxLayout(self.composer_card)
        cc.setContentsMargins(14, 12, 10, 8)
        cc.setSpacing(8)
        self.brief_input = BriefInput()
        self.brief_input.setObjectName("briefInput")
        self.brief_input.setFrameShape(QFrame.NoFrame)
        self.brief_input.setPlaceholderText("Describe the screen you want on the panel…")
        self.brief_input.submitted.connect(self._on_send)
        self.brief_input.installEventFilter(self)
        cc.addWidget(self.brief_input)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.auto_apply = QCheckBox("Auto-apply to canvas")
        self.auto_apply.setObjectName("autoApply")
        self.auto_apply.setCursor(Qt.PointingHandCursor)
        self.auto_apply.setChecked(True)
        self.auto_apply.toggled.connect(lambda on: self.settings.setValue("ai/autoApply", on))
        actions.addWidget(self.auto_apply)
        actions.addStretch(1)
        self.shortcut_hint = QLabel("Ctrl+Enter")
        self.shortcut_hint.setObjectName("kbdHint")
        actions.addWidget(self.shortcut_hint, 0, Qt.AlignVCenter)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("ghostAction")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_conversation)
        actions.addWidget(self.clear_btn)
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("sendButton")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setFixedSize(34, 34)
        self.send_btn.setToolTip("Generate (Ctrl+Enter)")
        self.send_btn.clicked.connect(self._on_send_or_stop)
        actions.addWidget(self.send_btn)
        cc.addLayout(actions)
        comp.addWidget(self.composer_card)
        layout.addWidget(composer)

        # -- session strip -----------------------------------------------------
        strip = QFrame()
        strip.setObjectName("sessionStrip")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(16, 6, 16, 6)
        sl.setSpacing(6)
        self.session_icon = QLabel()
        self.session_icon.setFixedSize(13, 13)
        self._icon_slots.append((self.session_icon, "activity", 13, "mutedForeground"))
        sl.addWidget(self.session_icon)
        self.session_lbl = QLabel("No runs yet")
        self.session_lbl.setObjectName("sessionLabel")
        sl.addWidget(self.session_lbl, 1)
        layout.addWidget(strip)

        # -- live canvas preview -----------------------------------------------
        self.split.addWidget(self._build_preview_pane())
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([460, 760])

        self._set_send_icon("player-play")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        # Commit the model on selection or when editing finishes -- not on
        # every keystroke, which wrote QSettings per character.
        self.model_combo.activated.connect(lambda _i: self._on_model_changed(self.model_combo.currentText()))
        self.model_combo.lineEdit().editingFinished.connect(
            lambda: self._on_model_changed(self.model_combo.currentText()))

    def _build_preview_pane(self) -> QWidget:
        """Right pane: a second view onto the Designer's scene, plus a header."""
        pane = QFrame()
        pane.setObjectName("previewPane")
        pane.setMinimumWidth(240)
        col = QVBoxLayout(pane)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        head = QFrame()
        head.setObjectName("previewHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(8)
        self.preview_icon = QLabel()
        self.preview_icon.setFixedSize(14, 14)
        self._icon_slots.append((self.preview_icon, "device-desktop", 14, "mutedForeground"))
        hl.addWidget(self.preview_icon)
        title = QLabel("Panel canvas")
        title.setObjectName("previewTitle")
        hl.addWidget(title)
        self.bezel_badge = QLabel("BEZEL VIEW")
        self.bezel_badge.setObjectName("bezelBadge")
        self.bezel_badge.setToolTip("The same physical FlyVi display bezel used by Designer")
        hl.addWidget(self.bezel_badge)
        hl.addStretch(1)
        self.preview_meta = QLabel("")
        self.preview_meta.setObjectName("previewMeta")
        hl.addWidget(self.preview_meta)
        self.open_designer_btn = QPushButton("Open in Designer")
        self.open_designer_btn.setObjectName("ghostAction")
        self.open_designer_btn.setCursor(Qt.PointingHandCursor)
        self.open_designer_btn.clicked.connect(self.canvasFocusRequested.emit)
        self._icon_slots.append((self.open_designer_btn, "arrow-up-right", 13, "mutedForeground"))
        hl.addWidget(self.open_designer_btn)
        col.addWidget(head)

        self.preview_view = PreviewView()
        col.addWidget(self.preview_view, 1)

        self.preview_placeholder = PreviewEmptyState()
        self._icon_slots.append((self.preview_placeholder.icon, "device-desktop", 22, "primary"))
        col.addWidget(self.preview_placeholder, 1)
        self.preview_view.setVisible(False)
        return pane

    def _refresh_preview_meta(self):
        project = getattr(self.workspace, "project", None)
        if project is None:
            self.preview_meta.setText("")
            return
        n = sum(1 for _ in project.all_widgets())
        self.preview_meta.setText(f"{int(project.screen.width)} × {int(project.screen.height)}"
                                  f"  ·  {n} widget{'s' if n != 1 else ''}")

    def _build_hero(self) -> QWidget:
        """Empty state: what this tab does, and three briefs to start from."""
        hero = QWidget()
        hero.setObjectName("hero")
        outer = QVBoxLayout(hero)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(3)
        # Everything sits in one column capped at a readable width and centred
        # by the stretches either side; the column itself expands up to the cap.
        column = QWidget()
        column.setObjectName("heroColumn")
        column.setMaximumWidth(440)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        col = QVBoxLayout(column)
        col.setContentsMargins(8, 0, 8, 0)
        col.setSpacing(0)
        self.hero_icon = QLabel()
        self.hero_icon.setObjectName("heroIcon")
        self.hero_icon.setFixedSize(60, 60)
        self.hero_icon.setAlignment(Qt.AlignCenter)
        self._icon_slots.append((self.hero_icon, "bolt", 28, "primary"))
        col.addWidget(self.hero_icon, 0, Qt.AlignHCenter)
        col.addSpacing(14)
        title = QLabel("Design with AI")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignCenter)
        col.addWidget(title)
        col.addSpacing(6)
        sub = QLabel("Describe a panel screen in plain words. The model drafts it directly "
                     "onto the physical panel bezel at right, ready for you to refine in Designer.")
        sub.setObjectName("heroSub")
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignCenter)
        col.addWidget(sub)
        col.addSpacing(24)
        kicker = QLabel("START FROM AN EXAMPLE")
        kicker.setObjectName("fieldCaption")
        kicker.setAlignment(Qt.AlignCenter)
        col.addWidget(kicker)
        col.addSpacing(10)
        for icon_name, label, blurb, brief in self.EXAMPLES:
            card = PromptCard(icon_name, label, blurb, brief)
            card.clicked.connect(self._use_example)
            self._icon_slots.append((card.icon, icon_name, 16, "primary"))
            self._icon_slots.append((card.arrow, "chevron-right", 14, "mutedForeground"))
            col.addWidget(card)
            col.addSpacing(6)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(column, 1)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(4)
        return hero

    def _use_example(self, brief: str):
        self.brief_input.setPlainText(brief)
        self.brief_input.setFocus()
        self.brief_input.moveCursor(QTextCursor.End)

    def _toggle_endpoint(self, on: bool):
        """Disclosure: chevron points right when closed, down when open."""
        self.endpoint_box.setVisible(on)
        name = "chevron-down" if on else "chevron-right"
        self._icon_slots = [(w, name if w is self.endpoint_toggle else n, sz, tk)
                            for (w, n, sz, tk) in self._icon_slots]
        self.endpoint_toggle.setIcon(_icon(name, 12, _token("mutedForeground", self._theme)))

    def eventFilter(self, obj, event):
        # Highlight the whole composer card while the brief has focus (no
        # :focus-within in QSS).
        if obj is self.brief_input and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.composer_card.setProperty("focused", "true" if event.type() == QEvent.FocusIn else "false")
            self.composer_card.style().unpolish(self.composer_card)
            self.composer_card.style().polish(self.composer_card)
        return super().eventFilter(obj, event)

    @staticmethod
    def _labelled(caption: str, widget: QWidget) -> QWidget:
        box = QWidget()
        box.setObjectName("fieldBox")
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        lbl = QLabel(caption.upper())
        lbl.setObjectName("fieldCaption")
        col.addWidget(lbl)
        col.addWidget(widget)
        return box

    def _set_send_icon(self, name: str):
        self._send_icon_name = name
        self.send_btn.setIcon(_icon(name, 16, _token("primaryForeground", self._theme)))
        self.send_btn.setIconSize(QSize(16, 16))

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def apply_theme(self, theme: str):
        """Re-skin from the Studio's shadcn tokens; called by the main window."""
        self._theme = theme
        t = lambda name: _token(name, theme)
        bg, card, border = t("background"), t("card"), t("border")
        fg, muted_fg, muted = t("foreground"), t("mutedForeground"), t("muted")
        primary, primary_fg = t("primary"), t("primaryForeground")
        success, warning, destructive, info = t("success"), t("warning"), t("destructive"), t("info")
        accent = t("accent")
        tint = lambda c, a: _rgba(c, a)
        dark = theme == "dark"
        # Surfaces: the console sits one step above the page so the chat reads
        # as a panel; cards inside it step up again.
        surface = card if dark else bg
        raised = tint(fg, 0.035) if dark else tint(fg, 0.025)
        hover = tint(fg, 0.06)
        mono = '"Cascadia Mono", Consolas, Menlo, "DejaVu Sans Mono", monospace'
        arrow = _icon_file("chevron-down", 12, muted_fg)
        primary_grad = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {tint(primary, 1.0)}, "
                        f"stop:1 {tint(info, 0.95)})")
        self.setStyleSheet(f"""
            QSplitter#aiSplitter::handle {{ background: {border}; }}
            QFrame#aiConsole {{ background: {surface}; }}
            QFrame#aiTopBar {{ background: {surface}; border-bottom: 1px solid {border}; }}
            QFrame#aiInputBar {{ background: {surface}; border-top: 1px solid {border}; }}
            QFrame#sessionStrip {{ background: {surface}; border-top: 1px solid {border}; }}
            QScrollArea#chatArea, QWidget#chatSurface {{ background: {surface}; border: none; }}
            QScrollArea#chatArea > QWidget > QWidget {{ background: {surface}; }}

            /* Layout-only containers: the Studio's global QWidget rule paints
               every plain widget in the page colour, which showed as grey
               slabs behind captions and inside the shell heads. */
            QWidget#fieldBox, QWidget#shellHead, QWidget#toolRow, QWidget#turn,
            QWidget#chipHost, QWidget#foldBody, QWidget#hero, QWidget#heroColumn,
            QWidget#variantStrip {{ background: transparent; }}

            /* -- variant strip: three quiet thumbnails, one click each ------ */
            QFrame#variantThumb {{ background: {raised}; border: 1px solid {border};
                                   border-radius: 8px; }}
            QFrame#variantThumb:hover {{ border-color: {primary}; background: {tint(primary, 0.08)}; }}
            QLabel#variantCaption {{ color: {muted_fg}; font-size: 10px; }}

            QLabel#fieldCaption {{ color: {muted_fg}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
            QLabel#sessionLabel, QLabel#toolMeta, QLabel#foldRight {{ color: {muted_fg}; font-size: 11px; }}
            QLabel#foldRight {{ font-family: {mono}; }}
            QLabel#kbdHint {{ color: {muted_fg}; font-size: 10px; font-family: {mono};
                              border: 1px solid {border}; border-radius: 5px; padding: 1px 5px; }}

            /* -- provider / model ------------------------------------------ */
            QComboBox#providerSelector, QComboBox#modelSelector, QFrame#endpointBox QLineEdit {{
                background: {raised}; border: 1px solid {border}; border-radius: 9px;
                padding: 0 10px; color: {fg}; font-size: 12px; min-height: 32px; max-height: 32px;
            }}
            QComboBox#providerSelector:hover, QComboBox#modelSelector:hover,
            QFrame#endpointBox QLineEdit:hover {{ border-color: {tint(primary, 0.55)}; }}
            QComboBox#providerSelector:focus, QComboBox#modelSelector:focus,
            QComboBox#modelSelector:on, QFrame#endpointBox QLineEdit:focus {{
                border: 1px solid {primary}; background: {tint(primary, 0.06)}; }}
            QComboBox#modelSelector QLineEdit {{ background: transparent; border: none; padding: 0;
                                                 color: {fg}; font-size: 12px; selection-background-color: {tint(primary, 0.35)}; }}
            QComboBox#providerSelector::drop-down, QComboBox#modelSelector::drop-down {{
                border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
            QComboBox#providerSelector::down-arrow, QComboBox#modelSelector::down-arrow {{
                image: url("{arrow}"); width: 12px; height: 12px; }}
            QComboBox#providerSelector QAbstractItemView, QComboBox#modelSelector QAbstractItemView {{
                background: {card}; color: {fg}; border: 1px solid {border}; border-radius: 8px;
                padding: 4px; outline: 0; selection-background-color: {tint(primary, 0.18)}; selection-color: {fg}; }}
            QFrame#endpointBox {{ background: {raised}; border: 1px solid {border}; border-radius: 10px; }}
            QToolButton#iconButton {{ background: {raised}; border: 1px solid {border}; border-radius: 9px;
                                      min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0; }}
            QToolButton#iconButton:hover {{ background: {hover}; border-color: {tint(primary, 0.55)}; }}
            QToolButton#iconButton:pressed {{ background: {tint(primary, 0.15)}; }}
            QToolButton#linkButton {{ background: transparent; border: none; border-radius: 6px;
                                      color: {muted_fg}; font-size: 11px; padding: 3px 6px; }}
            QToolButton#linkButton:hover {{ color: {fg}; background: {hover}; }}
            QToolButton#linkButton:checked {{ color: {fg}; }}

            QLabel#statusDot {{ border-radius: 4px; background: {muted_fg}; }}
            QLabel#statusDot[tone="ok"] {{ background: {success}; }}
            QLabel#statusDot[tone="fail"] {{ background: {destructive}; }}
            QLabel#statusDot[tone="busy"] {{ background: {info}; }}
            QLabel#connectionStatus {{ color: {muted_fg}; font-size: 11px; }}

            /* -- empty state ----------------------------------------------- */
            QLabel#heroIcon {{ background: {tint(primary, 0.14)}; border: 1px solid {tint(primary, 0.42)};
                               border-radius: 30px; }}
            QLabel#heroTitle {{ color: {fg}; font-size: 22px; font-weight: 600; letter-spacing: -0.5px; }}
            QLabel#heroSub {{ color: {muted_fg}; font-size: 12px; line-height: 150%; }}
            QFrame#promptCard {{ background: {raised}; border: 1px solid {border}; border-radius: 12px; }}
            QFrame#promptCard:hover {{ border-color: {tint(primary, 0.72)}; background: {tint(primary, 0.09)}; }}
            QLabel#promptCardIcon {{ background: {tint(primary, 0.14)}; border-radius: 8px; }}
            QLabel#promptCardTitle {{ color: {fg}; font-size: 12px; font-weight: 600; background: transparent; }}
            QLabel#promptCardBlurb {{ color: {muted_fg}; font-size: 11px; background: transparent; }}
            QLabel#promptCardMeta {{ color: {tint(primary, 0.9)}; font-size: 10px; font-weight: 600;
                                    background: transparent; padding-top: 2px; }}

            /* -- turns ------------------------------------------------------ */
            QLabel#userBubble {{ background: {primary_grad}; color: {primary_fg}; border: none;
                                 border-radius: 16px; border-bottom-right-radius: 5px;
                                 padding: 9px 14px; font-size: 13px; }}

            QFrame#executionShell {{ background: {raised}; border: 1px solid {border}; border-radius: 12px; }}
            QFrame#executionShell > QFrame#foldHead {{ background: transparent; border-radius: 12px; }}
            QFrame#executionShell > QFrame#foldHead:hover {{ background: {hover}; }}
            QFrame#foldBoxed {{ background: {surface}; border: 1px solid {border}; border-radius: 9px; }}
            QFrame#foldFlat {{ background: transparent; border: none; }}
            QFrame#foldHead {{ background: transparent; border-radius: 8px; }}
            QFrame#foldHead:hover {{ background: {hover}; }}
            QLabel#foldTitle {{ color: {fg}; font-size: 12px; font-weight: 500; }}
            QLabel#shellStatus {{ color: {fg}; font-size: 13px; font-weight: 500; }}
            QLabel#shellStatus[tone="ok"] {{ color: {success}; }}
            QLabel#shellStatus[tone="fail"] {{ color: {destructive}; }}
            QLabel#shellStatus[tone="warn"] {{ color: {warning}; }}
            QLabel#toolTitle {{ color: {fg}; font-size: 12px; }}
            QLabel#changesList {{ color: {fg}; font-family: {mono}; font-size: 11px; padding: 2px 4px; }}
            QPlainTextEdit#streamPane {{ background: {surface}; color: {tint(fg, 0.88)}; border: none;
                                         border-radius: 0; padding: 6px 8px; font-family: {mono}; font-size: 12px; }}

            QFrame#assistantCard {{ background: transparent; border: none; }}
            QLabel#assistantAvatar {{ background: {primary_grad}; border-radius: 13px; }}
            QLabel#conclusion {{ color: {fg}; font-size: 13px; }}

            QFrame#errorCard {{ background: {tint(destructive, 0.08)}; border: 1px solid {tint(destructive, 0.35)};
                                border-radius: 12px; }}
            QLabel#errorIcon {{ background: {tint(destructive, 0.16)}; border-radius: 14px; }}
            QLabel#errorTitle {{ color: {fg}; font-size: 13px; font-weight: 600; background: transparent; }}
            QLabel#errorText {{ color: {tint(fg, 0.85)}; font-size: 12px; background: transparent; }}

            QLabel#chip {{ background: {raised}; color: {muted_fg}; border-radius: 11px;
                           border: 1px solid {border}; padding: 2px 9px; font-size: 11px; min-height: 16px; }}
            QLabel#chip[tone="ok"] {{ color: {success}; background: {tint(success, 0.10)}; border-color: {tint(success, 0.35)}; }}
            QLabel#chip[tone="fail"] {{ color: {destructive}; background: {tint(destructive, 0.10)}; border-color: {tint(destructive, 0.35)}; }}
            QLabel#chip[tone="warn"] {{ color: {warning}; background: {tint(warning, 0.10)}; border-color: {tint(warning, 0.4)}; }}
            QLabel#chip[tone="info"] {{ color: {fg}; background: {tint(primary, 0.12)}; border-color: {tint(primary, 0.4)}; }}

            /* -- composer --------------------------------------------------- */
            QFrame#composerCard {{ background: {raised}; border: 1px solid {border}; border-radius: 16px; }}
            QFrame#composerCard[focused="true"] {{ border: 1px solid {primary}; background: {tint(primary, 0.07)}; }}
            QPlainTextEdit#briefInput {{ background: transparent; border: none; color: {fg}; font-size: 13px;
                                         font-family: inherit; padding: 0; selection-background-color: {tint(primary, 0.35)}; }}
            QPushButton#sendButton {{ background: {primary_grad}; border: none; border-radius: 17px; padding: 0;
                                      min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; }}
            QPushButton#sendButton:hover {{ background: {tint(primary, 0.85)}; }}
            QPushButton#sendButton:pressed {{ background: {tint(primary, 0.7)}; }}
            QPushButton#sendButton:disabled {{ background: {muted}; }}
            QPushButton#sendButton[stop="true"] {{ background: {destructive}; }}
            QPushButton#secondaryAction, QPushButton#ghostAction {{
                background: transparent; color: {fg}; border: 1px solid {border};
                border-radius: 8px; padding: 0 12px; font-size: 12px; font-weight: 500;
                min-height: 28px; max-height: 28px; height: 28px; }}
            QPushButton#ghostAction {{ border-color: transparent; color: {muted_fg}; }}
            QPushButton#secondaryAction:hover, QPushButton#ghostAction:hover {{
                background: {hover}; color: {fg}; border-color: {border}; }}
            QCheckBox#autoApply {{ color: {muted_fg}; font-size: 12px; spacing: 7px; background: transparent; }}
            QCheckBox#autoApply:hover {{ color: {fg}; }}
            QCheckBox#autoApply::indicator {{ width: 15px; height: 15px; border-radius: 5px;
                                              border: 1px solid {border}; background: {surface}; }}
            QCheckBox#autoApply::indicator:hover {{ border-color: {tint(primary, 0.6)}; }}
            QCheckBox#autoApply::indicator:checked {{ background: {primary}; border-color: {primary};
                                                      image: url("{_icon_file("check", 11, primary_fg)}"); }}

            /* -- canvas preview --------------------------------------------- */
            QFrame#previewPane {{ background: {bg}; }}
            QFrame#previewHead {{ background: {surface}; border-bottom: 1px solid {border}; }}
            QLabel#previewTitle {{ color: {fg}; font-size: 12px; font-weight: 600; background: transparent; }}
            QLabel#bezelBadge {{ color: {muted_fg}; font-size: 9px; font-weight: 600; letter-spacing: 0.8px;
                                  background: {tint(fg, 0.055)}; border: 1px solid {border}; border-radius: 5px;
                                  padding: 2px 5px; }}
            QLabel#previewMeta {{ color: {muted_fg}; font-size: 11px; font-family: {mono}; background: transparent; }}
            QGraphicsView#previewView {{ background: {bg}; border: none; }}
            QFrame#previewEmptyState {{ background: {bg}; border: none; }}
            QLabel#previewEmptyIcon {{ background: {tint(primary, 0.12)}; border: 1px solid {tint(primary, 0.35)};
                                      border-radius: 24px; }}
            QLabel#previewEmptyTitle {{ color: {fg}; font-size: 15px; font-weight: 600; background: transparent; }}
            QLabel#previewEmptyBody {{ color: {muted_fg}; font-size: 12px; line-height: 145%; background: transparent; }}
        """)
        for widget, name, size, token in self._icon_slots:
            pix = _icon(name, size, _token(token, theme))
            if isinstance(widget, QLabel):
                widget.setPixmap(pix.pixmap(size, size))
            else:
                widget.setIcon(pix)
                widget.setIconSize(QSize(size, size))
        self._set_send_icon(self._send_icon_name)
        self._render_status()
        for turn in self.turns:
            turn.retheme(theme)
        # Do not assign a view background brush here. The shared
        # ``DesignerScene`` owns its complete physical-panel rendering:
        # enclosure, logo, screen opening, grid and target caption. A view
        # brush masks that scene background, leaving only its foreground text
        # visible in the AI tab.
        self.preview_view.viewport().update()

    # ------------------------------------------------------------------
    # Provider / model / endpoint
    # ------------------------------------------------------------------

    def _load_defaults(self):
        self.auto_apply.setChecked(self.settings.value("ai/autoApply", True, type=bool))
        saved = self.settings.value("ai/provider", "", type=str)
        index = self.provider_combo.findData(saved) if saved else -1
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        # setCurrentIndex on the index the combo already sits at emits nothing,
        # so the connector must be configured explicitly once at start-up.
        if self.provider_combo.count():
            self._on_provider_changed(self.provider_combo.currentIndex())
        self.statusMessage.emit("AI Design tab ready")

    def _populate_providers(self):
        """Populate provider selector from connector presets."""
        if not self.connector:
            return
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        for preset in self.connector.get_provider_presets():
            self.provider_combo.addItem(preset["label"], preset["key"])
        self.provider_combo.blockSignals(False)

    def _current_provider_key(self) -> str:
        return self.provider_combo.currentData() or ""

    def _on_provider_changed(self, index: int):
        """Switch provider: rebuild the BYOK config from preset + saved overrides."""
        key = self.provider_combo.itemData(index)
        if not self.connector or not key:
            return
        preset = dict(BYOK_PRESETS.get(key, {}))
        preset["provider"] = key
        preset["baseUrl"] = self.settings.value(f"ai/baseUrl/{key}", preset.get("baseUrl", ""), type=str)
        preset["apiKey"] = self.settings.value(f"ai/apiKey/{key}", "", type=str)
        preset["model"] = self.settings.value(f"ai/model/{key}", (preset.get("models") or [""])[0], type=str)
        self.connector.mode = "byok"
        self.connector.byok = ProviderConfig.from_dict(preset)
        self.settings.setValue("ai/provider", key)

        self.base_url.setText(preset["baseUrl"])
        self.api_key.setText(preset["apiKey"])
        self.api_key_box.setVisible(bool(preset.get("requiresApiKey")) or bool(preset["apiKey"]))

        self._probe_models = []
        self._probe_ok = None
        self._fill_models(preset["model"])
        self._render_status("Not checked")
        self.probe_connection()

    def _fill_models(self, current: str):
        """Preset models first, then anything the endpoint actually serves."""
        models = list(self.connector.discover_models()) if self.connector else []
        ids = [m.id for m in models]
        for mid in self._probe_models:
            if mid not in ids:
                ids.append(mid)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for mid in ids:
            self.model_combo.addItem(mid, mid)
        if current and current not in ids:
            self.model_combo.addItem(current, current)
        self.model_combo.setCurrentText(current or (ids[0] if ids else ""))
        # A long id ("nvidia/Qwen3.6-35B…") otherwise scrolls to its tail and
        # the vendor prefix is what disappears.
        self.model_combo.lineEdit().setCursorPosition(0)
        self.model_combo.blockSignals(False)

    def _on_model_changed(self, text: str):
        if not self.connector or not self.connector.byok:
            return
        self.connector.byok.model = text.strip()
        self.settings.setValue(f"ai/model/{self._current_provider_key()}", text.strip())

    def _endpoint_edited(self):
        if not self.connector or not self.connector.byok:
            return
        key = self._current_provider_key()
        self.connector.byok.baseUrl = self.base_url.text().strip()
        self.connector.byok.apiKey = self.api_key.text().strip()
        self.settings.setValue(f"ai/baseUrl/{key}", self.connector.byok.baseUrl)
        self.settings.setValue(f"ai/apiKey/{key}", self.connector.byok.apiKey)
        self.probe_connection()

    # ------------------------------------------------------------------
    # Connection probe
    # ------------------------------------------------------------------

    def probe_connection(self):
        if not self.connector:
            return
        if self._probe is not None and self._probe.isRunning():
            # The endpoint changed under a probe in flight: its answer is for
            # the old endpoint, so discard it and run again when it returns.
            self._probe_pending = True
            self._render_status("Checking…", checking=True)
            return
        self._probe_pending = False
        self._render_status("Checking…", checking=True)
        self._probe = ProbeWorker(self.connector, self)
        self._probe.result.connect(self._on_probe_result)
        self._probe.start()

    def _on_probe_result(self, result: dict):
        if self._probe_pending:
            self._probe.wait(100)
            self.probe_connection()
            return
        self._probe_ok = bool(result.get("ok"))
        model = self.connector.byok.model if self.connector and self.connector.byok else ""
        served = result.get("models") or []
        if self._probe_ok:
            text = f"Connected · {result.get('detail', '')} · {result.get('latency_ms', 0):.0f} ms"
            if served:
                text += f" · {len(served)} models"
                if model and model not in served:
                    text += f" · '{model}' not listed"
            self._probe_models = served
            self._fill_models(self.model_combo.currentText())
        else:
            text = f"Not connected · {result.get('detail', 'unreachable')}"
        self._render_status(text)
        self.statusMessage.emit(f"AI provider: {text}")

    def _render_status(self, text: str = None, checking: bool = False):
        if text is not None:
            self.status_lbl.setText(text)
        if checking:
            tone = "busy"
        elif self._probe_ok is None:
            tone = "neutral"
        elif self._probe_ok:
            tone = "ok"
        else:
            tone = "fail"
        self.status_dot.setProperty("tone", tone)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

    # ------------------------------------------------------------------
    # Canvas hookup
    # ------------------------------------------------------------------

    def set_workspace(self, workspace):
        """Give the tab the Designer so diffs and screen size are real, and
        show its scene in the preview pane."""
        self.workspace = workspace
        scene = getattr(workspace, "scene", None)
        if scene is not None:
            self.preview_view.attach(scene)
            scene.sceneRectChanged.connect(lambda _r: self._refresh_preview_meta())
            scene.changed.connect(lambda _regions: self._refresh_preview_meta())
            self.preview_placeholder.setVisible(False)
            self.preview_view.setVisible(True)
        self._refresh_preview_meta()

    def _screen_size(self):
        project = getattr(self.workspace, "project", None)
        if project is not None:
            return int(project.screen.width), int(project.screen.height)
        return 1280, 800

    def _canvas_project(self):
        return getattr(self.workspace, "project", None) or self.last_project

    def apply_to_canvas(self, designer_workspace=None, project=None, focus=False) -> str:
        """Apply a generated design to the canvas (button or auto-apply).

        Loading the project only redraws the Designer canvas; the live panel
        preview on the left re-renders through the Designer's own Preview
        path (generate QML -> reload bundle).  With no application bundle
        open the Designer provisions one for the design, so the hand-over
        needs no prior setup.  Returns what happened, for the chips:
        ``"previewed"`` | ``"applied"`` | ``"no-workspace"``.
        """
        project = project or self.last_project
        if project is None:
            QMessageBox.information(self, "No Design", "Generate a design first.")
            return "no-workspace"
        workspace = designer_workspace or self.workspace
        outcome = "no-workspace"
        if workspace is not None and hasattr(workspace, "load_project"):
            workspace.load_project(project)
            outcome = "applied"
            if hasattr(workspace, "preview") and (
                    getattr(workspace, "bundle_dir", "") or hasattr(workspace, "ensure_bundle")):
                if workspace.preview() is not False:
                    outcome = "previewed"
        self.preview_view.refit()
        self._refresh_preview_meta()
        self.generateRequested.emit(project)
        if focus:
            self.canvasFocusRequested.emit()
        return outcome

    def _variant_renderer(self):
        """The panel's renderer for the thumbnails, or None when there is none."""
        if self._variant_renderer_cache is not None:
            return self._variant_renderer_cache or None
        try:
            from designer.preview import NativeRenderer
            renderer = NativeRenderer()
        except Exception:
            renderer = None
        if renderer is None or not getattr(renderer, "available", False):
            self._variant_renderer_cache = False
            return None
        self._variant_renderer_cache = renderer
        return renderer

    def _offer_variants(self, turn, project):
        """Show the other compositions of this section as thumbnails.

        Drawn by hmi-ui itself, so what is offered is what the glass will
        show. Without the binary there is nothing honest to show: the strip
        is skipped and the turn reads exactly as it did before.
        """
        renderer = self._variant_renderer()
        if renderer is None or project is None or not project.pages:
            return
        try:
            from designer.layout.polish import polish_candidates
            registry = getattr(self.generator, "registry", None)
            page = project.pages[0]
            items = []
            for candidate, verdict, archetype in polish_candidates(
                    project, page, registry, brief=self._root_brief, limit=3):
                variant = copy.deepcopy(project)
                variant.pages[0] = candidate
                image = renderer.render_page_sync(variant, candidate, variant.screen.theme)
                if image is None or image.isNull():
                    continue
                items.append((archetype, verdict.score, image, variant))
            if len(items) < 2:
                return
            turn.show_variants(items)
        except Exception:
            return      # a variant strip is a courtesy; it never breaks a turn

    def _take_variant(self, project):
        """A thumbnail was clicked: that composition becomes the canvas."""
        if project is None:
            return
        self.last_project = project
        self.apply_to_canvas(project=project)
        self.statusMessage.emit("AI Design: composition applied to the canvas")

    def set_last_project(self, project):
        self.last_project = project

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _on_send_or_stop(self):
        if self.streaming:
            self.stop_generation()
        else:
            self._on_send()

    def stop_generation(self):
        if self.connector and self.streaming:
            self._queued_section_request = None
            self.connector.cancel()
            self.send_btn.setEnabled(False)
            self.send_btn.setToolTip("Stopping\u2026")

    def _on_send(self):
        brief = self.brief_input.toPlainText().strip()
        if not brief or self.streaming:
            return
        self._root_brief = brief
        self._section_run = 1
        self._section_project = None
        self._queued_section_request = None
        request = f"{brief}\n\n{self.SECTION_REQUEST}"
        self._start_generation(request, brief)

    def _start_generation(self, brief: str, display_brief: str):
        """Start one user or automatic section request."""
        if not self.connector:
            QMessageBox.warning(self, "AI Design", "No connector configured. Check provider settings.")
            return
        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.warning(self, "AI Design", "Pick or type a model name first.")
            return

        self.brief_input.setPlainText("")
        self.empty_hint.setVisible(False)
        turn = TurnWidget(display_brief)
        turn.request_text = brief
        turn.retheme(self._theme)
        turn.applyRequested.connect(lambda project: self.apply_to_canvas(project=project, focus=True))
        turn.variantPicked.connect(self._take_variant)
        turn.editRequested.connect(self._use_example)
        self.turns.append(turn)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, turn)
        self._scroll_to_bottom()

        width, height = self._screen_size()
        registry = getattr(self.generator, "registry", None)
        self.connector.system_prompt = build_system_prompt(registry, width, height, brief=self._root_brief)
        # The brief picks the composition archetype when the section is polished.
        if self.generator is not None:
            self.generator.brief = self._root_brief

        self.streaming = True
        self.send_btn.setToolTip("Stop")
        self.send_btn.setProperty("stop", "true")
        self.send_btn.style().unpolish(self.send_btn); self.send_btn.style().polish(self.send_btn)
        self._set_send_icon("player-stop")
        self.statusMessage.emit(f"AI Design: generating with {model}")

        # Bound-method slots so PySide queues the calls onto the UI thread;
        # a lambda would run on the worker thread and touch widgets there.
        self._active_turn = turn
        self._worker = GenerationWorker(self.connector, brief, model, self)
        self._worker.event.connect(self._on_worker_event)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _queue_next_section(self, label: str = "", truncated: bool = False) -> bool:
        """Schedule the next bounded section after the current worker exits."""
        if self._section_run >= self.MAX_SECTION_RUNS:
            return False
        next_run = self._section_run + 1
        target = label or "the next unfinished part of the screen"
        reason = ("The previous response reached its output limit. " if truncated else "")
        implemented = []
        if self._section_project is not None:
            implemented = [widget.id for widget in self._section_project.all_widgets()]
        implemented_text = ", ".join(implemented) if implemented else "none"
        request = (
            f"Original brief: {self._root_brief}\n"
            f"Already implemented widget ids: {implemented_text}\n\n"
            f"{reason}Continue the same design with section {next_run}: {target}. "
            "Return one complete, valid JSON design section with at most 8 widgets. "
            "Do not repeat widgets already emitted. Keep every id globally unique. "
            "Set section.complete=true only when the whole requested design is finished; "
            "otherwise name the next section in section.next."
        )
        self._queued_section_request = (
            request,
            f"Continue · Section {next_run}" + (f" · {label}" if label else ""),
        )
        return True

    def _on_worker_event(self, ev: dict):
        if self._active_turn is not None:
            self._on_event(self._active_turn, ev)

    def _on_event(self, turn: TurnWidget, ev: dict):
        shell = turn.shell
        kind = ev.get("type")
        if kind == "start":
            shell.note_request(ev.get("provider", ""), ev.get("model", ""), ev.get("url", ""),
                               getattr(turn, "request_text", turn.bubble.text()), ev.get("mode", ""))
            if self._probe_ok is None:
                self._render_status("Connecting…")
        elif kind == "status":
            shell.note_status(ev.get("label", ""))
        elif kind == "thinking_start":
            shell.set_status("thinking")
        elif kind == "thinking":
            shell.append_thinking(ev.get("delta", ""))
        elif kind == "thinking_tokens":
            shell.note_thinking_tokens(ev.get("tokens"))
        elif kind == "delta":
            shell.append_delta(ev.get("delta", ""))
            if self._probe_ok is not True:
                self._probe_ok = True
                self._render_status("Connected · streaming")
        elif kind in ("tool_use", "tool_result"):
            shell.note_tool(ev)
        elif kind == "usage":
            shell.note_usage(ev)
        elif kind == "error":
            shell.note_error(ev.get("message", "unknown error"))
            if self._probe_ok is None or "reach" in ev.get("message", "").lower():
                self._probe_ok = False
                self._render_status("Not connected · " + ev.get("message", "")[:80])
        elif kind == "turn_end":
            self._conclude_turn(turn, stopped=bool(ev.get("stopped")))
        self._scroll_to_bottom()

    def _conclude_turn(self, turn: TurnWidget, stopped: bool):
        shell = turn.shell
        full_text = shell.response_pane.toPlainText() if shell.response_pane is not None else ""
        failed = shell.error_row is not None and not full_text
        error_message = shell.error_row.title.text() if shell.error_row is not None else ""

        project, chips = None, []
        if stopped:
            shell.finish("stopped")
        elif failed:
            shell.finish("failed")
        else:
            shell.set_status("parsing")
            width, height = self._screen_size()
            try:
                project = self.generator.generate(full_text, width, height) if self.generator else None
            except Exception as exc:
                project = None
                shell.note_error(f"Parse error: {exc}")
            summary = summarize_widgets(project) if project is not None else ""
            shell.note_parse(project, summary)
            if project is not None:
                shell.note_polish(getattr(self.generator, "last_polish", None))
                sectioned = hasattr(project, "_section_complete") or bool(getattr(project, "_truncated", False))
                section_index = int(getattr(project, "_section_index", self._section_run) or self._section_run)
                section_label = str(getattr(project, "_section_label", "") or "").strip()
                section_next = str(getattr(project, "_next_section", "") or "").strip()
                section_complete = bool(getattr(project, "_section_complete", True))
                was_truncated = shell.truncated or bool(getattr(project, "_truncated", False))
                if sectioned:
                    project = (project if self._section_project is None
                               else merge_project_section(self._section_project, project))
                    self._section_project = project
                diff = diff_projects(self._canvas_project(), project)
                applied = self.auto_apply.isChecked()
                shell.note_changes(diff, applied)
                self.last_project = project
                n = sum(1 for _ in project.all_widgets())
                if sectioned:
                    label = f"Section {section_index}" + (f" · {section_label}" if section_label else "")
                    chips.append((label, "info"))
                chips.append((f"{n} widget{'s' if n != 1 else ''}", "info"))
                chips.append((f"+{len(diff['added'])} \u2212{len(diff['removed'])} ~{len(diff['changed'])}", "neutral"))
                if applied:
                    outcome = self.apply_to_canvas(project=project)
                    if outcome == "previewed":
                        chips.append(("Applied · panel preview refreshed", "ok"))
                    else:
                        chips.append(("Applied to canvas", "ok"))
                        chips.append(("Panel preview not refreshed", "warn"))
                    self._offer_variants(turn, project)
                if sectioned and (was_truncated or not section_complete):
                    if self._queue_next_section(section_next, truncated=was_truncated):
                        chips.append(("Applied · continuing automatically", "warn"))
                    else:
                        chips.append((f"Stopped after {self.MAX_SECTION_RUNS} sections", "warn"))
                        turn.show_error("Automatic continuation paused.",
                                        "Review the canvas, then send a new brief to continue.")
            else:
                if shell.truncated:
                    if self._queue_next_section(truncated=True):
                        chips.append(("Section incomplete · retrying automatically", "warn"))
                    else:
                        chips.append(("No design parsed", "fail"))
                        turn.show_error("Automatic continuation paused.",
                                        "Review the canvas, then send a new brief to continue.")
                elif full_text.strip():
                    chips.append(("No design parsed", "fail"))
                    turn.show_error("The model answered, but no design payload could be parsed from it.",
                                    "Open the Response fold above to see what came back.",
                                    ["Rephrase the brief and ask for a JSON design explicitly.",
                                     "Try a larger or instruction-tuned model."])
                else:
                    chips.append(("No design parsed", "fail"))
                    turn.show_error("The model returned nothing.",
                                    "Check the connection status and the model name, then try again.")
            shell.finish("done" if project is not None or self._queued_section_request else "failed")

        if stopped:
            chips.append(("Cancelled", "warn"))
        elif failed:
            chips.append(("Failed", "fail"))
            hint = ""
            low = error_message.lower()
            if "cannot reach" in low or "unreachable" in low:
                hint = "The endpoint is not answering. Check Endpoint > Base URL, and that the server is running."
            elif "api key" in low or "401" in low or "403" in low:
                hint = "Open Endpoint and paste a valid API key for this provider."
            elif "404" in low:
                hint = "The model name is not served at this endpoint. Press refresh to list what is."
            turn.show_error(error_message, hint)
        m = shell.metrics()
        tokens = format_tokens(m["total_tokens"] or m["output_tokens"], estimated=m["output_estimated"])
        cost = [f"{tokens} tok" if tokens else None, format_rate(m["rate"]),
                format_elapsed(m["elapsed_ms"]) if m["elapsed_ms"] >= 1000 else None]
        cost = " · ".join(c for c in cost if c)
        if cost:
            chips.append((cost, "neutral"))
        turn.conclude(project, conclusion_prose(full_text), chips)
        # OpenDesign folds the record once the conclusion lands; the reader can reopen it.
        shell.set_lifecycle_open(False)
        self._account_session(m, stopped or failed)

    def _account_session(self, m: dict, aborted: bool):
        s = self.session
        s["runs"] += 1
        s["input_tokens"] += m["input_tokens"] or 0
        s["output_tokens"] += m["output_tokens"] or 0
        s["estimated"] = s["estimated"] or bool(m["output_estimated"])
        if m["rate"]:
            s["last_rate"] = m["rate"]
        total = s["input_tokens"] + s["output_tokens"]
        parts = [f"{s['runs']} run{'s' if s['runs'] != 1 else ''}"]
        if total:
            parts.append(f"{format_tokens(total, estimated=s['estimated'])} tokens "
                         f"({format_tokens(s['input_tokens']) or 0} in / "
                         f"{format_tokens(s['output_tokens'], estimated=s['estimated']) or 0} out)")
        if s["last_rate"]:
            parts.append(format_rate(s["last_rate"]))
        self.session_lbl.setText("  ·  ".join(parts))
        self.statusMessage.emit("AI Design: " + ("run aborted" if aborted else "generation complete"))

    def _on_worker_done(self):
        self.streaming = False
        self._worker = None
        self._active_turn = None
        self.send_btn.setEnabled(True)
        self.send_btn.setToolTip("Generate (Ctrl+Enter)")
        self.send_btn.setProperty("stop", "false")
        self.send_btn.style().unpolish(self.send_btn); self.send_btn.style().polish(self.send_btn)
        self._set_send_icon("player-play")
        # A turn whose worker died before turn_end still needs closing out.
        for turn in self.turns:
            if turn.shell.running:
                self._conclude_turn(turn, stopped=True)
        queued, self._queued_section_request = self._queued_section_request, None
        if queued:
            self._section_run += 1
            request, display = queued
            self._start_generation(request, display)

    # ------------------------------------------------------------------
    # Conversation housekeeping
    # ------------------------------------------------------------------

    def clear_conversation(self):
        if self.streaming:
            return
        self._queued_section_request = None
        self._section_run = 0
        self._section_project = None
        self._root_brief = ""
        for turn in self.turns:
            self.chat_layout.removeWidget(turn)
            turn.deleteLater()
        self.turns.clear()
        if self.connector:
            self.connector.conversation.clear()
        self.empty_hint.setVisible(True)

    def add_message(self, role: str, content: str):
        """Compatibility shim: a system/assistant note rendered as a conclusion."""
        note = QLabel(content)
        note.setObjectName("conclusion")
        note.setWordWrap(True)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, note)
        self._scroll_to_bottom()
        return note

    def _scroll_to_bottom(self):
        bar = self.chat_area.verticalScrollBar()
        # Follow only if the reader is already near the tail (OpenDesign's
        # thinking-follow rule): scrolling up to read must not be yanked back.
        if bar.maximum() - bar.value() < 160:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
