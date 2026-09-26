"""designer/ide/tag_panel.py -- the Code section's "Backend" pane.

What the design exchanges with the backend, and what the backend says right
now. One row per tag of the DesignIndex (DesignIndex.tags(), sorted):

    Tag          Access  Used by           Value     Status
    ai.fuel              -                 --        unused
    ai.oiltemp   R       oil               52.113    not declared
    ai.rpm       R       rpm, rpm2         3120.5    ok
    do.pump      RW      pump              true      ok

Columns (COLUMNS, in this order):
    Tag     -- the tag name.
    Access  -- TagEntry.access ('R', 'W', 'RW', or '').
    Used by -- ids from index.widgets_using(tag) joined with ", "; "-" when none.
    Value   -- format_value(source value): "--" for None/no source, "true"/
               "false" for bools, ints as-is, floats with up to 3 decimals
               and no trailing zeros ("3120.5", "52.113", "0"), strings as-is.
    Status  -- status_for(entry): "unused" when access is '', else
               "not declared" when not entry.declared, else "ok". Rows whose
               status is not "ok" are drawn in the theme's muted colour
               ("unused") or warning colour ("not declared").

Above the table: a status line `source_label` -- "Source: <name> (online)"
/ "Source: <name> (offline)" / "Source: none" -- and a filter field
`filter_edit` (case-insensitive substring of the tag or of "Used by").
Below: buttons "Copy tags" (copy_tags(): every tag name, one per line, to
the clipboard) and "Generate backend..." (emits scaffoldRequested()).

Values refresh from the source on a REFRESH_MS QTimer that runs only while
the pane is visible AND a source is set (refresh_values() does one pass;
tests call it directly). Also on the source's valuesChanged, throttled to at
most one refresh per REFRESH_MS. Only the Value column changes on refresh;
the table is rebuilt only by set_index().

Interaction:
    click a row          -> tagActivated(tag)
    double-click a row   -> tagActivated(tag), and for a writable tag
                            (entry.writable) with a source that can_write():
                            request_write(tag) -- asks for a value (QInputDialog
                            getText; tests call write_value directly).
    context menu         -> "Copy tag", "Write value..." (enabled as above).
write_value(tag, text) parses text: "true"/"false"/"on"/"off"/"1"/"0" for
di./do. tags -> bool; else float (int when it has no fraction part);
unparsable -> False and message("Not a value: <text>"). Otherwise
source.write(tag, value) and message(f"Wrote {tag} = {value}") on success,
message(f"Write refused: {tag}") on failure; returns the write's result.

Attributes tests rely on: `table` (QTableWidget, one row per tag, the tag
in column 0's text), `filter_edit`, `source_label`, `copy_button`,
`scaffold_button`.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from designer.ide.design_index import DesignIndex
from designer.ide.project_files import _rgba, color

COLUMNS = ("Tag", "Access", "Used by", "Value", "Status")
TAG_COL, ACCESS_COL, USED_COL, VALUE_COL, STATUS_COL = range(5)
REFRESH_MS = 250

# A "not ok" status is drawn muted ("unused") or in the warning colour.
_STATUS_OK = "ok"
_STATUS_UNUSED = "unused"
_STATUS_NOT_DECLARED = "not declared"


def format_value(value) -> str:
    """See the module docstring, Value column."""
    if value is None:
        return "--"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-", "-0") else text
    return str(value)


def status_for(entry) -> str:
    """See the module docstring, Status column."""
    access = entry.access
    if access == "":
        return _STATUS_UNUSED
    if not entry.declared:
        return _STATUS_NOT_DECLARED
    return _STATUS_OK


class TagPanel(QWidget):
    """Signals:
        tagActivated(str): a row was clicked / double-clicked.
        scaffoldRequested(): "Generate backend..." was clicked.
        message(str): status-line text.
    """

    tagActivated = Signal(str)
    scaffoldRequested = Signal()
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tagPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._theme = "dark"
        self._index: DesignIndex | None = None
        self._source = None
        self._tag_rows: dict[str, int] = {}

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("tagPanelFilter")
        self.filter_edit.setPlaceholderText("Filter tags")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("tagPanelTable")
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # The tag and its value are what the pane is for: they keep their
        # width, "Used by" takes what is left and is elided (tooltip has all).
        header.setSectionResizeMode(TAG_COL, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(ACCESS_COL, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(USED_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(VALUE_COL, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(STATUS_COL, QHeaderView.ResizeMode.ResizeToContents)
        header.setMinimumSectionSize(36)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setWordWrap(False)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.customContextMenuRequested.connect(self._show_menu)

        self.source_label = QLabel("Source: none")
        self.source_label.setObjectName("tagPanelSource")

        self.copy_button = QPushButton("Copy tags")
        self.copy_button.clicked.connect(self.copy_tags)
        self.scaffold_button = QPushButton("Generate backend...")
        self.scaffold_button.clicked.connect(self.scaffoldRequested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.source_label)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(self.copy_button)
        row.addWidget(self.scaffold_button)
        row.addStretch(1)
        layout.addLayout(row)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(False)
        self._refresh_timer.setInterval(REFRESH_MS)
        self._refresh_timer.timeout.connect(self._on_refresh_timer)

        self._throttle_timer = QTimer(self)
        self._throttle_timer.setSingleShot(True)
        self._throttle_timer.setInterval(REFRESH_MS)
        self._throttle_timer.timeout.connect(self._refresh)

        self._last_refresh = 0.0
        self._menu = QMenu(self)
        self._menu_tag = ""
        self._copy_action = self._menu.addAction("Copy tag", self._copy_tag)
        self._write_action = self._menu.addAction("Write value...", self._write_value_action)

        self.apply_theme("dark")

    def set_index(self, index: DesignIndex | None) -> None:
        """Rebuilds the table from index.tags() (None -> empty), keeping the
        filter, then refresh_values()."""
        self._index = index
        self._tag_rows = {}
        tags = index.tags() if index is not None else []
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(tags))
            for row, entry in enumerate(tags):
                self._tag_rows[entry.tag] = row
                self.table.setItem(row, TAG_COL, QTableWidgetItem(entry.tag))
                self.table.setItem(row, ACCESS_COL, QTableWidgetItem(entry.access))
                used = index.widgets_using(entry.tag)
                used_item = QTableWidgetItem(", ".join(used) if used else "-")
                used_item.setToolTip("\n".join(used))
                self.table.setItem(row, USED_COL, used_item)
                self.table.setItem(row, VALUE_COL, QTableWidgetItem("--"))
                self.table.setItem(row, STATUS_COL, QTableWidgetItem(status_for(entry)))
        finally:
            self.table.blockSignals(False)
        self._colour_rows()
        self._apply_filter(self.filter_edit.text())
        self.refresh_values()

    def set_source(self, source) -> None:
        """A designer.ide.tag_source.TagSource, or None. Disconnects the
        previous one's signals (never stops it: the caller owns sources),
        connects valuesChanged/onlineChanged, updates source_label, starts or
        stops the refresh timer, refresh_values()."""
        if self._source is not None:
            try:
                self._source.valuesChanged.disconnect(self._on_values_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                self._source.onlineChanged.disconnect(self._on_online_changed)
            except (TypeError, RuntimeError):
                pass
        self._source = source
        if source is not None:
            source.valuesChanged.connect(self._on_values_changed)
            source.onlineChanged.connect(self._on_online_changed)
            self._update_source_label()
            if self.isVisible():
                self._refresh_timer.start()
        else:
            self._refresh_timer.stop()
            self.source_label.setText("Source: none")
        self.refresh_values()

    def source(self):
        return self._source

    def tags(self) -> list:
        """Tag names of the rows currently shown (filter applied), top to bottom."""
        out = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, TAG_COL)
            if item is None:
                continue
            out.append(item.text())
        return out

    def value_text(self, tag: str) -> str:
        """The Value cell's text for `tag` ('' when no such row)."""
        row = self._tag_rows.get(tag)
        if row is None:
            return ""
        item = self.table.item(row, VALUE_COL)
        return item.text() if item is not None else ""

    def status_text(self, tag: str) -> str:
        """The Status cell's text for `tag` ('' when no such row)."""
        row = self._tag_rows.get(tag)
        if row is None:
            return ""
        item = self.table.item(row, STATUS_COL)
        return item.text() if item is not None else ""

    def refresh_values(self) -> None:
        """One pass: source.snapshot(all tags) into the Value column."""
        self._refresh()

    def _refresh(self) -> None:
        self._last_refresh = time.monotonic()
        if self._source is None:
            self._fill_values("--")
            return
        self._do_refresh()

    def _do_refresh(self) -> None:
        if self._source is None or self._index is None:
            self._fill_values("--")
            return
        self._last_refresh = time.monotonic()
        values = self._source.snapshot(list(self._tag_rows))
        by_row = {self.table.item(r, TAG_COL).text(): r
                  for r in range(self.table.rowCount())
                  if self.table.item(r, TAG_COL) is not None}
        self.table.blockSignals(True)
        try:
            for tag, value in values.items():
                row = by_row.get(tag)
                if row is not None:
                    self.table.item(row, VALUE_COL).setText(format_value(value))
        finally:
            self.table.blockSignals(False)

    def _fill_values(self, text: str) -> None:
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, VALUE_COL)
                if item is not None:
                    item.setText(text)
        finally:
            self.table.blockSignals(False)

    def set_filter(self, text: str) -> None:
        """Same as typing into filter_edit."""
        self.filter_edit.setText(text)

    def select_tag(self, tag: str) -> None:
        """Selects and scrolls to that tag's row, without emitting tagActivated."""
        row = self._tag_rows.get(tag)
        if row is None:
            return
        index = self.table.model().index(row, TAG_COL)
        if not index.isValid():
            return
        self.table.blockSignals(True)
        try:
            self.table.selectRow(row)
            self.table.scrollTo(index)
        finally:
            self.table.blockSignals(False)

    def copy_tags(self) -> str:
        """Copies every tag name (all rows, filter ignored), one per line, to
        the clipboard and returns that text."""
        all_tags = []
        if self._index is not None:
            all_tags = [entry.tag for entry in self._index.tags()]
        text = "\n".join(all_tags)
        QApplication.clipboard().setText(text)
        return text

    def request_write(self, tag: str) -> None:
        """Asks the user for a value (QInputDialog.getText) and write_value()s it."""
        text, ok = QInputDialog.getText(self, "Write value", f"New value for {tag}:")
        if not ok:
            return
        self.write_value(tag, text)

    def write_value(self, tag: str, text: str) -> bool:
        """See the module docstring, Interaction."""
        entry = None if self._index is None else self._index.tag(tag)
        is_di_do = tag is not None and (tag.startswith("di.") or tag.startswith("do."))

        if text is None:
            value = None
        else:
            stripped = text.strip()
            if is_di_do:
                low = stripped.lower()
                if low in ("true", "on", "1"):
                    value = True
                elif low in ("false", "off", "0"):
                    value = False
                else:
                    value = None
            elif "e" in stripped or "E" in stripped or "." in stripped:
                try:
                    value = float(stripped)
                except ValueError:
                    value = None
            else:
                try:
                    value = int(stripped)
                except ValueError:
                    value = None

        if value is None:
            self.message.emit(f"Not a value: {text}")
            return False

        if self._source is None or not self._source.can_write():
            self.message.emit(f"Write refused: {tag}")
            return False

        result = self._source.write(tag, value)
        if result:
            self.message.emit(f"Wrote {tag} = {value}")
        else:
            self.message.emit(f"Write refused: {tag}")
        return result

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        self._theme = "light" if theme == "light" else "dark"
        t = self._theme
        bg = self._token("background", t)
        fg = self._token("foreground", t)
        border = self._token("border", t)
        muted = self._token("mutedForeground", t)
        primary = self._token("primary", t)
        warning = self._token("warning", t)
        self.setStyleSheet(f"""
            QWidget#tagPanel {{ background: {bg}; color: {fg}; }}
            QLineEdit#tagPanelFilter {{
                background: {bg}; color: {fg}; border: none; border-bottom: 1px solid {border};
                padding: 5px 8px; font-size: 12px;
            }}
            QLabel#tagPanelSource {{ color: {muted}; font-size: 11px; padding: 2px 4px; }}
            QTableWidget#tagPanelTable {{
                background: {bg}; color: {fg}; border: 1px solid {border}; font-size: 12px; outline: 0;
            }}
            QTableWidget#tagPanelTable::item {{ padding: 2px 4px; }}
            QTableWidget#tagPanelTable::item:selected {{
                background: {_rgba(primary, 0.16)}; color: {fg};
            }}
            QHeaderView::section {{
                background: {bg}; color: {fg}; border: none; padding: 4px 6px; font-size: 12px;
            }}
            QLabel#tagPanelSourceEmpty {{ color: {muted}; font-size: 12px; }}
        """)
        self._colour_rows()

    # ------------------------------------------------------------ private

    @staticmethod
    def _token(name, theme):
        try:
            return color(name, theme)
        except KeyError:
            defaults = {
                "destructive": "#ef4444",
                "warning": "#f59e0b",
                "success": "#22c55e",
            }
            return defaults.get(name, "#fafafa" if theme == "dark" else "#09090b")

    def _colour_rows(self) -> None:
        muted = QColor(self._token("mutedForeground", self._theme))
        warning = QColor(self._token("warning", self._theme))
        for row in range(self.table.rowCount()):
            item = self.table.item(row, STATUS_COL)
            if item is None:
                continue
            tint = {_STATUS_UNUSED: muted, _STATUS_NOT_DECLARED: warning}.get(item.text())
            for col in range(self.table.columnCount()):
                cell = self.table.item(row, col)
                if cell is not None:
                    cell.setForeground(tint if tint is not None else QBrush())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.table.rowCount()):
            tag_item = self.table.item(row, TAG_COL)
            if tag_item is None:
                continue
            tag = tag_item.text()
            used_item = self.table.item(row, USED_COL)
            used = (used_item.text() if used_item is not None else "")
            show = not needle or needle in tag.lower() or needle in used.lower()
            self.table.setRowHidden(row, not show)

    def _cell_row(self, row: int):
        item = self.table.item(row, TAG_COL)
        return item.text() if item is not None else None

    def _on_cell_clicked(self, row, _column):
        tag = self._cell_row(row)
        if tag is not None:
            self.tagActivated.emit(tag)

    def _on_cell_double_clicked(self, row, _column):
        tag = self._cell_row(row)
        if tag is None:
            return
        self.tagActivated.emit(tag)
        entry = None if self._index is None else self._index.tag(tag)
        if entry is not None and entry.writable and self._source is not None \
                and self._source.can_write():
            self.request_write(tag)

    def _show_menu(self, pos):
        row = self.table.rowAt(pos.y())
        tag = self._cell_row(row)
        writable = (tag is not None and self._index is not None
                    and self._index.tag(tag) is not None
                    and self._index.tag(tag).writable)
        self._write_action.setEnabled(bool(writable and self._source is not None
                                           and self._source.can_write()))
        if tag is not None:
            self._menu_tag = tag
            self._menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_tag(self) -> None:
        if self._menu_tag:
            QApplication.clipboard().setText(self._menu_tag)

    def _write_value_action(self) -> None:
        if self._menu_tag:
            self.request_write(self._menu_tag)

    def _update_source_label(self) -> None:
        if self._source is None:
            self.source_label.setText("Source: none")
        elif self._source.is_online():
            self.source_label.setText(f"Source: {self._source.name()} (online)")
        else:
            self.source_label.setText(f"Source: {self._source.name()} (offline)")

    def _on_online_changed(self, _online) -> None:
        self._update_source_label()

    def _on_values_changed(self) -> None:
        remaining = REFRESH_MS - int((time.monotonic() - self._last_refresh) * 1000)
        if remaining > 0:
            self._throttle_timer.start(remaining)
        else:
            self._throttle_timer.stop()
            self.refresh_values()

    def _on_refresh_timer(self) -> None:
        if self.isVisible():
            self.refresh_values()

    def showEvent(self, event):
        super().showEvent(event)
        if self._source is not None:
            self._refresh_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._refresh_timer.stop()


__all__ = ["TagPanel", "format_value", "status_for", "COLUMNS", "REFRESH_MS"]

# Imported for the implementation; keeps the skeleton's import list stable.

_ = (Qt, QTimer, QApplication, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton,
      QTableWidget, QTableWidgetItem, QVBoxLayout, _rgba, color)