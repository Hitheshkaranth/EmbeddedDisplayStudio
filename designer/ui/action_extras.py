"""Inspector fields for CONTRACT 13.1 actions. FROZEN API (wave 1, W1).

ActionEditor (designer_workspace.py) embeds one ActionExtras under its own
fields, calls `load(action)` when a signal's action is shown, `set_kind(kind)`
when the Action combo changes, and `apply_to(action)` on Apply to get the
action to store. Plain PySide6 widgets, styled like the ActionEditor's
fields (`_mark(editor, "propField")` is the workspace's job, not this one's).
"""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QListWidget, QPushButton, QDoubleSpinBox, QSpinBox, QWidget


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
        self._rows = []
        self._edited = None

        self.step = QDoubleSpinBox(self); self.step.setRange(-1e9, 1e9)
        self.min = QLineEdit(self)
        self.max = QLineEdit(self)
        self.ms = QSpinBox(self)
        self.ms.setRange(self.SHELVE_MS_MIN, self.SHELVE_MS_MAX)
        self.ms.setValue(600000)
        self.confirm = QLineEdit(self)
        self.then = QListWidget(self)
        self.add = QPushButton("Add step", self)
        self.clear = QPushButton("Clear steps", self)
        self._named = {
            "extraStep": self.step,
            "extraMin": self.min,
            "extraMax": self.max,
            "extraMs": self.ms,
            "extraConfirm": self.confirm,
            "extraThen": self.then,
        }
        for name, widget in self._named.items():
            widget.setObjectName(name)
        self.add.setObjectName("extraAddThen")
        self.clear.setObjectName("extraClearThen")
        self.add.clicked.connect(self._add_then)
        self.clear.clicked.connect(self._clear_then)

    def set_kind(self, kind: str) -> None:
        """Which fields are visible depends on the action kind."""
        self._kind = kind or ""
        step_visible = self._kind in self.STEP_KINDS
        self.step.setVisible(step_visible)
        self.min.setVisible(step_visible)
        self.max.setVisible(step_visible)
        self.ms.setVisible(self._kind == "shelve")
        if not step_visible:
            self.step.setValue(1.0)
            self.min.clear()
            self.max.clear()

    def load(self, action) -> None:
        """Show `action`'s 13.1 fields (None clears them)."""
        self._rows = []
        if action is None:
            self.step.clear()
            self.min.clear()
            self.max.clear()
            self.ms.clear()
            self.confirm.clear()
            self._edited = None
            return

        self._edited = action
        self.step.setValue(float(action.step))
        self.min.setText("%g" % action.min if action.min is not None else "")
        self.max.setText("%g" % action.max if action.max is not None else "")
        self.confirm.setText(action.confirm)
        if action.kind == "shelve":
            self.ms.setValue(int(action.ms))
        self._rows = [self._row_label(sibling) for sibling in action.then]
        self._refresh_then()

    def apply_to(self, action):
        """Return `action` with step / min / max / ms (shelve) / confirm /
        then taken from the fields (a min/max field that is empty or not a
        number becomes None). The argument is not modified."""
        import copy

        result = copy.deepcopy(action)
        result.step = self.step.value()
        result.min = self._parse_minmax(self.min.text())
        result.max = self._parse_minmax(self.max.text())
        result.confirm = self.confirm.text()
        if result.kind == "shelve":
            result.ms = self.ms.value()
        result.then = [self._row_action(row) for row in self._rows]
        return result

    def _add_then(self):
        self._rows.append(self._current_label())
        self._refresh_then()

    def _clear_then(self):
        self._rows = []
        self._refresh_then()

    # --- helpers -------------------------------------------------------

    def _current_label(self):
        """Text for a copy of the action currently on the fields."""
        if self._edited is not None:
            return self._row_label(self._edited)
        return self._kind

    @staticmethod
    def _parse_minmax(text):
        text = (text or "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _row_label(self, action):
        """The text a further action row displays."""
        return f"{action.kind} {action.tag}" if action else self._kind

    def _row_action(self, label):
        """Rebuild the further action stored in a row."""
        from designer.model.project import DesignerAction

        text = label.strip()
        kind, _, rest = text.partition(" ")
        rest = rest.strip()
        if kind == "navigate":
            return DesignerAction("navigate", page=rest)
        return DesignerAction(kind, rest)

    def _refresh_then(self):
        self.then.clear()
        self.then.addItems(self._rows)