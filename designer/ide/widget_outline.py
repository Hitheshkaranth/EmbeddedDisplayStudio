"""designer/ide/widget_outline.py -- every widget of the design, at a glance.

The Widgets picker (widget_picker.py) shows the current page with
thumbnails. The Outline shows the WHOLE design as a tree, with what each
widget is wired to, so "which widgets does this design use, and what do
they read and write?" has one answer on one screen:

    2 pages, 10 widgets, 6 types, 6 tags, 2 issues        <- summary_label
    [filter        ] [All] [Bound] [Issues]   [tag: ai.rpm x]
    Widget                       Tags                 Issues
    v Main (5)
        rpm       ShGauge        ai.rpm
      v panel     ShCard
          pump    ShToggle       do.pump (rw)
          horn    ShButton       do.horn (w)
        next      ShButton       -> Alarms
    v Alarms (5)
        oil       ShNumDisplay   ai.oiltemp           1
        broken    ShNumDisplay                        1

Columns (COLUMNS): "Widget", "Tags", "Issues".
    Widget -- page rows: f"{page_name} ({number of widgets on it})";
              widget rows: f"{id}  {type}" (two spaces).
    Tags   -- widget_tags_text(entry, index): the widget's tags, ", "-joined,
              in this order: tags only read -> "tag"; read and written ->
              "tag (rw)"; only written -> "tag (w)"; then each navigate
              action -> "-> <target page name>" (page id when unknown).
              '' when none.
    Issues -- number of index.issues_for(id) rows, '' when 0. The row's
              Issues cell tooltip lists each row's detail, one per line.
Every widget row's tooltip (column 0) is widget_tooltip(entry, index):
    "<id> (<type>)", "Page: <page name>", "Geometry: x, y, w x h" (ints),
    then "Binds <property> <- <tag>" per binding and
    "On <signal>: <kind> <target>" per action, one per line.

Rows: Qt.UserRole of column 0 holds the widget id ('' for a page row);
page rows hold their page index in PAGE_ROLE. Tree order = index order.
All items expanded after a rebuild.

summary_label: summary_text(index.summary()) --
    f"{pages} pages, {widgets} widgets, {types} types, {tags} tags, {issues} issues"
with singular words for a count of exactly 1 ("1 page", "1 issue"). Its
tooltip lists index.type_counts() as "<type>: <n>" lines.

Filtering (all combined with AND; a page row is shown when any of its
widgets is; a container row is shown when it or any descendant matches):
    filter_edit  -- case-insensitive substring of id, type or Tags text.
    mode         -- set_mode("all" | "bound" | "issues"): bound = widgets
                    with tags_read() or tags_written(); issues = widgets
                    with issues_for(). The three buttons are exclusive
                    checkable QToolButtons (mode_buttons dict by mode).
    show_tag(tag)-- only widgets in index.widgets_using(tag); shows
                    `tag_chip` (a QPushButton "tag: <tag>  x", clicking it
                    calls show_tag("")); show_tag("") hides the chip.

Interaction:
    click a widget row   -> pick(widget_id)
    double-click         -> sourceRequested(widget_id, entry.line)
pick(widget_id): when the widget is on another page than
workspace.current_page_index, workspace.change_page(page_index) first; then
workspace.select_widget(widget_id); highlight it; emit widgetPicked(id).
The Designer's selection (workspace.scene.selectionIdsChanged, one id)
highlights the matching row without emitting anything (connect it once in
__init__).

The outline never builds its own index: the Code section calls
set_index() whenever the design changes.

Attributes tests rely on: `tree` (QTreeWidget), `filter_edit`,
`summary_label`, `tag_chip`, `mode_buttons`.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from designer.ide.design_index import DesignIndex
from designer.ide.project_files import _rgba, color

COLUMNS = ("Widget", "Tags", "Issues")
PAGE_ROLE = Qt.UserRole + 2
MODES = ("all", "bound", "issues")

# The real theme has "destructive"; the fallback token table does not.
_DESTRUCTIVE_FALLBACK = "#ef4444"


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def summary_text(summary: dict) -> str:
    """See the module docstring, summary_label."""
    return ", ".join(_count(int(summary.get(key, 0)), word) for key, word in (
        ("pages", "page"), ("widgets", "widget"), ("types", "type"), ("tags", "tag"), ("issues", "issue")))


def _page_name(index: DesignIndex, page_id: str) -> str:
    for page in getattr(index.project, "pages", None) or []:
        if page.id == page_id:
            return page.name
    return page_id


def widget_tags_text(entry, index: DesignIndex) -> str:
    """See the module docstring, Tags column."""
    read, written = entry.tags_read(), entry.tags_written()
    parts = [tag for tag in read if tag not in written]
    parts += [f"{tag} (rw)" for tag in read if tag in written]
    parts += [f"{tag} (w)" for tag in written if tag not in read]
    parts += [f"-> {_page_name(index, target)}" for _signal, kind, target in entry.actions if kind == "navigate"]
    return ", ".join(parts)


def widget_tooltip(entry, index: DesignIndex) -> str:
    """See the module docstring, tooltips."""
    x, y, w, h = (int(v) for v in entry.geometry)
    lines = [f"{entry.id} ({entry.type})", f"Page: {entry.page_name}", f"Geometry: {x}, {y}, {w} x {h}"]
    lines += [f"Binds {prop} <- {tag}" for prop, tag in entry.bindings]
    lines += [f"On {signal}: {kind} {target}" for signal, kind, target in entry.actions]
    return "\n".join(lines)


class WidgetOutline(QWidget):
    """Signals:
        widgetPicked(str): a widget row was clicked (after pick() did its work).
        sourceRequested(str, int): double-click; widget id and its
            project.edsui line (0 = unknown).
    """

    widgetPicked = Signal(str)
    sourceRequested = Signal(str, int)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.setObjectName("widgetOutline")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._workspace = workspace
        self._index: DesignIndex | None = None
        self._items: dict = {}
        self._page_items: list = []
        self._mode = "all"
        self._tag = ""
        self._theme = "dark"

        self.summary_label = QLabel()
        self.summary_label.setObjectName("widgetOutlineSummary")

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("widgetOutlineFilter")
        self.filter_edit.setPlaceholderText("Filter by id, type or tag")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filters)

        self.mode_buttons = {}
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for mode in MODES:
            button = QToolButton()
            button.setObjectName("widgetOutlineMode")
            button.setText(mode.capitalize())
            button.setCheckable(True)
            # clicked, not toggled: set_mode() checks the button itself and
            # must not re-enter through the signal.
            button.clicked.connect(lambda _checked=False, m=mode: self.set_mode(m))
            self._mode_group.addButton(button)
            self.mode_buttons[mode] = button
        self.mode_buttons["all"].setChecked(True)

        self.tag_chip = QPushButton()
        self.tag_chip.setObjectName("widgetOutlineTagChip")
        self.tag_chip.hide()
        self.tag_chip.clicked.connect(lambda _checked=False: self.show_tag(""))

        self.tree = QTreeWidget()
        self.tree.setObjectName("widgetOutlineTree")
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        # Column 0 follows the tree's width (see eventFilter).
        self.tree.viewport().installEventFilter(self)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)

        bar = QHBoxLayout()
        bar.setContentsMargins(4, 4, 4, 4)
        bar.setSpacing(4)
        bar.addWidget(self.filter_edit, 1)
        for mode in MODES:
            bar.addWidget(self.mode_buttons[mode])
        bar.addWidget(self.tag_chip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.summary_label)
        layout.addLayout(bar)
        layout.addWidget(self.tree, 1)

        self._workspace.scene.selectionIdsChanged.connect(self._follow_selection)
        self.apply_theme("dark")

    def set_index(self, index: DesignIndex | None) -> None:
        """Rebuilds the tree (None -> empty), keeping filter, mode, tag and
        the vertical scroll position; re-highlights the Designer's selection."""
        scroll = self.tree.verticalScrollBar().value()
        self._index = index
        self._items = {}
        self._page_items = []
        self.tree.clear()
        if index is None:
            self.summary_label.setText("")
            self.summary_label.setToolTip("")
            return
        self.summary_label.setText(summary_text(index.summary()))
        self.summary_label.setToolTip("\n".join(f"{t}: {n}" for t, n in index.type_counts().items()))
        self._build(index)
        self.tree.expandAll()
        self._apply_filters()
        selected = self._workspace.selected_widget()
        self._highlight(selected.id if selected is not None else "", scroll_to=False)
        self.tree.verticalScrollBar().setValue(scroll)

    def index(self) -> DesignIndex | None:
        return self._index

    def widget_ids(self) -> list:
        """Ids of the widget rows currently shown, tree order (pre-order)."""
        if self._index is None:
            return []
        return [entry.id for entry in self._index.widgets()
                if entry.id in self._items and not self._items[entry.id].isHidden()]

    def item_for(self, widget_id: str):
        """The QTreeWidgetItem of that widget, or None."""
        return self._items.get(widget_id)

    def highlighted_id(self) -> str:
        """Id of the current widget row, or ''."""
        item = self.tree.currentItem()
        return (item.data(0, Qt.ItemDataRole.UserRole) or "") if item is not None else ""

    def set_filter(self, text: str) -> None:
        if self.filter_edit.text() == text:
            self._apply_filters()
        else:
            self.filter_edit.setText(text)  # textChanged applies it

    def set_mode(self, mode: str) -> None:
        """'all' | 'bound' | 'issues'; anything else -> ValueError."""
        if mode not in MODES:
            raise ValueError(f"unknown outline mode {mode!r}; expected one of {', '.join(MODES)}")
        self._mode = mode
        self.mode_buttons[mode].setChecked(True)
        self._apply_filters()

    def mode(self) -> str:
        return self._mode

    def show_tag(self, tag: str) -> None:
        self._tag = tag or ""
        if self._tag:
            self.tag_chip.setText(f"tag: {self._tag}  x")
            self.tag_chip.show()
        else:
            self.tag_chip.hide()
        self._apply_filters()

    def shown_tag(self) -> str:
        return self._tag

    def pick(self, widget_id: str) -> None:
        entry = self._index.widget(widget_id) if self._index is not None else None
        if entry is not None and entry.page_index != self._workspace.current_page_index:
            self._workspace.change_page(entry.page_index)
        self._workspace.select_widget(widget_id)
        self._highlight(widget_id)
        self.widgetPicked.emit(widget_id)

    def eventFilter(self, watched, event) -> bool:
        # Id + type get a bit more than half of the tree's own width, the
        # tags the rest: a fixed width starves the tags in a narrow pane.
        if watched is self.tree.viewport() and event.type() == QEvent.Resize:
            width = event.size().width()
            if width > 0:
                self.tree.header().resizeSection(0, max(120, int(width * 0.56)))
        return super().eventFilter(watched, event)

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'. Issue counts use the theme's destructive colour."""
        self._theme = "light" if theme == "light" else "dark"
        t = self._theme
        bg, fg, border = color("background", t), color("foreground", t), color("border", t)
        primary, muted = color("primary", t), color("mutedForeground", t)
        self.setStyleSheet(f"""
            QWidget#widgetOutline {{ background: {bg}; }}
            QLabel#widgetOutlineSummary {{ color: {muted}; font-size: 11px; padding: 4px 8px; }}
            QLineEdit#widgetOutlineFilter {{
                background: {bg}; color: {fg}; border: none; border-bottom: 1px solid {border};
                padding: 5px 8px; font-size: 12px;
            }}
            QToolButton#widgetOutlineMode {{
                background: transparent; color: {muted}; border: 1px solid {border};
                border-radius: 4px; padding: 2px 8px; font-size: 11px;
            }}
            QToolButton#widgetOutlineMode:checked {{
                background: {_rgba(primary, 0.16)}; color: {fg}; border-color: {primary};
            }}
            QPushButton#widgetOutlineTagChip {{
                background: {_rgba(primary, 0.16)}; color: {fg}; border: none;
                border-radius: 9px; padding: 2px 10px; font-size: 11px;
            }}
            QTreeWidget#widgetOutlineTree {{
                background: {bg}; color: {fg}; border: none; font-size: 12px; outline: 0;
            }}
            QTreeWidget#widgetOutlineTree::item:hover {{ background: {_rgba(fg, 0.06)}; }}
            QTreeWidget#widgetOutlineTree::item:selected {{
                background: {_rgba(primary, 0.16)}; color: {fg};
            }}
        """)
        brush = QBrush(QColor(self._issue_color()))
        for item in self._items.values():
            if item.text(2):
                item.setForeground(2, brush)

    # ---------------------------------------------------------------- private

    def _issue_color(self) -> str:
        try:
            return color("destructive", self._theme)
        except KeyError:
            return _DESTRUCTIVE_FALLBACK

    def _build(self, index: DesignIndex) -> None:
        pages = list(getattr(index.project, "pages", None) or [])
        for page_index, page in enumerate(pages):
            item = QTreeWidgetItem([f"{page.name} ({len(index.widgets(page_index))})", "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, "")
            item.setData(0, PAGE_ROLE, page_index)
            self.tree.addTopLevelItem(item)
            self._page_items.append(item)
        issue_brush = QBrush(QColor(self._issue_color()))
        # index.widgets() is pre-order: a container's item always exists
        # before its children's.
        for entry in index.widgets():
            issues = index.issues_for(entry.id)
            item = QTreeWidgetItem([f"{entry.id}  {entry.type}", widget_tags_text(entry, index),
                                    str(len(issues)) if issues else ""])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.id)
            item.setToolTip(0, widget_tooltip(entry, index))
            if issues:
                item.setToolTip(2, "\n".join(row.detail for row in issues))
                item.setForeground(2, issue_brush)
            parent = self._items.get(entry.parent_id) if entry.parent_id else None
            if parent is None:
                parent = self._page_items[entry.page_index]
            parent.addChild(item)
            self._items.setdefault(entry.id, item)

    def _matches(self, entry, needle: str, tagged: set) -> bool:
        index = self._index
        if needle and not any(needle in text.lower()
                              for text in (entry.id, entry.type, widget_tags_text(entry, index))):
            return False
        if self._mode == "bound" and not (entry.tags_read() or entry.tags_written()):
            return False
        if self._mode == "issues" and not index.issues_for(entry.id):
            return False
        if self._tag and entry.id not in tagged:
            return False
        return True

    def _apply_filters(self, *_args) -> None:
        if self._index is None:
            return
        needle = self.filter_edit.text().strip().lower()
        tagged = set(self._index.widgets_using(self._tag)) if self._tag else set()
        entries = self._index.widgets()
        shown: set = set()
        # Reversed pre-order visits every child before its container, so a
        # container already knows whether a descendant is shown.
        for entry in reversed(entries):
            if entry.id in shown or self._matches(entry, needle, tagged):
                shown.add(entry.id)
                if entry.parent_id:
                    shown.add(entry.parent_id)
        pages_shown = set()
        for entry in entries:
            item = self._items.get(entry.id)
            if item is None:
                continue
            item.setHidden(entry.id not in shown)
            if entry.id in shown:
                pages_shown.add(entry.page_index)
        for page_index, item in enumerate(self._page_items):
            item.setHidden(page_index not in pages_shown)

    def _highlight(self, widget_id: str, scroll_to: bool = True) -> None:
        item = self._items.get(widget_id) if widget_id else None
        # Mirrors a selection made elsewhere: must not look like a click.
        self.tree.blockSignals(True)
        try:
            if item is None:
                self.tree.clearSelection()
                self.tree.setCurrentItem(None)
            else:
                self.tree.setCurrentItem(item)
                if scroll_to:
                    self.tree.scrollToItem(item)
        finally:
            self.tree.blockSignals(False)

    def _follow_selection(self, ids) -> None:
        ids = list(ids or [])
        self._highlight(ids[0] if len(ids) == 1 else "")

    def _on_clicked(self, item, _column: int) -> None:
        widget_id = item.data(0, Qt.ItemDataRole.UserRole)
        if widget_id:
            self.pick(widget_id)

    def _on_double_clicked(self, item, _column: int) -> None:
        widget_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not widget_id:
            return
        entry = self._index.widget(widget_id) if self._index is not None else None
        self.sourceRequested.emit(widget_id, entry.line if entry is not None else 0)


__all__ = ["WidgetOutline", "summary_text", "widget_tags_text", "widget_tooltip", "COLUMNS", "PAGE_ROLE",
           "MODES"]

# Imported for the implementation; keeps the skeleton's import list stable.
_ = (QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QToolButton,
     QTreeWidget, QTreeWidgetItem, QVBoxLayout, _rgba, color)
