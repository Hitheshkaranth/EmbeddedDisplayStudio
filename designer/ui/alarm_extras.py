"""Inspector fields for CONTRACT 13.3 alarm options. FROZEN API (wave 1, W3).

BindingEditor embeds one AlarmExtras below the BindingExtras; `load(binding)`
when a binding is shown, `apply_to(binding)` on "Apply binding". The group is
only meaningful when the binding has a warning or critical threshold; it is
always shown so the author sees what an alarm will do.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget


class AlarmExtras(QWidget):
    """Fields (object names are tested):

    "alarmPriority" QComboBox  "Auto", "1", "2", "3", "4"  (Auto = no priority key)
    "alarmLatch"    QCheckBox  "Latch until acknowledged"
    "alarmDelay"    QSpinBox   0..600000 ms, suffix " ms"
    "alarmDeadband" QDoubleSpinBox 0..1e9
    "alarmMessage"  QLineEdit  "" = generated message
    """

    def load(self, binding) -> None:
        pass   # W3

    def apply_to(self, binding):
        """Return a copy of `binding` whose `alarm` dict holds only the
        options that differ from the defaults (Auto priority, no latch, 0 ms,
        0 deadband, "" message); {} when all are defaults."""
        return binding   # W3
