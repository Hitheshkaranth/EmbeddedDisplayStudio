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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from designer.ide.design_index import DesignIndex
from designer.ide.project_files import _rgba, color

COLUMNS = ("Widget", "Tags", "Issues")
PAGE_ROLE = Qt.UserRole + 2
MODES = ("all", "bound", "issues")


def summary_text(summary: dict) -> str:
    """See the module docstring, summary_label."""
    def word(name, n):
        return f"{n} {name}" if n == 1 else f"{n} {name}s"
    return (f"{word('page', summary['pages'])}, {word('widget', summary['widgets'])}, "
            f"{word('type', summary['types'])}, {summary['tags']} tags, "
            f"{word('issue', summary['issues'])}")


def widget_tags_text(entry, index: DesignIndex) -> str:
    """See the module docstring, Tags column."""
    def page_name(page_id):
        if index.project is None:
            return page_id
        for page in index.project.pages:
            if page.id == page_id:
                return page.name
        return page_id

    tags = []
    read = list(entry.tags_read())
    written = list(entry.tags_written())
    for tag in read:
        if tag in written:
            tags.append(f"{tag} (rw)")
        else:
            tags.append(f"{tag}")
    for tag in written:
        if tag not in read:
            tags.append(f"{tag} (w)")
    for _signal, kind, target in entry.actions:
        if kind == "navigate":
            tags.append(f"-> {page_name(target)}")
    return "  ".join(tags)


def widget_tooltip(entry, index: DesignIndex) -> str:
    """See the module docstring, tooltips."""
    x, y, w, h = entry.geometry
    lines = [f"{entry.id} ({entry.type})", f"Page: {entry.page_name}",
             f"Geometry: {int(x)}, {int(y)}, {int(w)} x {int(h)}"]
    for prop, tag in entry.bindings:
        lines.append(f"Binds {prop} <- {tag}")
    for signal, kind, target in entry.actions:
        lines.append(f"On {signal}: {kind} {target}")
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
        self._workspace = workspace
        self._theme = "dark"
        self._index = None
        self._items = {}
        self._page_items = []
        self._mode = "all"
        self._shown_tag = ""

        self.summary_label = QLabel()
        self.summary_label.setObjectName("widgetOutlineSummary")
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("widgetOutlineFilter")
        self.filter_edit.setPlaceholderText("Filter widgets")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.set_filter)

        self.mode_buttons = {}
        mode_bar = QHBoxLayout()
        mode_bar.setContentsMargins(0, 0, 0, 0)
        mode_bar.setSpacing(4)
        for mode in MODES:
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setText(mode.capitalize())
            button.setObjectName(f"widgetOutlineMode{mode.capitalize()}")
            mode_bar.addWidget(button, 1)
            self.mode_buttons[mode] = button
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        for mode, button in self.mode_buttons.items():
            mode_group.addButton(button, {"all": 0, "bound": 1, "issues": 2}[mode])
            button.toggled.connect(lambda checked, m=mode: checked and self.set_mode(m))
        self.mode_buttons["all"].setChecked(True)

        self.tag_chip = QPushButton()
        self.tag_chip.setObjectName("widgetOutlineTagChip")
        self.tag_chip.setHidden(True)
        self.tag_chip.clicked.connect(lambda _check: self.show_tag(""))

        tree = QTreeWidget()
        tree.setObjectName("widgetOutlineTree")
        tree.setColumnCount(len(COLUMNS))
        tree.setHeaderLabels(COLUMNS)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setAlternatingRowColors(True)
        tree.itemClicked.connect(self._on_click)
        tree.itemDoubleClicked.connect(self._on_double_click)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.summary_label)
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(4, 4, 4, 4)
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addLayout(mode_bar, 1)
        filter_row.addWidget(self.tag_chip)
        layout.addLayout(filter_row)
        layout.addWidget(tree, 1)

        self.tree = tree
        self._workspace.scene.selectionIdsChanged.connect(self._follow_selection)
        self.apply_theme("dark")

    # ----------------------------------------------------------------- public

    def set_index(self, index: DesignIndex | None) -> None:
        """Rebuilds the tree (None -> empty), keeping filter, mode, tag and
        the vertical scroll position; re-highlights the Designer's selection."""
        scroll = self.tree.verticalScrollBar().value()
        self._index = index
        self._items.clear()
        self._page_items.clear()
        self.tree.clear()
        if index is not None:
            self._build(index)
            self._apply_filters()
        self.summary_label.setText(summary_text(index.summary()) if index is not None else "")
        self._highlight(self.highlighted_id())
        self.tree.verticalScrollBar().setValue(scroll)

    def index(self) -> DesignIndex | None:
        return self._index

    def widget_ids(self) -> list:
        """Ids of the widget rows currently shown, tree order (pre-order)."""
        return [item.data(0, Qt.UserRole) for item in self._items.values()
                if not item.isHidden()]

    def item_for(self, widget_id: str):
        """The QTreeWidgetItem of that widget, or None."""
        return self._items.get(widget_id)

    def highlighted_id(self) -> str:
        """Id of the current widget row, or ''."""
        selected = self.tree.selectedItems()
        if not selected:
            return ""
        item = selected[0]
        return item.data(0, Qt.UserRole) if item.data(0, Qt.UserRole) else ""

    def set_filter(self, text: str) -> None:
        self.filter_edit.setText(text)
        self._apply_filters()

    def set_mode(self, mode: str) -> None:
        """'all' | 'bound' | 'issues'; anything else -> ValueError."""
        if mode not in MODES:
            raise ValueError(f"Unknown outline mode: {mode!r}")
        self._mode = mode
        for name, button in self.mode_buttons.items():
            button.setChecked(name == mode)
        self._apply_filters()

    def mode(self) -> str:
        return self._mode

    def show_tag(self, tag: str) -> None:
        if tag:
            self._shown_tag = tag
            self.tag_chip.setText(f"tag: {tag}  x")
            self.tag_chip.setVisible(True)
        else:
            self._shown_tag = ""
            self.tag_chip.setVisible(False)
        self._apply_filters()

    def shown_tag(self) -> str:
        return self._shown_tag

    def pick(self, widget_id: str) -> None:
        """What clicking a widget row does: switch to its page, select it,
        highlight it, emit widgetPicked."""
        entry = self._index.widget(widget_id) if self._index else None
        if entry is not None and entry.page_index != self._workspace.current_page_index:
            self._workspace.change_page(entry.page_index)
        self._workspace.select_widget(widget_id)
        self._highlight(widget_id)
        self.widgetPicked.emit(widget_id)

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'. Issue counts use the theme's destructive colour."""
        self._theme = "light" if theme == "light" else "dark"
        t = self._theme
        bg = color("background", t)
        fg = color("foreground", t)
        border = color("border", t)
        primary = color("primary", t)
        muted = color("mutedForeground", t)
        try:
            destructive = color("destructive", t)
        except KeyError:
            destructive = "#ef4444"
        self.setStyleSheet(f"""
            QWidget#widgetOutline {{ background: {bg}; }}
            QLabel#widgetOutlineSummary {{ color: {muted}; font-size: 12px; padding: 4px 6px; }}
            QLineEdit#widgetOutlineFilter {{
                background: {bg}; color: {fg}; border: none; border-bottom: 1px solid {border};
                padding: 5px 8px; font-size: 12px;
            }}
            QTreeWidget#widgetOutlineTree {{
                background: {bg}; color: {fg}; border: none; font-size: 12px; outline: 0;
            }}
            QTreeWidget#widgetOutlineTree::item:hover {{ background: {_rgba(fg, 0.06)}; }}
            QTreeWidget#widgetOutlineTree::item:selected {{
                background: {_rgba(primary, 0.16)}; color: {fg};
            }}
            QPushButton#widgetOutlineTagChip {{
                background: {_rgba(primary, 0.16)}; color: {fg}; border: none;
                border-radius: 10px; padding: 2px 10px; font-size: 11px;
            }}
        """)
        for item in self._items.values():
            if item.data(0, Qt.UserRole):
                self._apply_issue_style(item)

    # ------------------------------------------------------------ internal

    def _build(self, index):
        for page_index, page in enumerate(index.project.pages):
            page_item = QTreeWidgetItem()
            page_item.setText(0, f"{page.name} ({len(page.widgets)})")
            page_item.setText(1, "")
            page_item.setText(2, "")
            page_item.setData(0, Qt.UserRole, "")
            page_item.setData(0, PAGE_ROLE, page_index)
            self.tree.addTopLevelItem(page_item)
            self._page_items.append(page_item)

        for entry in index.widgets():
            item = QTreeWidgetItem()
            item.setText(0, f"{entry.id}  {entry.type}")
            item.setText(1, widget_tags_text(entry, index))
            issue_rows = index.issues_for(entry.id)
            issue_count = len(issue_rows)
            item.setText(2, str(issue_count) if issue_count else "")
            item.setData(0, Qt.UserRole, entry.id)
            item.setToolTip(0, widget_tooltip(entry, index))
            item.setToolTip(1, widget_tooltip(entry, index))
            item.setToolTip(2, widget_tooltip(entry, index))
            item.setData(1, Qt.UserRole, issue_count)
            if entry.parent_id:
                self._items[entry.parent_id].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            self._items[entry.id] = item

        for page_item in self._page_items:
            page_item.setExpanded(True)
        for item in self._items.values():
            item.setExpanded(True)

    def _apply_filters(self):
        if self._index is None:
            return
        needle = self.filter_edit.text().strip().lower()
        mode = self._mode
        tag = self._shown_tag

        def matches(entry):
            if needle:
                text = f"{entry.id}  {widget_tags_text(entry, self._index)}".lower()
                if needle not in text:
                    return False
            if mode == "bound" and not (entry.tags_read() or entry.tags_written()):
                return False
            if mode == "issues" and not self._index.issues_for(entry.id):
                return False
            if tag and entry.id not in set(self._index.widgets_using(tag)):
                return False
            return True

        matched = set()
        for entry in self._index.widgets():
            if matches(entry):
                matched.add(entry.id)

        for entry in self._index.widgets():
            if self._is_ancestor_or_self(entry, matched):
                self._items[entry.id].setHidden(False)
            else:
                self._items[entry.id].setHidden(True)

        for page_index, page in enumerate(self._index.project.pages):
            visible = any(
                not self._items[entry.id].isHidden()
                for entry in self._index.widgets()
                if entry.page_id == page.id
            )
            self._page_items[page_index].setHidden(not visible)

        self._highlight(self.highlighted_id())

    @staticmethod
    def _is_ancestor_or_self(entry, matched):
        if entry.id in matched:
            return True
        seen = set()
        parent_id = entry.parent_id
        while parent_id and parent_id not in seen:
            if parent_id in matched:
                return True
            seen.add(parent_id)
            parent = entry
            while parent.parent_id != parent_id:
                parent = parent.parent_id
            parent_id = parent.parent_id
        return False

    def _apply_issue_style(self, item: QTreeWidgetItem) -> None:
        issue_count = int(item.data(1, Qt.UserRole) or 0)
        item.setData(2, Qt.ForegroundColorRole, QColor(self._issue_color()) if issue_count else QColor("#000000"))

    def _issue_color(self) -> str:
        try:
            return color("destructive", self._theme)
        except KeyError:
            return "#ef4444"

    def _on_click(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, Qt.UserRole):
            self.pick(item.data(0, Qt.UserRole))

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        widget_id = item.data(0, Qt.UserRole)
        if not widget_id:
            return
        entry = self._index.widget(widget_id) if self._index else None
        self.sourceRequested.emit(widget_id, entry.line if entry else 0)

    def _follow_selection(self, ids: list) -> None:
        self._highlight(ids[0] if len(ids) == 1 else "")

    def _highlight(self, widget_id: str) -> None:
        item = self._items.get(widget_id)
        self.tree.blockSignals(True)
        try:
            self.tree.clearSelection()
            if item is not None:
                self.tree.setCurrentItem(item)
        finally:
            self.tree.blockSignals(False)


__all__ = ["WidgetOutline", "summary_text", "widget_tags_text", "widget_tooltip", "COLUMNS", "PAGE_ROLE",
            "MODES"]

# Imported for the implementation; keeps the skeleton's import list stable.
_ = (QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QToolButton,
      QTreeWidget, QTreeWidgetItem, QVBoxLayout, _rgba, color)