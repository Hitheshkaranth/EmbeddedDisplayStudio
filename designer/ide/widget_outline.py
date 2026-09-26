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
    raise NotImplementedError  # W1


def widget_tags_text(entry, index: DesignIndex) -> str:
    """See the module docstring, Tags column."""
    raise NotImplementedError  # W1


def widget_tooltip(entry, index: DesignIndex) -> str:
    """See the module docstring, tooltips."""
    raise NotImplementedError  # W1


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
        raise NotImplementedError  # W1

    def set_index(self, index: DesignIndex | None) -> None:
        """Rebuilds the tree (None -> empty), keeping filter, mode, tag and
        the vertical scroll position; re-highlights the Designer's selection."""
        raise NotImplementedError  # W1

    def index(self) -> DesignIndex | None:
        raise NotImplementedError  # W1

    def widget_ids(self) -> list:
        """Ids of the widget rows currently shown, tree order (pre-order)."""
        raise NotImplementedError  # W1

    def item_for(self, widget_id: str):
        """The QTreeWidgetItem of that widget, or None."""
        raise NotImplementedError  # W1

    def highlighted_id(self) -> str:
        """Id of the current widget row, or ''."""
        raise NotImplementedError  # W1

    def set_filter(self, text: str) -> None:
        raise NotImplementedError  # W1

    def set_mode(self, mode: str) -> None:
        """'all' | 'bound' | 'issues'; anything else -> ValueError."""
        raise NotImplementedError  # W1

    def mode(self) -> str:
        raise NotImplementedError  # W1

    def show_tag(self, tag: str) -> None:
        raise NotImplementedError  # W1

    def shown_tag(self) -> str:
        raise NotImplementedError  # W1

    def pick(self, widget_id: str) -> None:
        raise NotImplementedError  # W1

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'. Issue counts use the theme's destructive colour."""
        raise NotImplementedError  # W1


__all__ = ["WidgetOutline", "summary_text", "widget_tags_text", "widget_tooltip", "COLUMNS", "PAGE_ROLE",
           "MODES"]

# Imported for the implementation; keeps the skeleton's import list stable.
_ = (QAbstractItemView, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QToolButton,
     QTreeWidget, QTreeWidgetItem, QVBoxLayout, _rgba, color)
