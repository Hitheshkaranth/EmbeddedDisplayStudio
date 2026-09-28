"""Inspector fields for CONTRACT 13.2 bindings. FROZEN API (wave 1, W2).

BindingEditor (designer_workspace.py) embeds one BindingExtras under its own
fields, calls `load(binding, definition)` when a binding is shown and
`apply_to(binding)` on "Apply binding".
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget, QWidget, QStyledItemDelegate,
                               QTableWidgetItem)
from PySide6.QtCore import Qt

from designer.model.expr import compile_expr, ExprError


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

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)

        self.decimals = QSpinBox()
        self.decimals.setRange(-1, 6)
        self.decimals.setSpecialValueText("auto")
        self.decimals.setValue(-1)
        self.decimals.setObjectName("extraDecimals")
        layout.addRow("Decimals", self.decimals)

        self.expr = QLineEdit()
        self.expr.setObjectName("extraExpr")
        self.expr.setPlaceholderText("expression")
        self.expr.textChanged.connect(self._update_state)
        layout.addRow("Expression", self.expr)

        self.state = QLabel()
        self.state.setObjectName("extraExprState")
        self.state.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addRow("Expression state", self.state)

        self.rules = QTableWidget(0, 3)
        self.rules.setObjectName("extraRules")
        self.rules.setHorizontalHeaderLabels(["If", "Property", "Value"])
        self.rules.setItemDelegateForColumn(2, QStyledItemDelegate())
        self.rules.verticalHeader().setVisible(False)
        self.rules.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addRow(self.rules)

        buttons = QHBoxLayout()
        self.add_rule = QPushButton("Add rule")
        self.add_rule.setObjectName("extraAddRule")
        self.remove_rule = QPushButton("Remove rule")
        self.remove_rule.setObjectName("extraRemoveRule")
        self.add_rule.clicked.connect(self._add_rule)
        self.remove_rule.clicked.connect(self._remove_rule)
        buttons.addWidget(self.add_rule)
        buttons.addWidget(self.remove_rule)
        layout.addRow(buttons)

        self._definition = None

    def load(self, binding, definition=None) -> None:
        """Show `binding`'s 13.2 fields (None clears them). `definition` (the
        registry WidgetDefinition or None) offers the properties for rules."""
        self._definition = definition
        if binding is None:
            self.decimals.setValue(-1)
            self.expr.setText("")
            self._update_state()
            self.rules.setRowCount(0)
            return

        decimals = getattr(binding, "decimals", -1)
        self.decimals.setValue(int(decimals) if decimals is not None else -1)

        expr_text = getattr(binding, "expr", "") or ""
        self.expr.setText(expr_text)
        self._update_state()

        rules = getattr(binding, "rules", []) or []
        self.rules.setRowCount(0)
        for rule in rules:
            self._append_rule_row(rule)

    def apply_to(self, binding):
        """Return a copy of `binding` with decimals / expr / rules from the
        fields (a Value cell is parsed as JSON when it is valid JSON, else
        kept as text). The argument is not modified."""
        copy = type(binding)(**binding.__dict__)
        copy.decimals = self.decimals.value()
        copy.expr = self.expr.text()
        copy.rules = []
        for row in range(self.rules.rowCount()):
            parsed = self._read_rule_cell(row)
            copy.rules.append(parsed)
        return copy

    # -- expression state --------------------------------------------------
    def _update_state(self) -> None:
        text = self.expr.text()
        if not text:
            self.state.setText("")
            return
        try:
            compile_expr(text)
            self.state.setText("")
        except ExprError as err:
            self.state.setText(str(err))

    # -- rules -------------------------------------------------------------
    def _add_rule(self) -> None:
        first = ""
        if self._definition is not None and self._definition.properties:
            first = next(iter(self._definition.properties))
        self._append_rule_row({"if": "> 0", "prop": first, "value": ""})

    def _remove_rule(self) -> None:
        row = self.rules.currentRow()
        if row < 0:
            rows = self.rules.rowCount()
            row = rows - 1 if rows else 0
        if 0 <= row < self.rules.rowCount():
            self.rules.removeRow(row)

    def _append_rule_row(self, rule) -> None:
        row = self.rules.rowCount()
        self.rules.insertRow(row)
        self.rules.setItem(row, 0, QTableWidgetItem(self._cell_text(rule.get("if", ""))))
        self.rules.setItem(row, 1, QTableWidgetItem(self._cell_text(rule.get("prop", ""))))
        self.rules.setItem(row, 2, QTableWidgetItem(self._value_text(rule.get("value", ""))))

    def _read_rule_cell(self, row):
        if_item = self.rules.item(row, 0)
        if_text = if_item.text() if if_item else ""
        prop_item = self.rules.item(row, 1)
        prop_text = prop_item.text() if prop_item else ""
        value_item = self.rules.item(row, 2)
        value_text = value_item.text() if value_item else ""
        return {"if": if_text, "prop": prop_text, "value": _parse_value(value_text)}

    @staticmethod
    def _cell_text(value) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _value_text(value) -> str:
        try:
            return json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(value)


def _parse_value(text: str):
    if text == "":
        return ""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text