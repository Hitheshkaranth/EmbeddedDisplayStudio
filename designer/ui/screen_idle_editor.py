"""Editor for CONTRACT 13.5 screen idle settings. FROZEN API (wave 1, W5).

The Designer's "Idle…" toolbar button opens a dialog holding one
ScreenIdleEditor; OK stores `value()` in project.screen.idle as one undo step.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class ScreenIdleEditor(QWidget):
    """Fields (object names are tested):

    "idleDim"        QSpinBox  0..86400 s, special value text "never" at 0
    "idleDimPercent" QSpinBox  10..100 %, default 30
    "idleOff"        QSpinBox  0..86400 s, special value text "never" at 0
    "idleProblem"    QLabel    "" or the first validate_idle message
    `changed` fires on any edit.
    """

    changed = Signal()

    def load(self, idle: dict) -> None:
        pass   # W5

    def value(self) -> dict:
        """normalise_idle() of the fields."""
        return {}   # W5
