"""designer/ide/agent_context.py -- what the coding agent is told about the design.

Without this the agent sees files and nothing else: it has to grep
project.edsui to learn which widgets exist and guesses tag names. The Code
section passes design_brief() as context["design"] with each message
(AgentPanel's "Include design" option), and build_prompt
(agent_backend.py) appends it after the editor context, fenced as below.

design_brief(index, selected_id, max_chars) -> str, sections in this order,
each starting with its "## " heading, separated by one blank line:

    ## Design
    Project "<project.name or '(unnamed)'>", <summary_text-like counts>:
    "<pages> pages, <widgets> widgets, <tags> tags" (plain plural "s" even
    for 1 is fine here -- this is for a model, not a person).
    One line per page: "- <page id> \"<page name>\": <n> widgets (<type> x<count>, ...)"
      types in first-seen order within the page.

    ## Selected widget            (only when selected_id names a widget)
    "<id> (<type>) on page <page id>, parent <parent id or 'none'>"
    "Bindable properties: a, b" / "Action signals: x" from the registry
      definition (index.definition(type)); "none" when empty / no registry.
    Then the widget's JSON (DesignerWidget.to_dict(), indent 2) in a
    ```json fence, children included.

    ## Tags
    One line per index.tags() entry:
    "- <tag> [<access or '-'>] read by <ids or 'nothing'>; written by <ids or 'nothing'>"
    plus " (not declared)" when not entry.declared and " (writable)" when
    entry.writable. No tags -> "- none".

    ## Issues                     (only when index.issues() is non-empty)
    "- <widget id>.<property>: <detail>" per issue row.

    ## Rules
    RULES verbatim.

max_chars: the brief is cut to at most max_chars characters. When cutting,
drop whole lines from the end of the Tags section first, replacing them
with "- ... <n> more tags"; if still too long drop the per-page lines
(replaced by "- ... <n> more pages"); the Rules section is never cut and the
Selected widget JSON is never cut in the middle of a line. If it still does
not fit, return it over-length rather than lose Rules.

quick_actions(index, selected_id) -> list[QuickAction], shown as buttons /
a menu in the agent panel. Exactly, in this order:
  with a selected widget W (type T):
    "Explain <W>"          -- "Explain what widget <W> (<T>) shows and how it is wired: its bindings, actions and the tags involved."
    "Bind <W>..."          -- only when T has bindable properties:
                              "Bind widget <W>'s <first bindable property> to a suitable tag in project.edsui. Use an existing tag of this design when one fits, otherwise a new CONTRACT 2.5 tag name, and say which you chose."
    "Add alarm to <W>"     -- only when W has at least one binding:
                              "Add warning and critical thresholds to widget <W>'s <first bound property> binding in project.edsui, with sensible values for its range."
  always:
    "Fix binding issues"   -- only when index.issues() is non-empty:
                              "Fix the binding issues listed in the design context by editing project.edsui."
    "Write backend for tags" --
                              "Implement the read functions in backend/backend.py so each tag returns a realistic value for this design; keep the CONTRACT 2 wire format."
    "Summarise design"     -- "Summarise this design: pages, what each page is for, and the tags it depends on."
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from designer.ide.design_index import DesignIndex

RULES = (
    "- project.edsui is JSON the panel runs directly: keep it valid, keep every widget id unique "
    "across the whole design, never edit generated/.\n"
    "- Tag names follow CONTRACT 2.5: ^[a-z][a-z0-9]*(\\.[a-z0-9_]+)+$ -- lowercase, dotted. "
    "Prefixes: ai. analog in (read-only), di. digital in (read-only), do. digital out (writable), "
    "mb. Modbus, sys. daemon health (read-only).\n"
    "- A binding is {\"tag\", \"format\", \"multiplier\", \"offset\", \"unit\", \"warning\", \"critical\"}; "
    "thresholds are strings like \">4000\" or \"<10\".\n"
    "- An action is {\"kind\": \"write\"|\"pulse\"|\"navigate\", \"tag\", \"value\", \"ms\", \"page\"}; only "
    "writable tags may be written or pulsed."
)

DEFAULT_MAX_CHARS = 6000


@dataclass(frozen=True)
class QuickAction:
    label: str
    prompt: str


def design_brief(index: DesignIndex | None, selected_id: str = "", max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """See the module docstring. index None -> '' (no design open)."""
    if index is None:
        return ""
    project = index.project
    summary = index.summary()
    head = ["## Design",
            f'Project "{getattr(project, "name", "") or "(unnamed)"}", '
            f"{summary['pages']} pages, {summary['widgets']} widgets, {summary['tags']} tags"]
    page_lines = [_page_line(index, page_index, page)
                  for page_index, page in enumerate(getattr(project, "pages", None) or [])]

    selected: list = []
    entry = index.widget(selected_id) if selected_id else None
    if entry is not None:
        definition = index.definition(entry.type)
        bindable = tuple(getattr(definition, "bindable_properties", ()) or ())
        signals = tuple(getattr(definition, "action_signals", ()) or ())
        selected = ["## Selected widget",
                    f"{entry.id} ({entry.type}) on page {entry.page_id}, parent {entry.parent_id or 'none'}",
                    "Bindable properties: " + (", ".join(bindable) or "none"),
                    "Action signals: " + (", ".join(signals) or "none")]
        model = find_widget(project, entry.id)
        if model is not None:
            selected += ["```json", *json.dumps(model.to_dict(), indent=2).splitlines(), "```"]

    tag_lines = [_tag_line(tag) for tag in index.tags()]
    issue_lines = [f"- {row.widget_id}.{row.property}: {row.detail}" for row in index.issues()]
    rules = ["## Rules", RULES]

    def render(pages_kept: int, tags_kept: int) -> str:
        pages = page_lines[:pages_kept]
        if pages_kept < len(page_lines):
            pages.append(f"- ... {len(page_lines) - pages_kept} more pages")
        if not tag_lines:
            tags = ["- none"]
        else:
            tags = tag_lines[:tags_kept]
            if tags_kept < len(tag_lines):
                tags.append(f"- ... {len(tag_lines) - tags_kept} more tags")
        sections = [head + pages]
        if selected:
            sections.append(selected)
        sections.append(["## Tags"] + tags)
        if issue_lines:
            sections.append(["## Issues"] + issue_lines)
        sections.append(rules)
        return "\n\n".join("\n".join(section) for section in sections)

    pages_kept, tags_kept = len(page_lines), len(tag_lines)
    text = render(pages_kept, tags_kept)
    # Each step drops exactly one line, so this ends after at most
    # len(tag_lines) + len(page_lines) renders; the Rules and the selected
    # widget are never touched, so an unfittable brief comes back over-long.
    while len(text) > max_chars and (tags_kept or pages_kept):
        if tags_kept:
            tags_kept -= 1
        else:
            pages_kept -= 1
        text = render(pages_kept, tags_kept)
    return text


def _page_line(index: DesignIndex, page_index: int, page) -> str:
    counts: dict = {}
    for entry in index.widgets(page_index):
        counts[entry.type] = counts.get(entry.type, 0) + 1
    types = ", ".join(f"{name} x{count}" for name, count in counts.items())
    return f'- {page.id} "{page.name}": {sum(counts.values())} widgets ({types})'


def _tag_line(entry) -> str:
    # A widget reading one tag through two properties is still one reader.
    readers = ", ".join(dict.fromkeys(wid for wid, _prop in entry.readers)) or "nothing"
    writers = ", ".join(dict.fromkeys(wid for wid, _sig in entry.writers)) or "nothing"
    line = f"- {entry.tag} [{entry.access or '-'}] read by {readers}; written by {writers}"
    if not entry.declared:
        line += " (not declared)"
    if entry.writable:
        line += " (writable)"
    return line


def quick_actions(index: DesignIndex | None, selected_id: str = "") -> list:
    """See the module docstring. index None -> [] ."""
    if index is None:
        return []
    actions = []
    entry = index.widget(selected_id) if selected_id else None
    if entry is not None:
        wid, wtype = entry.id, entry.type
        actions.append(QuickAction(
            f"Explain {wid}",
            f"Explain what widget {wid} ({wtype}) shows and how it is wired: its bindings, actions "
            "and the tags involved."))
        bindable = tuple(getattr(index.definition(wtype), "bindable_properties", ()) or ())
        if bindable:
            actions.append(QuickAction(
                f"Bind {wid}...",
                f"Bind widget {wid}'s {bindable[0]} to a suitable tag in project.edsui. Use an existing "
                "tag of this design when one fits, otherwise a new CONTRACT 2.5 tag name, and say which "
                "you chose."))
        # An empty binding or the alarm table's wildcard has nothing to put
        # thresholds on.
        bound = [prop for prop, tag in entry.bindings if tag and tag != "*"]
        if bound:
            actions.append(QuickAction(
                f"Add alarm to {wid}",
                f"Add warning and critical thresholds to widget {wid}'s {bound[0]} binding in "
                "project.edsui, with sensible values for its range."))
    if index.issues():
        actions.append(QuickAction(
            "Fix binding issues",
            "Fix the binding issues listed in the design context by editing project.edsui."))
    actions.append(QuickAction(
        "Write backend for tags",
        "Implement the read functions in backend/backend.py so each tag returns a realistic value for "
        "this design; keep the CONTRACT 2 wire format."))
    actions.append(QuickAction(
        "Summarise design",
        "Summarise this design: pages, what each page is for, and the tags it depends on."))
    return actions


def find_widget(project, widget_id: str):
    """The DesignerWidget with that id anywhere in project (nested too), or None."""
    if project is None or not widget_id:
        return None
    for page in getattr(project, "pages", None) or []:
        for widget in page.walk():
            if widget.id == widget_id:
                return widget
    return None


__all__ = ["design_brief", "quick_actions", "find_widget", "QuickAction", "RULES", "DEFAULT_MAX_CHARS"]

_ = json
