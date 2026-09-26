"""designer/ide/design_index.py -- one read-only index of the whole design.

The Code section's outline, backend pane, agent context and backend scaffold
all ask the same questions of a DesignerProject: which widgets are there (on
every page, not just the current one), what does each read and write, which
tags does the design use and who uses them, where in project.edsui is a
widget, and what is wrong with its bindings. This module answers them once,
with no Qt, so each consumer is a thin view over the same facts.

    index = DesignIndex.build(project, registry, declared_tags, edsui_text)
    index.widgets()          # every widget, page order, depth-first
    index.tags()             # every tag, sorted, with readers and writers
    index.issues_for(id)     # binding diagnostics of one widget

An index is a snapshot: rebuild it when the design changes (it is cheap --
one walk of the model).

See docs/CODE_SECTION.md, "Widget visibility and backend".
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from designer.model.binding_diagnostics import DiagnosticRow, audit_bindings

# CONTRACT 2.5: what a prefix says about who may write the tag. "mb." is
# writable only when hwd.json says so, which the Studio does not know; a
# design that writes one is trusted to be right.
WRITABLE_PREFIXES = ("do.", "mb.", "uart.tx")
READ_ONLY_PREFIXES = ("ai.", "di.", "sys.")

# The alarm table's "every alarm" wildcard is a binding, not a tag.
WILDCARD_TAG = "*"


@dataclass(frozen=True)
class WidgetEntry:
    """One widget of the design.

    id, type      -- as in the model.
    page_index    -- index into project.pages.
    page_id, page_name
    parent_id     -- id of the containing widget, '' at page level.
    depth         -- 0 at page level, +1 per container.
    bindings      -- ((property, tag), ...) in the model's order.
    actions       -- ((signal, kind, target), ...): target is the tag of a
                     write/pulse, the page id of a navigate.
    geometry      -- (x, y, width, height).
    line          -- 1-based line of the widget's `"id": "<id>"` in the
                     project.edsui text the index was built with, 0 when no
                     text was given or the id was not found.
    """
    id: str
    type: str
    page_index: int
    page_id: str
    page_name: str
    parent_id: str
    depth: int
    bindings: tuple = ()
    actions: tuple = ()
    geometry: tuple = (0.0, 0.0, 0.0, 0.0)
    line: int = 0

    def tags_read(self) -> tuple:
        """The distinct tags this widget's bindings read, in order."""
        return tuple(dict.fromkeys(tag for _prop, tag in self.bindings if tag and tag != WILDCARD_TAG))

    def tags_written(self) -> tuple:
        """The distinct tags this widget's write/pulse actions address."""
        return tuple(dict.fromkeys(target for _sig, kind, target in self.actions
                                   if kind in ("write", "pulse") and target))


@dataclass(frozen=True)
class TagEntry:
    """One tag the design uses or the bundle declares.

    readers   -- ((widget_id, property), ...) bindings that read it.
    writers   -- ((widget_id, signal), ...) actions that write/pulse it.
    declared  -- listed by the bundle's manifest (tags_required) or the
                 catalogue the index was given; when the index was given no
                 declared tags at all, every tag the design uses counts as
                 declared (there is nothing to check it against).
    writable  -- the tag's prefix allows writes (CONTRACT 2.5).
    """
    tag: str
    readers: tuple = ()
    writers: tuple = ()
    declared: bool = False
    writable: bool = False

    @property
    def access(self) -> str:
        """'R', 'W', 'RW', or '' for a declared tag nothing uses."""
        return ("R" if self.readers else "") + ("W" if self.writers else "")


def is_writable_tag(tag: str) -> bool:
    return tag.startswith(WRITABLE_PREFIXES)


def edsui_lines(text: str) -> dict:
    """{widget id: 1-based line} for every `"id": "<id>"` in an .edsui text.

    The first occurrence wins; page ids share the key, so the index only asks
    for ids it knows are widgets and pages come first in the file only when
    a page and a widget share an id, which ensure_unique_ids forbids."""
    lines: dict = {}
    pattern = re.compile(r'"id"\s*:\s*("(?:[^"\\]|\\.)*")')
    for number, line in enumerate(text.splitlines(), 1):
        for match in pattern.finditer(line):
            try:
                value = json.loads(match.group(1))
            except ValueError:
                continue
            lines.setdefault(value, number)
    return lines


@dataclass
class DesignIndex:
    project: object = None
    _widgets: list = field(default_factory=list)
    _by_id: dict = field(default_factory=dict)
    _tags: list = field(default_factory=list)
    _tag_by_name: dict = field(default_factory=dict)
    _issues: list = field(default_factory=list)
    _registry: object = None

    @classmethod
    def build(cls, project, registry=None, declared_tags=(), edsui_text: str | None = None) -> "DesignIndex":
        """Indexes `project` (a DesignerProject; None -> an empty index).

        registry      -- designer.palette.widget_registry registry, used only
                         by callers through `definition()`.
        declared_tags -- tags the bundle declares (manifest tags_required).
        edsui_text    -- the project.edsui text, for WidgetEntry.line.
        """
        index = cls(project=project, _registry=registry)
        if project is None:
            return index
        lines = edsui_lines(edsui_text) if edsui_text else {}
        declared = {tag for tag in (declared_tags or ()) if tag and tag != WILDCARD_TAG}
        readers: dict = {}
        writers: dict = {}

        def walk(widgets, page_index, page, parent_id, depth):
            for widget in widgets:
                bindings = tuple((prop, binding.tag) for prop, binding in widget.bindings.items())
                actions = tuple((signal, action.kind, action.page if action.kind == "navigate" else action.tag)
                                for signal, action in widget.actions.items())
                g = widget.geometry
                entry = WidgetEntry(
                    id=widget.id, type=widget.type, page_index=page_index, page_id=page.id,
                    page_name=page.name, parent_id=parent_id, depth=depth, bindings=bindings,
                    actions=actions,
                    geometry=(float(g.get("x", 0)), float(g.get("y", 0)),
                              float(g.get("width", 0)), float(g.get("height", 0))),
                    line=lines.get(widget.id, 0))
                index._widgets.append(entry)
                index._by_id.setdefault(widget.id, entry)
                for prop, tag in bindings:
                    if tag and tag != WILDCARD_TAG:
                        readers.setdefault(tag, []).append((widget.id, prop))
                for signal, kind, target in actions:
                    if kind in ("write", "pulse") and target:
                        writers.setdefault(target, []).append((widget.id, signal))
                walk(widget.children, page_index, page, widget.id, depth + 1)

        for page_index, page in enumerate(project.pages):
            walk(page.widgets, page_index, page, "", 0)

        known = declared or set(readers) | set(writers)
        for tag in sorted(set(readers) | set(writers) | declared):
            entry = TagEntry(tag=tag, readers=tuple(readers.get(tag, ())), writers=tuple(writers.get(tag, ())),
                             declared=tag in known, writable=is_writable_tag(tag))
            index._tags.append(entry)
            index._tag_by_name[tag] = entry

        all_widgets = [w for page in project.pages for w in page.walk()]
        # Without a manifest every used tag counts as declared: "not declared"
        # would then flag the whole design and say nothing.
        known = (declared if declared else set(readers) | set(writers)) | {WILDCARD_TAG}
        index._issues = audit_bindings(all_widgets, known)
        return index

    # ------------------------------------------------------------ widgets

    def widgets(self, page_index: int | None = None) -> list:
        """WidgetEntry list in page order, depth-first; one page when given."""
        if page_index is None:
            return list(self._widgets)
        return [w for w in self._widgets if w.page_index == page_index]

    def widget(self, widget_id: str):
        """The WidgetEntry with that id, or None."""
        return self._by_id.get(widget_id)

    def type_counts(self) -> dict:
        """{type: count} over the whole design, most used first, ties by name."""
        counts = Counter(w.type for w in self._widgets)
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    def definition(self, widget_type: str):
        """The registry's WidgetDefinition for a type, or None."""
        if self._registry is None:
            return None
        try:
            return self._registry.get(widget_type)
        except (KeyError, AttributeError):
            return None

    # ------------------------------------------------------------ tags

    def tags(self) -> list:
        """TagEntry list sorted by tag."""
        return list(self._tags)

    def tag(self, name: str):
        """The TagEntry for that tag, or None."""
        return self._tag_by_name.get(name)

    def widgets_using(self, tag: str) -> list:
        """Ids of the widgets that read or write `tag`, design order, no repeats."""
        entry = self._tag_by_name.get(tag)
        if entry is None:
            return []
        ids = {wid for wid, _ in entry.readers} | {wid for wid, _ in entry.writers}
        return [w.id for w in self._widgets if w.id in ids and w.id]

    # ------------------------------------------------------------ issues

    def issues(self) -> list:
        """audit_bindings rows whose status is 'error' or 'warning'."""
        return [row for row in self._issues if row.status in ("error", "warning")]

    def diagnostics(self) -> list:
        """Every audit_bindings row, 'ready' and 'info' included."""
        return list(self._issues)

    def issues_for(self, widget_id: str) -> list:
        """The error/warning rows of one widget."""
        return [row for row in self.issues() if row.widget_id == widget_id]

    def summary(self) -> dict:
        """{"pages", "widgets", "types", "tags", "bound", "issues"}: counts
        for a one-line header. bound = widgets with at least one binding or
        write/pulse action."""
        return {
            "pages": len(getattr(self.project, "pages", []) or []),
            "widgets": len(self._widgets),
            "types": len({w.type for w in self._widgets}),
            "tags": len(self._tags),
            "bound": sum(1 for w in self._widgets if w.tags_read() or w.tags_written()),
            "issues": len(self.issues()),
        }


__all__ = ["DesignIndex", "WidgetEntry", "TagEntry", "DiagnosticRow", "edsui_lines", "is_writable_tag",
           "WRITABLE_PREFIXES", "READ_ONLY_PREFIXES", "WILDCARD_TAG"]
