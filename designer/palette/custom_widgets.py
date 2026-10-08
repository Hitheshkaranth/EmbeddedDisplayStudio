"""designer/palette/custom_widgets.py -- widgets a person makes in the Studio.

A custom widget is a group of kit widgets saved under a name: an icon, a
title and a value laid out once, reused on every page. It needs no code and
no new runtime: on the canvas it is inserted as an Item container holding
fresh copies of the saved widgets (new ids, same look, same tag bindings), so
it previews, deploys and runs on the panel like any other design.

The library is a folder of `<name>.edswidget` JSON files beside the Studio's
projects (Documents/EmbeddedDisplay Studio/widgets), shared by every project.
`EDS_CUSTOM_WIDGETS_DIR` overrides the folder (tests, portable installs).

    {"schema": 1, "name": "Door Status", "width": 240, "height": 90,
     "widgets": [<DesignerWidget.to_dict()>, ...]}   # geometry relative to the group
"""
from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QStandardPaths, Signal

PREFIX = "custom:"
SUFFIX = ".edswidget"
CATEGORY = "Custom"


def is_custom(widget_type: str) -> bool:
    return str(widget_type or "").startswith(PREFIX)


def slug_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-") or "widget"


@dataclass
class CustomWidget:
    name: str
    slug: str
    width: int
    height: int
    widgets: list = field(default_factory=list)

    @property
    def type(self) -> str:
        return PREFIX + self.slug


def default_folder() -> str:
    override = os.environ.get("EDS_CUSTOM_WIDGETS_DIR")
    if override:
        return override
    documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
    return os.path.join(documents, "EmbeddedDisplay Studio", "widgets")


class CustomWidgetLibrary(QObject):
    """The saved custom widgets. `changed` fires after a save or a delete."""

    changed = Signal()

    def __init__(self, folder: str | None = None, parent=None):
        super().__init__(parent)
        self.folder = folder or default_folder()

    # -- reading ------------------------------------------------------------
    def items(self) -> list:
        found = []
        if os.path.isdir(self.folder):
            for name in sorted(os.listdir(self.folder)):
                if name.endswith(SUFFIX):
                    item = self._read(os.path.join(self.folder, name))
                    if item is not None:
                        found.append(item)
        return sorted(found, key=lambda item: item.name.lower())

    def get(self, widget_type_or_slug: str):
        slug = str(widget_type_or_slug or "")
        slug = slug[len(PREFIX):] if slug.startswith(PREFIX) else slug
        return self._read(os.path.join(self.folder, slug + SUFFIX))

    @staticmethod
    def _read(path):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            widgets = [w for w in data.get("widgets") or [] if isinstance(w, dict)]
            if not widgets:
                return None
            slug = os.path.basename(path)[:-len(SUFFIX)]
            return CustomWidget(str(data.get("name") or slug), slug,
                                int(data.get("width") or 0), int(data.get("height") or 0), widgets)
        except (OSError, ValueError, TypeError):
            return None

    # -- writing ------------------------------------------------------------
    def save(self, name: str, models) -> CustomWidget:
        """Save these widgets (DesignerWidget models, as selected on the canvas)
        as one custom widget, positioned relative to their bounding box."""
        models = list(models)
        if not models:
            raise ValueError("select the widgets to save first")
        left = min(float(m.geometry.get("x", 0)) for m in models)
        top = min(float(m.geometry.get("y", 0)) for m in models)
        right = max(float(m.geometry.get("x", 0)) + float(m.geometry.get("width", 0)) for m in models)
        bottom = max(float(m.geometry.get("y", 0)) + float(m.geometry.get("height", 0)) for m in models)
        widgets = []
        for model in models:
            data = copy.deepcopy(model.to_dict())
            data["geometry"]["x"] = round(float(model.geometry.get("x", 0)) - left)
            data["geometry"]["y"] = round(float(model.geometry.get("y", 0)) - top)
            widgets.append(data)
        item = CustomWidget(str(name).strip() or "Custom widget", slug_of(name),
                            max(1, round(right - left)), max(1, round(bottom - top)), widgets)
        os.makedirs(self.folder, exist_ok=True)
        path = os.path.join(self.folder, item.slug + SUFFIX)
        partial = path + ".partial"
        with open(partial, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "name": item.name, "width": item.width, "height": item.height,
                       "widgets": item.widgets}, handle, indent=2)
        os.replace(partial, path)
        self.changed.emit()
        return item

    def delete(self, widget_type_or_slug: str) -> bool:
        item = self.get(widget_type_or_slug)
        if item is None:
            return False
        os.remove(os.path.join(self.folder, item.slug + SUFFIX))
        self.changed.emit()
        return True

    # -- using ----------------------------------------------------------------
    def instantiate(self, widget_type_or_slug: str, project, x: float = 20, y: float = 20):
        """A fresh copy for `project`: an Item container at (x, y) holding the
        saved widgets with new, unique ids. None when there is no such widget."""
        from designer.model import DesignerWidget
        item = self.get(widget_type_or_slug)
        if item is None:
            return None
        group = DesignerWidget("Item", project.unique_id(item.slug.replace("-", "_") or "custom"),
                               {"x": max(0, round(x)), "y": max(0, round(y)),
                                "width": item.width, "height": item.height},
                               {"opacity": 1.0, "visible": True})
        taken = set()
        for data in item.widgets:
            child = DesignerWidget.from_dict(copy.deepcopy(data))
            for part in child.walk():
                wanted = part.id
                part.id = project.unique_id(wanted)
                while part.id in taken:
                    part.id = project.unique_id(part.id + "_")
                taken.add(part.id)
            group.children.append(child)
        return group
