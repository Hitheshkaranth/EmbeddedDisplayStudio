"""designer/code/code_model.py -- code texts for a design section.

FROZEN CONTRACT (Code window swarm, 2026-09-22). Owner: W1. Every signature
and docstring below is the contract the other workers build against; W1
fills the bodies and may add private helpers, nothing else.

Two scopes, two formats:

    scope  "widget"  the selected widget (with its children)
           "page"    the whole screen (the current page)
    fmt    "qml"     what designer/generators/qml_generator.py emits for it
           "edsui"   the JSON fragment the .edsui file stores for it

QML is read-only (it is generated; the model is the source). The .edsui
fragment is editable: parse_*_edsui turns the text back into a model
object that the workspace swaps in as one undoable step.

No Qt in this module: it is pure Python over the designer model so it can be
unit-tested without a display.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from designer.model import DesignerPage, DesignerProject, DesignerWidget

SCOPES = ("widget", "page")
FORMATS = ("qml", "edsui")


class CodeError(ValueError):
    """The text cannot be turned into a model object. The message is shown
    to the user verbatim, so it names the problem and, when known, the
    line: 'line 12: expecting a comma' / 'unknown widget type "ShFoo"' /
    'duplicate id "gauge1"'."""


@dataclass(frozen=True)
class CodeSection:
    """One code view.

    Attributes:
        scope: "widget" or "page".
        fmt: "qml" or "edsui".
        title: what the window shows above the editor, e.g.
            'gauge1 (ShGauge) -- generated QML' or 'Page "Main" -- design JSON'.
        text: the code.
        editable: True only for fmt == "edsui" (the design can be applied back).
        language: "qml" or "json" -- what the editor highlights as.
    """
    scope: str
    fmt: str
    title: str
    text: str
    editable: bool
    language: str


def widget_qml(generator, project: DesignerProject, widget: DesignerWidget) -> str:
    """The QML the generator emits for `widget` (and its children), as a
    standalone snippet.

    Exactly the lines `generator._widget(widget, 0)` produces (leading blank
    line dropped, trailing newline added), so what the window shows is what
    ends up in the page file, byte for byte apart from indentation depth.
    Bindings and actions stay in (they are part of the widget's code).
    """
    raise NotImplementedError


def page_qml(generator, project: DesignerProject, page: DesignerPage) -> str:
    """The complete generated page file for `page`: `generator._page(project, page)`."""
    raise NotImplementedError


def widget_edsui(widget: DesignerWidget) -> str:
    """`widget.to_dict()` as pretty JSON (indent 2, keys in model order, no
    key sorting, trailing newline) -- the fragment as it sits in the .edsui."""
    raise NotImplementedError


def page_edsui(page: DesignerPage) -> str:
    """`page.to_dict()` as pretty JSON, same rules as widget_edsui."""
    raise NotImplementedError


def parse_widget_edsui(text: str, registry, project: DesignerProject | None = None,
                       replacing: str | None = None) -> DesignerWidget:
    """The widget described by `text` (a JSON object as widget_edsui writes it).

    Args:
        text: the JSON.
        registry: the widget registry (designer.palette.default_registry());
            every "type" in the tree must be a registered type.
        project: when given, ids are checked for uniqueness against the
            project's other widgets.
        replacing: the id of the widget this one replaces (its own ids do
            not count as clashes).

    Raises:
        CodeError: invalid JSON (with the line), not an object, missing or
            non-string "type"/"id", unknown type, an id that is not a QML
            identifier, a duplicate id inside the fragment or against the
            project, geometry values that are not numbers.
    """
    raise NotImplementedError


def parse_page_edsui(text: str, registry, project: DesignerProject | None = None,
                     replacing: str | None = None) -> DesignerPage:
    """The page described by `text`; same validation as parse_widget_edsui
    applied to every widget of the page, plus "id" and "name" strings on the
    page itself."""
    raise NotImplementedError


def section_for(generator, registry, project: DesignerProject, page: DesignerPage,
                widget: DesignerWidget | None, scope: str, fmt: str) -> CodeSection:
    """The CodeSection for the given scope/format.

    scope "widget" with widget None gives a section whose text is a one-line
    QML/JSON comment saying nothing is selected (editable False). Unknown
    scope/fmt: ValueError.
    """
    raise NotImplementedError
