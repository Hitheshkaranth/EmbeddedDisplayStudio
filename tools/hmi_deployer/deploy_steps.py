"""tools/hmi_deployer/deploy_steps.py -- the four steps of a deploy, shown.

Validate -> Package -> Transfer -> Activate, each a bar, a name and a line
of detail, in one of four states: waiting, running, done, failed. The
Studio drives it from the same calls that move its progress bar
(MainWindow._progress_*), so the steps can never disagree with the bar.
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

STEPS = (
    ("Validate", "Bundle, imports and the panel's packages"),
    ("Package", "Build the release archive"),
    ("Transfer", "Upload and verify over SSH"),
    ("Activate", "Install, restart, keep the previous as rollback"),
)
STATES = ("waiting", "running", "done", "failed")


class DeploySteps(QWidget):
    """Four step tiles in a row. `set_state(index, state, detail="")`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("deploySteps")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self._bars, self._names, self._states, self._details = [], [], [], []
        for column, (name, detail) in enumerate(STEPS):
            bar = QFrame()
            bar.setObjectName("deployStepBar")
            bar.setFixedHeight(4)
            head = QHBoxLayout()
            head.setContentsMargins(0, 2, 0, 0)
            title = QLabel(name)
            title.setObjectName("deployStepName")
            # The bar's colour is the state; the word is for screen readers
            # (accessibleDescription), not another squeezed label in the row.
            state = QLabel("")
            state.setObjectName("deployStepState")
            state.hide()
            head.addWidget(title)
            head.addStretch()
            head.addWidget(state)
            text = QLabel(detail)
            text.setObjectName("deployStepDetail")
            text.setWordWrap(True)
            text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            text.setMinimumWidth(0)
            cell = QVBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(bar)
            cell.addLayout(head)
            cell.addWidget(text)
            grid.addLayout(cell, 0, column)
            grid.setColumnStretch(column, 1)
            self._bars.append(bar)
            self._names.append(title)
            self._states.append(state)
            self._details.append(text)
        self.reset()

    def reset(self, note: str = ""):
        """Every step waiting; `note` (e.g. why a deploy was called off) on
        the first."""
        for index, (_name, detail) in enumerate(STEPS):
            self.set_state(index, "waiting", note if index == 0 and note else detail)

    def state(self, index: int) -> str:
        return self._bars[index].property("state") or "waiting"

    def set_state(self, index: int, state: str, detail: str = ""):
        if not 0 <= index < len(STEPS) or state not in STATES:
            return
        words = {"waiting": "", "running": "Running", "done": "Done", "failed": "Failed"}[state]
        for widget in (self._bars[index], self._states[index], self._names[index]):
            widget.setProperty("state", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._states[index].setText(words)
        self._bars[index].setAccessibleDescription(f"{STEPS[index][0]}: {words or 'waiting'}")
        self._names[index].setToolTip(words or "Waiting")
        if detail:
            self._details[index].setText(detail)
            self._details[index].setToolTip(detail)

    def advance_to(self, index: int, detail: str = ""):
        """Steps before `index` done, `index` running."""
        for earlier in range(index):
            if self.state(earlier) != "done":
                self.set_state(earlier, "done")
        self.set_state(index, "running", detail)

    def fail_current(self, reason: str):
        """The running step (else the first not done) failed, with the reason."""
        for index in range(len(STEPS)):
            if self.state(index) == "running":
                self.set_state(index, "failed", reason)
                return
        for index in range(len(STEPS)):
            if self.state(index) != "done":
                self.set_state(index, "failed", reason)
                return

    def finish(self, detail: str = ""):
        for index in range(len(STEPS)):
            self.set_state(index, "done")
        if detail:
            self.set_state(len(STEPS) - 1, "done", detail)
