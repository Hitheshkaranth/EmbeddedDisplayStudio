"""
tools/hmi_deployer/taglab_panel.py
Layer: 3 (Host Deployer)
Purpose: PySide6 QWidget for the Tag Lab feature.

Design constraints
------------------
* Uses only widget types and property variants already covered by the
  application-level QSS (shadcn_dark.qss / shadcn_light.qss).  No inline
  stylesheet that hard-codes palette values.
* Spacing follows the 4/8/12/16 grid from tokens.json.
* Button variants use the QSS "variant" property (default, secondary,
  outline, destructive, ghost).
* Semantic status is expressed through QLabel text prefixes and
  setEnabled(False) states, never through custom colours.
* The widget fires signals but does NOT own or start the TagLabSender;
  ownership lives in MainWindow so the mutual-exclusion logic stays in one
  place.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .taglab import (
    WAVEFORM_KINDS,
    ConstantWaveform,
    NoiseWaveform,
    RampWaveform,
    SineWaveform,
    SquareWaveform,
    TagEntry,
    TagLabModel,
    load_scenario,
    save_scenario,
)

# ---------------------------------------------------------------------------
# Column indices for the tag table
# ---------------------------------------------------------------------------
_COL_TAG = 0
_COL_STATUS = 1
_COL_WAVEFORM = 2
_COL_PARAMS = 3
_COL_TOGGLE = 4
_COL_REMOVE = 5
_NUM_COLS = 6
_HEADERS = ["Tag", "Status", "Waveform", "Parameters", "", ""]


def _make_waveform_label(entry: TagEntry) -> str:
    """Compact human-readable waveform description for the Parameters column."""
    w = entry.waveform
    if isinstance(w, ConstantWaveform):
        return f"value={w.value:g}"
    if isinstance(w, SineWaveform):
        return f"amp={w.amplitude:g}  T={w.period:g}s  off={w.offset:g}"
    if isinstance(w, SquareWaveform):
        return f"hi={w.high:g}  lo={w.low:g}  T={w.period:g}s  duty={w.duty:.0%}"
    if isinstance(w, RampWaveform):
        return f"lo={w.low:g}  hi={w.high:g}  T={w.period:g}s"
    if isinstance(w, NoiseWaveform):
        return f"amp={w.amplitude:g}  mean={w.mean:g}"
    return w.kind


def _status_text(entry: TagEntry) -> str:
    """Short status badge text for the Status column."""
    if not entry.known:
        return "Unknown"
    if entry.enabled:
        return "Active"
    return "Paused"


# ---------------------------------------------------------------------------
# Waveform parameter editor dialog
# ---------------------------------------------------------------------------

class _WaveformDialog(QWidget):
    """
    Inline-style waveform editor.  Shown as a floating modal-less QWidget so
    the table remains visible.  Emits ``accepted(TagEntry)`` when saved.
    """

    accepted = Signal(object)  # emits the edited TagEntry

    def __init__(self, entry: TagEntry, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle(f"Edit Waveform — {entry.tag}")
        self.setMinimumWidth(360)
        self._entry = entry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Waveform kind selector
        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("Waveform:"))
        self._cmb_kind = QComboBox()
        self._cmb_kind.setToolTip("Select the signal shape to inject on this tag")
        self._cmb_kind.setAccessibleName("Waveform kind selector")
        for k in WAVEFORM_KINDS:
            self._cmb_kind.addItem(k.capitalize(), k)
        current_idx = WAVEFORM_KINDS.index(entry.waveform.kind)
        self._cmb_kind.setCurrentIndex(current_idx)
        self._cmb_kind.currentIndexChanged.connect(self._on_kind_changed)
        kind_row.addWidget(self._cmb_kind)
        layout.addLayout(kind_row)

        # Parameter group – rebuilt when kind changes
        self._param_box = QGroupBox("Parameters")
        self._param_layout = QVBoxLayout(self._param_box)
        self._param_layout.setContentsMargins(12, 12, 12, 12)
        self._param_layout.setSpacing(4)
        layout.addWidget(self._param_box)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_save = QPushButton("Apply")
        self._btn_save.setProperty("variant", "default")
        self._btn_save.setToolTip("Apply waveform settings")
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setProperty("variant", "outline")
        self._btn_cancel.setToolTip("Discard changes")
        self._btn_save.clicked.connect(self._on_save)
        self._btn_cancel.clicked.connect(self.close)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

        self._fields: dict = {}
        self._rebuild_params()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_params(self) -> None:
        while self._param_layout.count():
            item = self._param_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._fields.clear()

    def _add_field(self, name: str, label: str, value: str, tooltip: str = "") -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setFixedWidth(100)
        edit = QLineEdit(value)
        edit.setAccessibleName(f"{self._entry.tag} {label}")
        if tooltip:
            edit.setToolTip(tooltip)
        row.addWidget(lbl)
        row.addWidget(edit)
        self._param_layout.addLayout(row)
        self._fields[name] = edit

    def _rebuild_params(self) -> None:
        self._clear_params()
        kind = self._cmb_kind.currentData()
        w = self._entry.waveform

        if kind == "constant":
            v = w.value if isinstance(w, ConstantWaveform) else 0.0
            self._add_field("value", "Value:", f"{v:g}", "Fixed output value")

        elif kind == "sine":
            amp = w.amplitude if isinstance(w, SineWaveform) else 1.0
            period = w.period if isinstance(w, SineWaveform) else 1.0
            off = w.offset if isinstance(w, SineWaveform) else 0.0
            self._add_field("amplitude", "Amplitude:", f"{amp:g}", "Peak deviation from offset")
            self._add_field("period", "Period (s):", f"{period:g}", "Time for one full cycle (> 0)")
            self._add_field("offset", "Offset:", f"{off:g}", "DC bias added to the sine")

        elif kind == "square":
            hi = w.high if isinstance(w, SquareWaveform) else 1.0
            lo = w.low if isinstance(w, SquareWaveform) else 0.0
            period = w.period if isinstance(w, SquareWaveform) else 1.0
            duty = w.duty if isinstance(w, SquareWaveform) else 0.5
            self._add_field("high", "High value:", f"{hi:g}", "Value during ON phase")
            self._add_field("low", "Low value:", f"{lo:g}", "Value during OFF phase")
            self._add_field("period", "Period (s):", f"{period:g}", "Cycle duration (> 0)")
            self._add_field("duty", "Duty (0-1):", f"{duty:g}", "Fraction of period spent high (0 < duty ≤ 1)")

        elif kind == "ramp":
            lo = w.low if isinstance(w, RampWaveform) else 0.0
            hi = w.high if isinstance(w, RampWaveform) else 1.0
            period = w.period if isinstance(w, RampWaveform) else 1.0
            self._add_field("low", "Low value:", f"{lo:g}", "Starting value of the ramp")
            self._add_field("high", "High value:", f"{hi:g}", "Ending value of the ramp")
            self._add_field("period", "Period (s):", f"{period:g}", "Ramp duration (> 0)")

        elif kind == "noise":
            amp = w.amplitude if isinstance(w, NoiseWaveform) else 0.1
            mean = w.mean if isinstance(w, NoiseWaveform) else 0.0
            self._add_field("amplitude", "Amplitude:", f"{amp:g}", "Half-width of uniform noise (>= 0)")
            self._add_field("mean", "Mean:", f"{mean:g}", "Centre value of noise distribution")

    def _on_kind_changed(self, _index: int) -> None:
        self._rebuild_params()

    def _float_field(self, name: str) -> float:
        text = self._fields[name].text().strip()
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"'{name}' must be a number, got: {text!r}")

    def _on_save(self) -> None:
        kind = self._cmb_kind.currentData()
        try:
            if kind == "constant":
                w = ConstantWaveform(self._float_field("value"))
            elif kind == "sine":
                w = SineWaveform(
                    self._float_field("amplitude"),
                    self._float_field("period"),
                    self._float_field("offset"),
                )
            elif kind == "square":
                w = SquareWaveform(
                    self._float_field("high"),
                    self._float_field("low"),
                    self._float_field("period"),
                    self._float_field("duty"),
                )
            elif kind == "ramp":
                w = RampWaveform(
                    self._float_field("low"),
                    self._float_field("high"),
                    self._float_field("period"),
                )
            elif kind == "noise":
                w = NoiseWaveform(
                    self._float_field("amplitude"),
                    self._float_field("mean"),
                )
            else:
                raise ValueError(f"Unknown kind {kind!r}")
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Invalid Parameter", str(exc))
            return

        self._entry.waveform = w
        self.accepted.emit(self._entry)
        self.close()


# ---------------------------------------------------------------------------
# Main Tag Lab panel
# ---------------------------------------------------------------------------

class TagLabPanel(QWidget):
    """
    Tag Lab panel widget.

    Signals:
        sendingStarted():  Emitted when the user clicks Start (before the
                           caller creates/starts a TagLabSender).
        sendingStopped():  Emitted when the user clicks Stop.
    """

    sendingStarted = Signal()
    sendingStopped = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._model: TagLabModel = TagLabModel()
        self._sending: bool = False
        self._last_scenario_path: str = ""
        self._bound_tags: set[str] = set()

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API (called by MainWindow)
    # ------------------------------------------------------------------

    def set_model(self, model: TagLabModel) -> None:
        """Replace the current model and refresh the table."""
        self._model = model
        self._refresh_table()

    def model(self) -> TagLabModel:
        return self._model

    def set_sending(self, active: bool) -> None:
        """
        Reflect sending state in the UI (called by MainWindow after starting/
        stopping the TagLabSender).
        """
        self._sending = active
        self._btn_send.setEnabled(not active and bool(self._model.active_entries()))
        self._btn_stop.setEnabled(active)
        self._btn_load.setEnabled(not active)
        status = "Sending…" if active else "Idle"
        self._lbl_status.setText(f"Status: {status}")

    def bind_tags(self, tags: List[str]) -> None:
        """
        Bind a list of tag names from the loaded bundle.

        Known tags are added (or their known flag set to True).  Tags already
        in the model are not reset; their waveform is preserved.
        """
        self._bound_tags = set(tags)
        for entry in self._model.entries:
            entry.known = entry.tag in self._bound_tags
            if not entry.known:
                entry.enabled = False
        for tag in tags:
            existing = self._model.find(tag)
            if existing is not None:
                existing.known = True
            else:
                self._model.add_tag(tag, ConstantWaveform(0.0), known=True)
        self._refresh_table()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_send = QPushButton("Start Sending")
        self._btn_send.setProperty("variant", "default")
        self._btn_send.setToolTip("Begin injecting tag values over UDP to the TagEngine")
        self._btn_send.setAccessibleName("Start Tag Lab sender")
        self._btn_send.clicked.connect(self._on_start)

        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setProperty("variant", "outline")
        self._btn_stop.setToolTip("Stop injecting tag values")
        self._btn_stop.setAccessibleName("Stop Tag Lab sender")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)

        self._btn_save = QPushButton("Save Scenario…")
        self._btn_save.setProperty("variant", "secondary")
        self._btn_save.setToolTip("Save the current tag assignments to a .json scenario file")
        self._btn_save.setAccessibleName("Save scenario")
        self._btn_save.clicked.connect(self._on_save_scenario)

        self._btn_load = QPushButton("Load Scenario…")
        self._btn_load.setProperty("variant", "outline")
        self._btn_load.setToolTip("Load a previously saved scenario file")
        self._btn_load.setAccessibleName("Load scenario")
        self._btn_load.clicked.connect(self._on_load_scenario)

        self._btn_add = QPushButton("Add Tag…")
        self._btn_add.setProperty("variant", "ghost")
        self._btn_add.setToolTip("Manually add a tag name that is not in the bundle manifest")
        self._btn_add.setAccessibleName("Add custom tag")
        self._btn_add.clicked.connect(self._on_add_tag)

        self._lbl_status = QLabel("Status: Idle")
        self._lbl_status.setObjectName("tagLabStatus")

        toolbar.addWidget(self._btn_send)
        toolbar.addWidget(self._btn_stop)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._btn_save)
        toolbar.addWidget(self._btn_load)
        toolbar.addSpacing(4)
        toolbar.addWidget(self._btn_add)
        toolbar.addStretch()
        toolbar.addWidget(self._lbl_status)
        layout.addLayout(toolbar)

        # ── Tag table ─────────────────────────────────────────────────────
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setToolTip("Tag signal assignments.  Select a row and click Edit to change the waveform.")
        self._table.setAccessibleName("Tag Lab tag table")

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_TAG, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_WAVEFORM, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_PARAMS, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_TOGGLE, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_TOGGLE, 80)
        hdr.setSectionResizeMode(_COL_REMOVE, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_REMOVE, 44)

        layout.addWidget(self._table, 1)

        # ── Empty-state label (shown when model is empty) ─────────────────
        self._lbl_empty = QLabel(
            "No tags loaded.\n"
            "Open a bundle to bind its tags_required, or click Add Tag… to add one manually."
        )
        self._lbl_empty.setAlignment(Qt.AlignCenter)
        self._lbl_empty.setWordWrap(True)
        self._lbl_empty.setObjectName("tagLabEmptyState")
        layout.addWidget(self._lbl_empty)

        self._refresh_empty_state()

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        """Rebuild the table from the current model."""
        self._table.setRowCount(0)
        for entry in self._model.entries:
            self._append_row(entry)
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        has_entries = len(self._model) > 0
        self._table.setVisible(has_entries)
        self._lbl_empty.setVisible(not has_entries)
        self._btn_send.setEnabled(
            not self._sending and bool(self._model.active_entries())
        )

    def _append_row(self, entry: TagEntry) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Tag name
        item_tag = QTableWidgetItem(entry.tag)
        item_tag.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, _COL_TAG, item_tag)

        # Status badge
        self._set_status_cell(row, entry)

        # Waveform kind
        item_kind = QTableWidgetItem(entry.waveform.kind.capitalize())
        item_kind.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, _COL_WAVEFORM, item_kind)

        # Parameters summary
        item_params = QTableWidgetItem(_make_waveform_label(entry))
        item_params.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, _COL_PARAMS, item_params)

        # Edit / Toggle button
        btn_edit = QPushButton("Edit")
        btn_edit.setProperty("variant", "ghost")
        btn_edit.setToolTip(f"Edit waveform for {entry.tag}")
        btn_edit.setAccessibleName(f"Edit waveform for {entry.tag}")
        btn_edit.clicked.connect(lambda _checked, r=row: self._on_edit_row(r))
        self._table.setCellWidget(row, _COL_TOGGLE, btn_edit)

        # Remove button
        btn_rm = QPushButton("×")
        btn_rm.setProperty("variant", "ghost")
        btn_rm.setToolTip(f"Remove {entry.tag} from Tag Lab")
        btn_rm.setAccessibleName(f"Remove {entry.tag}")
        btn_rm.clicked.connect(lambda _checked, t=entry.tag: self._on_remove_tag(t))
        self._table.setCellWidget(row, _COL_REMOVE, btn_rm)

    def _set_status_cell(self, row: int, entry: TagEntry) -> None:
        text = _status_text(entry)
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, _COL_STATUS, item)

    def _update_row(self, row: int, entry: TagEntry) -> None:
        """Refresh the cells of an existing row after an entry is modified."""
        self._set_status_cell(row, entry)
        self._table.item(row, _COL_WAVEFORM).setText(entry.waveform.kind.capitalize())
        self._table.item(row, _COL_PARAMS).setText(_make_waveform_label(entry))

    def _row_for_tag(self, tag: str) -> int:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_TAG)
            if item and item.text() == tag:
                return row
        return -1

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if not self._model.active_entries():
            QMessageBox.information(
                self,
                "No Active Tags",
                "Enable at least one known tag before starting the sender.",
            )
            return
        self.sendingStarted.emit()

    def _on_stop(self) -> None:
        self.sendingStopped.emit()

    def _on_save_scenario(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Tag Lab Scenario",
            self._last_scenario_path or "scenario.json",
            "JSON Scenario (*.json)",
        )
        if not path:
            return
        try:
            save_scenario(self._model, path)
            self._last_scenario_path = path
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _on_load_scenario(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Tag Lab Scenario",
            self._last_scenario_path or "",
            "JSON Scenario (*.json)",
        )
        if not path:
            return
        try:
            model = load_scenario(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))
            return
        for entry in model.entries:
            entry.known = entry.tag in self._bound_tags
            if not entry.known:
                entry.enabled = False
        self._model = model
        self._last_scenario_path = path
        self._refresh_table()

    def _on_add_tag(self) -> None:
        """Show an inline dialog to let the user type a tag name."""
        dialog = QWidget(self, Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        dialog.setWindowTitle("Add Tag")
        dialog.setMinimumWidth(320)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(16, 16, 16, 16)
        dlg_layout.setSpacing(8)

        dlg_layout.addWidget(QLabel("Tag name (e.g. ai.custom.sensor):"))
        tag_edit = QLineEdit()
        tag_edit.setPlaceholderText("ai. di. do. sys. …")
        tag_edit.setAccessibleName("New tag name")
        dlg_layout.addWidget(tag_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_ok = QPushButton("Add")
        btn_ok.setProperty("variant", "default")
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setProperty("variant", "outline")
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        dlg_layout.addLayout(btn_row)

        def _do_add():
            tag = tag_edit.text().strip()
            if not tag:
                QMessageBox.warning(dialog, "Invalid Tag", "Tag name cannot be empty.")
                return
            if self._model.find(tag) is not None:
                QMessageBox.information(dialog, "Duplicate", f"Tag '{tag}' is already in the list.")
                dialog.close()
                return
            # Unknown – must NOT auto-enable
            entry = self._model.add_tag(tag, ConstantWaveform(0.0), known=False)
            self._append_row(entry)
            self._refresh_empty_state()
            dialog.close()

        btn_ok.clicked.connect(_do_add)
        btn_cancel.clicked.connect(dialog.close)
        tag_edit.returnPressed.connect(_do_add)
        dialog.show()

    def _on_edit_row(self, row: int) -> None:
        item = self._table.item(row, _COL_TAG)
        if item is None:
            return
        tag = item.text()
        entry = self._model.find(tag)
        if entry is None:
            return

        def _on_waveform_accepted(updated_entry: TagEntry) -> None:
            # Explicit editing is the opt-in required for custom tags.
            updated_entry.enabled = True
            self._update_row(row, updated_entry)
            self._refresh_empty_state()

        dlg = _WaveformDialog(entry, self)
        dlg.accepted.connect(_on_waveform_accepted)
        dlg.show()

    def _on_remove_tag(self, tag: str) -> None:
        if self._sending:
            QMessageBox.warning(
                self,
                "Sender Active",
                "Stop the sender before removing tags.",
            )
            return
        row = self._row_for_tag(tag)
        if row >= 0:
            self._table.removeRow(row)
        self._model.remove_tag(tag)
        self._refresh_empty_state()
