"""designer/ide/widget_picker.py -- pick a widget of the current page to see its code.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W1. See
docs/CODE_SECTION.md.

A list of the current page's widgets (nested widgets indented under their
container, in page order), each row a small preview thumbnail, the widget id
and its type. Clicking a row selects that widget in the Designer
(workspace.select_widget); the Code section's Design tab follows the
Designer's selection, so the row's code and preview appear there. The row of
the widget selected in the Designer is highlighted, so selecting on the
canvas moves the highlight here too.

Thumbnails come from the workspace's renderer, the same one the canvas and
the Design tab use: workspace.scene.qml_previews.image_for(widget, w, h,
theme) returns a QImage, or None with a render scheduled, in which case its
`ready(key)` signal fires later and the picker fills that row in (look the
thumbnails up again on ready; do not rebuild the list). The renderer may be
None, or return None forever when previews are off: the row then shows the
type's initial letter on a neutral tile. Thumbnails are fitted into
THUMB_SIZE, aspect kept, rendered at the widget's own geometry size.

The list is rebuilt on workspace.designChanged and workspace.pageChanged,
keeping the scroll position; selection highlight follows
workspace.scene.selectionIdsChanged. A filter field on top narrows rows by id
or type (case-insensitive substring).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QWidget

THUMB_SIZE = QSize(56, 40)


class WidgetPicker(QWidget):
    """Signals:
        widgetPicked(str): the id of the widget the user clicked (after
        workspace.select_widget was called with it).

    Attributes tests rely on: `list` (a QListWidget; each item's
    Qt.UserRole data is the widget id), `filter_edit` (QLineEdit).
    """

    widgetPicked = Signal(str)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    def rebuild(self) -> None:
        """Re-reads the current page's widgets."""
        raise NotImplementedError

    def widget_ids(self) -> list[str]:
        """The ids of the rows currently shown (filter applied), top to bottom."""
        raise NotImplementedError

    def highlighted_id(self) -> str:
        """The id of the highlighted row, or ''."""
        raise NotImplementedError

    def pick(self, widget_id: str) -> None:
        """What clicking the row does: workspace.select_widget(widget_id),
        highlight it, emit widgetPicked."""
        raise NotImplementedError

    def thumbnail(self, widget_id: str):
        """The QImage shown for that row, or None while it has none."""
        raise NotImplementedError

    def set_filter(self, text: str) -> None:
        """Same as typing into filter_edit."""
        raise NotImplementedError

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        raise NotImplementedError
