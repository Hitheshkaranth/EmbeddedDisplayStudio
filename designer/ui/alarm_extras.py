"""Inspector fields for CONTRACT 13.3 alarm options. FROZEN API (wave 1, W3).

BindingEditor embeds one AlarmExtras below the BindingExtras; `load(binding)`
when a binding is shown, `apply_to(binding)` on "Apply binding". The group is
only meaningful when the binding has a warning or critical threshold; it is
always shown so the author sees what an alarm will do.
"""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit,
                               QSpinBox, QWidget)

from designer.model.alarm_options import manifest_fields


ALARM_PRIORITY = ("Auto", "1", "2", "3", "4")


class AlarmExtras(QWidget):
    """Fields (object names are tested):

    "alarmPriority" QComboBox  "Auto", "1", "2", "3", "4"  (Auto = no priority key)
    "alarmLatch"    QCheckBox  "Latch until acknowledged"
    "alarmDelay"    QSpinBox   0..600000 ms, suffix " ms"
    "alarmDeadband" QDoubleSpinBox 0..1e9
    "alarmMessage"  QLineEdit  "" = generated message
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        self.priority = QComboBox(self)
        self.priority.setObjectName("alarmPriority")
        self.priority.addItems(list(ALARM_PRIORITY))
        self.latch = QCheckBox("Latch until acknowledged", self)
        self.latch.setObjectName("alarmLatch")
        self.delay = QSpinBox(self)
        self.delay.setObjectName("alarmDelay")
        self.delay.setRange(0, 600000)
        self.delay.setSuffix(" ms")
        self.deadband = QDoubleSpinBox(self)
        self.deadband.setObjectName("alarmDeadband")
        self.deadband.setRange(0.0, 1e9)
        self.message = QLineEdit(self)
        self.message.setObjectName("alarmMessage")
        form.addRow("Priority", self.priority)
        form.addRow("Latch", self.latch)
        form.addRow("Delay", self.delay)
        form.addRow("Deadband", self.deadband)
        form.addRow("Message", self.message)

    def load(self, binding) -> None:
        """Show `binding.alarm` in the fields; Auto priority when it has none."""
        # Only valid options are shown: a hand-edited file can hold anything,
        # and validate() is what names it.
        alarm = manifest_fields(getattr(binding, "alarm", None) or {})
        self.priority.setCurrentIndex(alarm.get("priority", 0))
        self.latch.setChecked(alarm.get("latch", False))
        self.delay.setValue(alarm.get("delay_ms", 0))
        self.deadband.setValue(float(alarm.get("deadband", 0.0)))
        self.message.setText(alarm.get("message", ""))

    def apply_to(self, binding):
        """Return a copy of `binding` whose `alarm` dict holds only the
        options that differ from the defaults (Auto priority, no latch, 0 ms,
        0 deadband, "" message); {} when all are defaults."""
        alarm = {}
        priority = self.priority.currentText()
        if priority != "Auto":
            alarm["priority"] = int(priority)
        if self.latch.isChecked():
            alarm["latch"] = True
        if self.delay.value() != 0:
            alarm["delay_ms"] = self.delay.value()
        deadband = self.deadband.value()
        if deadband != 0.0:
            alarm["deadband"] = deadband
        message = self.message.text()
        if message:
            alarm["message"] = message

        cloned = copy.copy(binding)
        cloned.alarm = alarm
        return cloned
