"""Inspector fields for CONTRACT 13.1 actions. FROZEN API (wave 1, W1).

ActionEditor (designer_workspace.py) embeds one ActionExtras under its own
fields, calls `load(action)` when a signal's action is shown, `set_kind(kind)`
when the Action combo changes, and `apply_to(action)` on Apply to get the
action to store. Plain PySide6 widgets, styled like the ActionEditor's
fields (`_mark(editor, "propField")` is the workspace's job, not this one's).
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget


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

    def set_kind(self, kind: str) -> None:
        pass   # W1

    def load(self, action) -> None:
        """Show `action`'s 13.1 fields (None clears them)."""
        pass   # W1

    def apply_to(self, action):
        """Return `action` with step / min / max / ms (shelve) / confirm /
        then taken from the fields (a min/max field that is empty or not a
        number becomes None). The argument is not modified."""
        return action   # W1
