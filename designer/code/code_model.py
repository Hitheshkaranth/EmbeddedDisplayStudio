"""designer/code/code_model.py -- code texts for a design section.

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
import math
import os
import sys
from dataclasses import dataclass

from designer.model import DesignerPage, DesignerProject, DesignerWidget
from designer.model.project import ID_RE

SCOPES = ("widget", "page")
FORMATS = ("qml", "edsui", "c")

# The runtime's widget sources: native/hmi-ui/src/widgets/w_<type>.c, one
# file per kit type, the C that draws the widget on the panel. A frozen
# Studio carries a copy of that directory (packaging/EmbeddedDisplayStudio.spec).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def hmi_ui_sources_dir() -> str:
    """The directory holding w_<type>.c (repository or frozen bundle)."""
    base = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else _REPO_ROOT
    return os.path.join(base, "native", "hmi-ui", "src", "widgets")


def c_source_name(widget_type: str) -> str:
    """The runtime source file for a kit type: ShGauge -> w_shgauge.c."""
    return f"w_{widget_type.lower()}.c"


def widget_c(widget_type: str) -> str:
    """The C source that implements `widget_type` in hmi-ui, or a one-line
    comment saying it was not found."""
    path = os.path.join(hmi_ui_sources_dir(), c_source_name(widget_type))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return f"// {c_source_name(widget_type)}: not found ({hmi_ui_sources_dir()})\n"


def page_c(page: DesignerPage) -> str:
    """The runtime sources of every widget type on `page`, each under a
    banner naming its file, in first-use order."""
    seen = []
    for widget in page.walk():
        if widget.type not in seen:
            seen.append(widget.type)
    if not seen:
        return "// This page has no widgets yet\n"
    parts = []
    for widget_type in seen:
        banner = f"// {'=' * 74}\n// {c_source_name(widget_type)}  ({widget_type})\n// {'=' * 74}\n"
        parts.append(banner + widget_c(widget_type))
    return "\n".join(parts)


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
    lines = generator._widget(widget, 0)
    return "\n".join(lines).lstrip("\n") + "\n"


def page_qml(generator, project: DesignerProject, page: DesignerPage) -> str:
    """The complete generated page file for `page`: `generator._page(project, page)`."""
    return generator._page(project, page)


def widget_edsui(widget: DesignerWidget) -> str:
    """`widget.to_dict()` as pretty JSON (indent 2, keys in model order, no
    key sorting, trailing newline) -- the fragment as it sits in the .edsui."""
    return _pretty(widget.to_dict())


def page_edsui(page: DesignerPage) -> str:
    """`page.to_dict()` as pretty JSON, same rules as widget_edsui."""
    return _pretty(page.to_dict())


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
    data = _load_object(text)
    seen: dict[str, None] = {}   # insertion-ordered: clashes are reported in document order
    _check_widget(data, registry, seen, "")
    if project is not None:
        _check_against_project(seen, project, _ids_under_widget(project, replacing))
    return _build(DesignerWidget.from_dict, data)


def parse_page_edsui(text: str, registry, project: DesignerProject | None = None,
                     replacing: str | None = None) -> DesignerPage:
    """The page described by `text`; same validation as parse_widget_edsui
    applied to every widget of the page, plus "id" and "name" strings on the
    page itself."""
    data = _load_object(text)
    for key in ("id", "name"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise CodeError(f'page "{key}" must be a non-empty string')
    widgets = data.get("widgets", [])
    if not isinstance(widgets, list):
        raise CodeError('page "widgets" must be a list')
    seen: dict[str, None] = {}   # insertion-ordered: clashes are reported in document order
    for index, item in enumerate(widgets):
        _check_widget(item, registry, seen, f"widgets[{index}]")
    if project is not None:
        _check_against_project(seen, project, _ids_in_page(project, replacing))
    return _build(DesignerPage.from_dict, data)


def section_for(generator, registry, project: DesignerProject, page: DesignerPage,
                widget: DesignerWidget | None, scope: str, fmt: str) -> CodeSection:
    """The CodeSection for the given scope/format.

    scope "widget" with widget None gives a section whose text is a one-line
    QML/JSON comment saying nothing is selected (editable False). Unknown
    scope/fmt: ValueError.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    language = {"qml": "qml", "edsui": "json", "c": "c"}[fmt]
    if fmt == "c":
        if scope == "page":
            return CodeSection(scope, fmt, f'Page "{page.name}" -- runtime C (hmi-ui)', page_c(page), False, language)
        if widget is None:
            return CodeSection(scope, fmt, "No selection -- runtime C (hmi-ui)",
                               "// Select a widget on the canvas to see the C that draws it\n", False, language)
        return CodeSection(scope, fmt, f"{widget.id} ({widget.type}) -- runtime C: {c_source_name(widget.type)}",
                           widget_c(widget.type), False, language)
    if scope == "page":
        if fmt == "qml":
            title, text = f'Page "{page.name}" -- generated QML', page_qml(generator, project, page)
        else:
            title, text = f'Page "{page.name}" -- design JSON', page_edsui(page)
        return CodeSection(scope, fmt, title, text, fmt == "edsui", language)
    if widget is None:
        # A comment in both formats: the JSON one is never parsed because
        # the section is not editable.
        if fmt == "qml":
            title, text = "No selection -- generated QML", "// Select a widget on the canvas to see its code\n"
        else:
            title, text = "No selection -- design JSON", "// Select a widget on the canvas to see its design JSON\n"
        return CodeSection(scope, fmt, title, text, False, language)
    if fmt == "qml":
        title, text = f"{widget.id} ({widget.type}) -- generated QML", widget_qml(generator, project, widget)
    else:
        title, text = f"{widget.id} ({widget.type}) -- design JSON", widget_edsui(widget)
    return CodeSection(scope, fmt, title, text, fmt == "edsui", language)


# ------------------------------------------------------------------ helpers

def _pretty(data) -> str:
    # ensure_ascii off to match DesignerProject.save: a label like "Temp °C"
    # reads in the editor the way it sits in the file.
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _load_object(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise CodeError(f"line {error.lineno}: {error.msg}") from None
    if not isinstance(data, dict):
        raise CodeError("the fragment must be a JSON object")
    return data


def _where(path: str) -> str:
    return f"{path}: " if path else ""


def _check_widget(data, registry, seen: dict[str, None], path: str) -> None:
    """Reject anything DesignerWidget.from_dict would silently paper over
    (it defaults a missing type to Rectangle and a missing id to "widget")
    or that the generator would choke on later (an unknown type has no
    definition to emit)."""
    where = _where(path)
    if not isinstance(data, dict):
        raise CodeError(f"{where}a widget must be a JSON object")
    for key in ("type", "id"):
        if key not in data:
            raise CodeError(f'{where}missing "{key}"')
        if not isinstance(data[key], str):
            raise CodeError(f'{where}"{key}" must be a string')
    widget_type, widget_id = data["type"], data["id"]
    if registry.get(widget_type) is None:
        raise CodeError(f'{where}unknown widget type "{widget_type}"')
    if not ID_RE.fullmatch(widget_id):
        raise CodeError(f'{where}id "{widget_id}" is not a QML identifier '
                        "(letters, digits and _, not starting with a digit)")
    if widget_id in seen:
        raise CodeError(f'{where}duplicate id "{widget_id}"')
    seen[widget_id] = None
    geometry = data.get("geometry", {})
    if not isinstance(geometry, dict):
        raise CodeError(f'{where}"geometry" must be an object')
    for key, value in geometry.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise CodeError(f'{where}geometry "{key}" must be a number')
    children = data.get("children", [])
    if not isinstance(children, list):
        raise CodeError(f'{where}"children" must be a list')
    for index, child in enumerate(children):
        _check_widget(child, registry, seen, f"{path}.children[{index}]" if path else f"children[{index}]")


def _ids_under_widget(project: DesignerProject, replacing: str | None) -> set[str]:
    if replacing is None:
        return set()
    for widget in project.all_widgets():
        if widget.id == replacing:
            return {item.id for item in widget.walk()}
    return set()


def _ids_in_page(project: DesignerProject, replacing: str | None) -> set[str]:
    if replacing is None:
        return set()
    for page in project.pages:
        if page.id == replacing:
            return {item.id for item in page.walk()}
    return set()


def _check_against_project(seen: dict[str, None], project: DesignerProject, own: set[str]) -> None:
    taken = {widget.id for widget in project.all_widgets()} - own
    for widget_id in seen:
        if widget_id in taken:
            raise CodeError(f'duplicate id "{widget_id}" (already used elsewhere in the project)')


def _build(factory, data):
    # from_dict validates bindings and actions itself; its message is the
    # user's message.
    try:
        return factory(data)
    except (TypeError, ValueError) as error:
        raise CodeError(str(error)) from None
