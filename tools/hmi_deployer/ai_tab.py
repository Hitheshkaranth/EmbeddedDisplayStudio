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
import re
import time

from PySide6.QtCore import Qt, Signal, QTimer, QThread, QSettings, QSize, QEvent, QRectF, QPointF, QRect, QPoint
from PySide6.QtGui import (
    QFont, QTextCursor, QKeyEvent, QPainter, QPen, QColor, QConicalGradient,
    QLinearGradient, QBrush,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget, QMessageBox,
)

from tools.hmi_deployer.ai_design import BYOK_PRESETS, ProviderConfig
from tools.hmi_deployer.ai_generator import (
    build_system_prompt, diff_projects, summarize_widgets,
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
            self._add_row(ToolRow("alert-triangle",
                                  "Output hit the token limit -- the design may be incomplete; "
                                  "ask for a smaller screen or raise the budget", "", "stopped"))
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
# Turn = brief + shell + conclusion
# ---------------------------------------------------------------------------

class TurnWidget(QWidget):
    applyRequested = Signal(object)

    def __init__(self, brief: str, parent=None):
        super().__init__(parent)
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
        self.bubble.setMaximumWidth(520)
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
        self.avatar.setFixedSize(28, 28)
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
        self.chip_row = FlowLayout(self.chip_host)
        body.addWidget(self.chip_host)
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
        ec.setContentsMargins(12, 10, 12, 10)
        ec.setSpacing(10)
        self.error_icon = QLabel()
        self.error_icon.setFixedSize(16, 16)
        ec.addWidget(self.error_icon, 0, Qt.AlignTop)
        self.error_text = QLabel("")
        self.error_text.setObjectName("errorText")
        self.error_text.setWordWrap(True)
        self.error_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ec.addWidget(self.error_text, 1)
        col.addWidget(self.error_card)
        self._render_avatar()

    def show_error(self, message: str, hint: str = ""):
        text = message if not hint else f"{message}\n{hint}"
        self.error_text.setText(text)
        self.error_icon.setPixmap(_icon("alert-triangle", 16, _token("destructive", self._theme)).pixmap(16, 16))
        self.error_card.setVisible(True)

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
        self.card.setVisible(bool(prose) or bool(chips))

    def retheme(self, theme):
        self._theme = theme
        self.shell.retheme(theme)
        self._render_avatar()
        if self.error_card.isVisible():
            self.error_icon.setPixmap(_icon("alert-triangle", 16, _token("destructive", theme)).pixmap(16, 16))
        if self.apply_btn.isVisible():
            self.apply_btn.setIcon(_icon("device-desktop", 14, _token("foreground", theme)))

    def _render_avatar(self):
        self.avatar.setPixmap(_icon("bolt", 15, _token("primaryForeground", self._theme)).pixmap(15, 15))


# ---------------------------------------------------------------------------
# Composer input: Ctrl+Enter sends
# ---------------------------------------------------------------------------

class BriefInput(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

class AIDesignTab(QWidget):
    """AI-powered design tab: model picker, generation console, canvas hand-off."""

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
        ("Engine dashboard",
         "Engine dashboard: large RPM gauge bound to eng.rpm, coolant and oil temperature gauges "
         "(eng.coolant_c, eng.oil_c), a fuel level bar, Start/Stop buttons and a status strip."),
        ("Alarm overview",
         "Alarm overview page: full-width alarm table bound to plc.alarms, an acknowledge-all "
         "button, and four annunciator tiles for the highest-priority faults."),
        ("Pump control",
         "Pump control screen: two pump cards side by side, each with a run toggle, a flow "
         "numeric display bound to pump.N.flow, a pressure gauge and a running status dot."),
    ]

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- top bar: provider / model / connection ---------------------------
        top_bar = QFrame()
        top_bar.setObjectName("aiTopBar")
        top = QVBoxLayout(top_bar)
        top.setContentsMargins(14, 12, 14, 10)
        top.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("providerSelector")
        self.provider_combo.setMinimumWidth(150)
        self.provider_combo.setCursor(Qt.PointingHandCursor)
        row1.addWidget(self._labelled("Provider", self.provider_combo))

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("modelSelector")
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row1.addWidget(self._labelled("Model", self.model_combo), 1)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setObjectName("iconButton")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setToolTip("Test the connection and refresh the model list")
        self.refresh_btn.clicked.connect(self.probe_connection)
        self._icon_slots.append((self.refresh_btn, "refresh", 15, "foreground"))
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
        ep.setContentsMargins(10, 8, 10, 10)
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
        self.chat_layout.setSpacing(22)
        self.chat_layout.addStretch(1)
        self.chat_area.setWidget(self.chat_widget)
        layout.addWidget(self.chat_area, 1)

        self.empty_hint = self._build_hero()
        self.chat_layout.insertWidget(0, self.empty_hint)

        # -- composer ----------------------------------------------------------
        composer = QFrame()
        composer.setObjectName("aiInputBar")
        comp = QVBoxLayout(composer)
        comp.setContentsMargins(14, 12, 14, 10)
        comp.setSpacing(8)

        self.composer_card = QFrame()
        self.composer_card.setObjectName("composerCard")
        self.composer_card.setProperty("focused", "false")
        cc = QVBoxLayout(self.composer_card)
        cc.setContentsMargins(12, 10, 10, 8)
        cc.setSpacing(6)
        self.brief_input = BriefInput()
        self.brief_input.setObjectName("briefInput")
        self.brief_input.setFrameShape(QFrame.NoFrame)
        self.brief_input.setPlaceholderText("Describe the screen you want on the panel\u2026  Ctrl+Enter to send")
        self.brief_input.setMaximumHeight(84)
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
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("ghostAction")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_conversation)
        actions.addWidget(self.clear_btn)
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("sendButton")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setFixedSize(36, 36)
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
        sl.setContentsMargins(14, 6, 14, 6)
        sl.setSpacing(6)
        self.session_icon = QLabel()
        self.session_icon.setFixedSize(13, 13)
        self._icon_slots.append((self.session_icon, "activity", 13, "mutedForeground"))
        sl.addWidget(self.session_icon)
        self.session_lbl = QLabel("No runs yet")
        self.session_lbl.setObjectName("sessionLabel")
        sl.addWidget(self.session_lbl, 1)
        layout.addWidget(strip)

        self._set_send_icon("player-play")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        # Commit the model on selection or when editing finishes -- not on
        # every keystroke, which wrote QSettings per character.
        self.model_combo.activated.connect(lambda _i: self._on_model_changed(self.model_combo.currentText()))
        self.model_combo.lineEdit().editingFinished.connect(
            lambda: self._on_model_changed(self.model_combo.currentText()))

    def _build_hero(self) -> QWidget:
        """Empty state: what this tab does, and three briefs to start from."""
        hero = QWidget()
        hero.setObjectName("hero")
        col = QVBoxLayout(hero)
        col.setContentsMargins(24, 36, 24, 24)
        col.setSpacing(10)
        self.hero_icon = QLabel()
        self.hero_icon.setObjectName("heroIcon")
        self.hero_icon.setFixedSize(56, 56)
        self.hero_icon.setAlignment(Qt.AlignCenter)
        self._icon_slots.append((self.hero_icon, "bolt", 26, "primary"))
        col.addWidget(self.hero_icon, 0, Qt.AlignHCenter)
        title = QLabel("Design with AI")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignCenter)
        col.addWidget(title)
        sub = QLabel("Describe a panel screen in plain words. The model drafts it onto the "
                     "Designer canvas, and the run log shows its reasoning, the streamed "
                     "answer, what changed and what it cost.")
        sub.setObjectName("heroSub")
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignCenter)
        col.addWidget(sub)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addStretch(1)
        for label, brief in self.EXAMPLES:
            btn = QPushButton(label)
            btn.setObjectName("promptChip")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(brief)
            btn.clicked.connect(lambda _=False, b=brief: self._use_example(b))
            chips.addWidget(btn)
        chips.addStretch(1)
        col.addSpacing(6)
        col.addLayout(chips)
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
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
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
        mono = '"Cascadia Mono", Consolas, Menlo, "DejaVu Sans Mono", monospace'
        self.setStyleSheet(f"""
            QFrame#aiTopBar {{ background: {card}; border-bottom: 1px solid {border}; }}
            QFrame#aiInputBar {{ background: {card}; border-top: 1px solid {border}; }}
            QFrame#sessionStrip {{ background: {card}; border-top: 1px solid {border}; }}
            QScrollArea#chatArea, QWidget#chatSurface {{ background: {bg}; }}

            QLabel#fieldCaption {{ color: {muted_fg}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
            QLabel#sessionLabel, QLabel#toolMeta, QLabel#foldRight {{
                color: {muted_fg}; font-size: 11px; }}
            QLabel#foldRight {{ font-family: {mono}; }}

            QComboBox#providerSelector, QComboBox#modelSelector, QFrame#endpointBox QLineEdit {{
                background: {bg}; border: 1px solid {border}; border-radius: 8px;
                padding: 5px 10px; color: {fg}; font-size: 12px; min-height: 24px;
            }}
            QComboBox#providerSelector:hover, QComboBox#modelSelector:hover {{ border-color: {tint(primary, 0.55)}; }}
            QComboBox#providerSelector:focus, QComboBox#modelSelector:focus,
            QFrame#endpointBox QLineEdit:focus {{ border-color: {primary}; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QFrame#endpointBox {{ background: {tint(fg, 0.03)}; border: 1px solid {border}; border-radius: 10px; }}
            QToolButton#iconButton {{ background: {bg}; border: 1px solid {border}; border-radius: 8px;
                                      min-width: 32px; min-height: 32px; }}
            QToolButton#iconButton:hover {{ background: {accent}; border-color: {tint(primary, 0.55)}; }}
            QToolButton#linkButton {{ background: transparent; border: none; color: {muted_fg};
                                      font-size: 11px; padding: 2px 4px; }}
            QToolButton#linkButton:hover, QToolButton#linkButton:checked {{ color: {fg}; }}

            QLabel#statusDot {{ border-radius: 4px; background: {muted_fg}; }}
            QLabel#statusDot[tone="ok"] {{ background: {success}; }}
            QLabel#statusDot[tone="fail"] {{ background: {destructive}; }}
            QLabel#statusDot[tone="busy"] {{ background: {info}; }}
            QLabel#connectionStatus {{ color: {muted_fg}; font-size: 11px; }}

            QWidget#hero {{ background: transparent; }}
            QLabel#heroIcon {{ background: {tint(primary, 0.14)}; border: 1px solid {tint(primary, 0.35)};
                               border-radius: 28px; }}
            QLabel#heroTitle {{ color: {fg}; font-size: 18px; font-weight: 600; }}
            QLabel#heroSub {{ color: {muted_fg}; font-size: 12px; }}
            QPushButton#promptChip {{ background: {card}; color: {fg}; border: 1px solid {border};
                                      border-radius: 14px; padding: 4px 12px; font-size: 12px;
                                      font-weight: 400; height: 18px; min-height: 18px; max-height: 18px; }}
            QPushButton#promptChip:hover {{ border-color: {primary}; background: {tint(primary, 0.10)}; }}

            QLabel#userBubble {{ background: {tint(primary, 0.12)}; color: {fg}; border: none;
                                 border-radius: 14px; padding: 9px 13px; font-size: 13px; }}

            QFrame#executionShell {{ background: {card}; border: 1px solid {border}; border-radius: 12px; }}
            QFrame#executionShell > QFrame#foldHead {{ background: transparent; border-radius: 12px; }}
            QFrame#executionShell > QFrame#foldHead:hover {{ background: {tint(fg, 0.04)}; }}
            QFrame#foldBoxed {{ background: {bg}; border: 1px solid {border}; border-radius: 9px; }}
            QFrame#foldFlat {{ background: transparent; border: none; }}
            QFrame#foldHead {{ background: transparent; border-radius: 8px; }}
            QFrame#foldHead:hover {{ background: {tint(fg, 0.05)}; }}
            QLabel#foldTitle {{ color: {fg}; font-size: 12px; font-weight: 500; }}
            QLabel#shellStatus {{ color: {fg}; font-size: 13px; font-weight: 500; }}
            QLabel#shellStatus[tone="ok"] {{ color: {success}; }}
            QLabel#shellStatus[tone="fail"] {{ color: {destructive}; }}
            QLabel#shellStatus[tone="warn"] {{ color: {warning}; }}
            QLabel#toolTitle {{ color: {fg}; font-size: 12px; }}
            QLabel#changesList {{ color: {fg}; font-family: {mono}; font-size: 11px; padding: 2px 4px; }}
            QPlainTextEdit#streamPane {{ background: {bg}; color: {tint(fg, 0.88)}; border: none; padding: 6px 8px;
                                         font-family: {mono}; font-size: 12px; }}

            QFrame#assistantCard {{ background: transparent; border: none; }}
            QFrame#errorCard {{ background: {tint(destructive, 0.10)}; border: 1px solid {tint(destructive, 0.40)};
                                border-radius: 12px; }}
            QLabel#errorText {{ color: {fg}; font-size: 12px; }}
            QLabel#assistantAvatar {{ background: {primary}; border-radius: 14px; }}
            QLabel#conclusion {{ color: {fg}; font-size: 13px; }}

            QLabel#chip {{ background: transparent; color: {muted_fg}; border-radius: 11px;
                           border: 1px solid {border}; padding: 2px 9px; font-size: 11px;
                           min-height: 16px; }}
            QLabel#chip[tone="ok"] {{ color: {success}; border-color: {tint(success, 0.45)}; }}
            QLabel#chip[tone="fail"] {{ color: {destructive}; border-color: {tint(destructive, 0.45)}; }}
            QLabel#chip[tone="warn"] {{ color: {warning}; border-color: {tint(warning, 0.5)}; }}
            QLabel#chip[tone="info"] {{ color: {fg}; border-color: {tint(primary, 0.5)}; }}

            QFrame#composerCard {{ background: {bg}; border: 1px solid {border}; border-radius: 14px; }}
            QFrame#composerCard[focused="true"] {{ border-color: {primary}; }}
            QPlainTextEdit#briefInput {{ background: transparent; border: none; color: {fg}; font-size: 13px; }}
            QPushButton#sendButton {{ background: {primary}; border: none; border-radius: 18px; }}
            QPushButton#sendButton:hover {{ background: {tint(primary, 0.85)}; }}
            QPushButton#sendButton:disabled {{ background: {muted}; }}
            QPushButton#sendButton[stop="true"] {{ background: {destructive}; }}
            QPushButton#secondaryAction, QPushButton#ghostAction {{
                background: transparent; color: {fg}; border: 1px solid {border};
                border-radius: 8px; padding: 4px 12px; font-size: 12px; font-weight: 500;
                height: 18px; min-height: 18px; max-height: 18px; }}
            QPushButton#ghostAction {{ border-color: transparent; color: {muted_fg}; }}
            QPushButton#secondaryAction:hover, QPushButton#ghostAction:hover {{
                background: {accent}; color: {fg}; border-color: {border}; }}
            QCheckBox#autoApply {{ color: {muted_fg}; font-size: 12px; spacing: 6px; }}
            QCheckBox#autoApply::indicator {{ width: 14px; height: 14px; border-radius: 4px;
                                              border: 1px solid {border}; background: {card}; }}
            QCheckBox#autoApply::indicator:checked {{ background: {primary}; border-color: {primary}; }}
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
        """Give the tab the Designer so diffs and screen size are real."""
        self.workspace = workspace

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
        path (generate QML -> reload bundle), so that runs too whenever an
        application bundle is open.  Returns what happened, for the chips:
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
            if getattr(workspace, "bundle_dir", "") and hasattr(workspace, "preview"):
                workspace.preview()
                outcome = "previewed"
        self.generateRequested.emit(project)
        if focus:
            self.canvasFocusRequested.emit()
        return outcome

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
            self.connector.cancel()
            self.send_btn.setEnabled(False)
            self.send_btn.setToolTip("Stopping\u2026")

    def _on_send(self):
        brief = self.brief_input.toPlainText().strip()
        if not brief or self.streaming:
            return
        if not self.connector:
            QMessageBox.warning(self, "AI Design", "No connector configured. Check provider settings.")
            return
        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.warning(self, "AI Design", "Pick or type a model name first.")
            return

        self.brief_input.setPlainText("")
        self.empty_hint.setVisible(False)
        turn = TurnWidget(brief)
        turn.retheme(self._theme)
        turn.applyRequested.connect(lambda project: self.apply_to_canvas(project=project, focus=True))
        self.turns.append(turn)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, turn)
        self._scroll_to_bottom()

        width, height = self._screen_size()
        registry = getattr(self.generator, "registry", None)
        self.connector.system_prompt = build_system_prompt(registry, width, height)

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

    def _on_worker_event(self, ev: dict):
        if self._active_turn is not None:
            self._on_event(self._active_turn, ev)

    def _on_event(self, turn: TurnWidget, ev: dict):
        shell = turn.shell
        kind = ev.get("type")
        if kind == "start":
            shell.note_request(ev.get("provider", ""), ev.get("model", ""), ev.get("url", ""),
                               turn.bubble.text(), ev.get("mode", ""))
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
                diff = diff_projects(self._canvas_project(), project)
                applied = self.auto_apply.isChecked()
                shell.note_changes(diff, applied)
                self.last_project = project
                n = sum(1 for _ in project.all_widgets())
                chips.append((f"{n} widget{'s' if n != 1 else ''}", "info"))
                chips.append((f"+{len(diff['added'])} \u2212{len(diff['removed'])} ~{len(diff['changed'])}", "neutral"))
                if applied:
                    outcome = self.apply_to_canvas(project=project)
                    if outcome == "previewed":
                        chips.append(("Applied · panel preview refreshed", "ok"))
                    else:
                        chips.append(("Applied to canvas", "ok"))
                        chips.append(("Open a bundle to preview on the panel", "warn"))
            else:
                chips.append(("No design parsed", "fail"))
                if shell.truncated:
                    turn.show_error("The reply was cut off at the token limit before the design JSON finished.",
                                    "Ask for a smaller screen, or pick a model that reasons less.")
                elif full_text.strip():
                    turn.show_error("The model answered, but no design payload could be parsed from it.",
                                    "Open the Response fold above to see what came back; try rephrasing the brief.")
                else:
                    turn.show_error("The model returned nothing.",
                                    "Check the connection pill and the model name, then try again.")
            shell.finish("done" if project is not None else "failed")

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

    # ------------------------------------------------------------------
    # Conversation housekeeping
    # ------------------------------------------------------------------

    def clear_conversation(self):
        if self.streaming:
            return
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
