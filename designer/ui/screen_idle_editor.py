"""Editor for CONTRACT 13.5 screen idle settings. FROZEN API (wave 1, W5).

The Designer's "Idle…" toolbar button opens a dialog holding one
ScreenIdleEditor; OK stores `value()` in project.screen.idle as one undo step.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QLabel, QSpinBox, QWidget

from designer.model.screen_idle import normalise_idle, validate_idle

SPIN_MAX = 86400


class ScreenIdleEditor(QWidget):
    """Fields (object names are tested):

    "idleDim"        QSpinBox  0..86400 s, special value text "never" at 0
    "idleDimPercent" QSpinBox  10..100 %, default 30
    "idleOff"        QSpinBox  0..86400 s, special value text "never" at 0
    "idleProblem"    QLabel    "" or the first validate_idle message
    `changed` fires on any edit.
    """

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.dim = QSpinBox()
        self.dim.setObjectName("idleDim")
        self.dim.setRange(0, SPIN_MAX)
        self.dim.setSpecialValueText("never")

        self.percent = QSpinBox()
        self.percent.setObjectName("idleDimPercent")
        self.percent.setRange(10, 100)
        self.percent.setValue(30)

        self.off = QSpinBox()
        self.off.setObjectName("idleOff")
        self.off.setRange(0, SPIN_MAX)
        self.off.setSpecialValueText("never")

        self.problem = QLabel()
        self.problem.setObjectName("idleProblem")

        self._updating = False

        form = QFormLayout(self)
        form.addRow("Dim after:", self.dim)
        form.addRow("Dim to:", self.percent)
        form.addRow("Off after:", self.off)
        form.addRow(self.problem)

        for spin in (self.dim, self.percent, self.off):
            spin.valueChanged.connect(self._edited)

    def _edited(self, value: int) -> None:
        if self._updating:
            return
        self.refresh_problem()
        self.changed.emit()

    def refresh_problem(self) -> None:
        current = self.value_raw()
        issues = validate_idle(current, "screen.idle")
        self.problem.setText(issues[0].message if issues else "")

    def value_raw(self) -> dict:
        return {
            "dimAfterS": self.dim.value(),
            "dimPercent": self.percent.value(),
            "offAfterS": self.off.value(),
        }

    def load(self, idle: dict) -> None:
        self._updating = True
        self.dim.setValue(int(idle.get("dimAfterS", 0)))
        self.percent.setValue(int(idle.get("dimPercent", 30)))
        self.off.setValue(int(idle.get("offAfterS", 0)))
        self._updating = False
        self.refresh_problem()

    def value(self) -> dict:
        """normalise_idle() of the fields."""
        return normalise_idle(self.value_raw())