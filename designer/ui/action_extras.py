"""Inspector fields for CONTRACT 13.1 actions. FROZEN API (wave 1, W1).

ActionEditor (designer_workspace.py) embeds one ActionExtras under its own
fields, calls `load(action)` when a signal's action is shown, `set_kind(kind)`
when the Action combo changes, and `apply_to(action)` on Apply to get the
action to store. Plain PySide6 widgets, styled like the ActionEditor's
fields (`_mark(editor, "propField")` is the workspace's job, not this one's).
"""
from __future__ import annotations

import copy

from PySide6.QtWidgets import (QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QListWidget,
                               QPushButton, QSpinBox, QWidget)


class ActionExtras(QWidget):
    """Fields (object names are tested):

    "extraStep"     QDoubleSpinBox  step            increment/decrement only
    "extraMin"      QLineEdit       min ("" = none, else "%g") increment/decrement only
    "extraMax"      QLineEdit       max ("" = none, else "%g") increment/decrement only
    "extraMs"       QSpinBox        shelve ms, 1..86400000 (default 600000); shelve only
    "extraConfirm"  QLineEdit       confirm text; every kind
    "extraThen"     QListWidget     the list's further actions, one row per
                                    action as "<kind> <tag|page>" (read-only view)
    "extraAddThen"  QPushButton     "Add step" -- appends a copy of the edited
                                    action (without `then`) to the list
    "extraClearThen" QPushButton    "Clear steps" -- empties the list

    Fields a kind does not use are hidden (not just disabled).
    """

    STEP_KINDS = ("increment", "decrement")
    SHELVE_MS_MIN, SHELVE_MS_MAX = 1, 86_400_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kind = ""
        self._edited = None
        # The list's further actions as whole actions: a row's text is only a
        # view, so nothing (value, ms, page, confirm) is lost on the way back.
        self._steps = []

        self.step = QDoubleSpinBox(); self.step.setObjectName("extraStep")
        self.step.setRange(-1e9, 1e9); self.step.setDecimals(3); self.step.setValue(1.0)
        self.min = QLineEdit(); self.min.setObjectName("extraMin"); self.min.setPlaceholderText("none")
        self.max = QLineEdit(); self.max.setObjectName("extraMax"); self.max.setPlaceholderText("none")
        self.ms = QSpinBox(); self.ms.setObjectName("extraMs")
        self.ms.setRange(self.SHELVE_MS_MIN, self.SHELVE_MS_MAX); self.ms.setValue(600000)
        self.ms.setSuffix(" ms")
        self.confirm = QLineEdit(); self.confirm.setObjectName("extraConfirm")
        self.confirm.setPlaceholderText("no confirmation")
        self.then = QListWidget(); self.then.setObjectName("extraThen")
        self.then.setMaximumHeight(84)
        self.add = QPushButton("Add step"); self.add.setObjectName("extraAddThen")
        self.clear = QPushButton("Clear steps"); self.clear.setObjectName("extraClearThen")
        buttons = QHBoxLayout(); buttons.setContentsMargins(0, 0, 0, 0); buttons.setSpacing(6)
        buttons.addWidget(self.add); buttons.addWidget(self.clear); buttons.addStretch(1)

        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setVerticalSpacing(6)
        for label, field in (("Step", self.step), ("Min", self.min), ("Max", self.max),
                             ("Shelve for", self.ms), ("Confirm", self.confirm),
                             ("Then", self.then)):
            self.form.addRow(label, field)
        self.form.addRow("", buttons)
        self.add.clicked.connect(self._add_then)
        self.clear.clicked.connect(self._clear_then)
        self.set_kind("write")

    def set_kind(self, kind: str) -> None:
        """Which fields are visible depends on the action kind."""
        self._kind = kind or ""
        stepping = self._kind in self.STEP_KINDS
        for field in (self.step, self.min, self.max):
            self.form.setRowVisible(field, stepping)
        self.form.setRowVisible(self.ms, self._kind == "shelve")

    def load(self, action) -> None:
        """Show `action`'s 13.1 fields (None clears them)."""
        self._edited = copy.deepcopy(action) if action is not None else None
        self.step.setValue(float(action.step) if action is not None else 1.0)
        self.min.setText("%g" % action.min if action is not None and action.min is not None else "")
        self.max.setText("%g" % action.max if action is not None and action.max is not None else "")
        self.ms.setValue(int(action.ms) if action is not None and action.kind == "shelve" else 600000)
        self.confirm.setText(action.confirm if action is not None else "")
        self._steps = [copy.deepcopy(a) for a in action.then] if action is not None else []
        self._refresh_then()

    def apply_to(self, action):
        """Return `action` with step / min / max / ms (shelve) / confirm /
        then taken from the fields (a min/max field that is empty or not a
        number becomes None). The argument is not modified."""
        result = copy.deepcopy(action)
        if result.kind in self.STEP_KINDS:
            result.step = self.step.value()
            result.min = self._parse_minmax(self.min.text())
            result.max = self._parse_minmax(self.max.text())
        if result.kind == "shelve":
            result.ms = self.ms.value()
        result.confirm = self.confirm.text()
        result.then = [copy.deepcopy(a) for a in self._steps]
        return result

    def _add_then(self):
        if self._edited is None:
            return
        step = copy.deepcopy(self._edited)
        step.then = []
        self._steps.append(step)
        self._refresh_then()

    def _clear_then(self):
        self._steps = []
        self._refresh_then()

    @staticmethod
    def _parse_minmax(text):
        try:
            return float(text) if (text or "").strip() else None
        except ValueError:
            return None

    @staticmethod
    def _row_label(action) -> str:
        """ "<kind> <tag|page>" -- navigate names its page, back nothing."""
        target = action.page if action.kind == "navigate" else action.tag
        return f"{action.kind} {target}".strip()

    def _refresh_then(self):
        self.then.clear()
        self.then.addItems([self._row_label(a) for a in self._steps])
