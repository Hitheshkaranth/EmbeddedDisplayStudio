"""Inspector fields for CONTRACT 13.2 bindings. FROZEN API (wave 1, W2).

BindingEditor (designer_workspace.py) embeds one BindingExtras under its own
fields, calls `load(binding, definition)` when a binding is shown and
`apply_to(binding)` on "Apply binding".
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget


class BindingExtras(QWidget):
    """Fields (object names are tested):

    "extraDecimals"  QSpinBox   -1..6, special value text "auto" at -1
    "extraExpr"      QLineEdit  the expression ("" = none)
    "extraExprState" QLabel     "" when the expression is empty or compiles,
                                else the ExprError text; updated as you type
    "extraRules"     QTableWidget  3 columns "If", "Property", "Value"; one row
                                per rule; Value shows the JSON of the value
    "extraAddRule"   QPushButton   "Add rule" -- appends {"if": "> 0",
                                "prop": <first property of the widget, or "">,
                                "value": ""}
    "extraRemoveRule" QPushButton  "Remove rule" -- removes the selected row
    """

    def load(self, binding, definition=None) -> None:
        """Show `binding`'s 13.2 fields (None clears them). `definition` (the
        registry WidgetDefinition or None) offers the properties for rules."""
        pass   # W2

    def apply_to(self, binding):
        """Return a copy of `binding` with decimals / expr / rules from the
        fields (a Value cell is parsed as JSON when it is valid JSON, else
        kept as text). The argument is not modified."""
        return binding   # W2
