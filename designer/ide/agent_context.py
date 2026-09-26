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
    lines = ["## Design",
             f'Project "{project.name or "(unnamed)"}", '
             f"{summary['pages']} pages, {summary['widgets']} widgets, {summary['tags']} tags", "", ""]

    for page_index, page in enumerate(project.pages):
        counts = {}
        for entry in index.widgets(page_index):
            counts[entry.type] = counts.get(entry.type, 0) + 1
        types = ", ".join(f"{t} x{counts[t]}" for t in counts)
        lines.append(f'- {page.id} "{page.name}": {sum(counts.values())} widgets ({types})')
    lines.append("")

    selected = index.widget(selected_id) if selected_id else None
    if selected is not None:
        lines += ["", "## Selected widget",
                  f"{selected.id} ({selected.type}) on page {selected.page_id}, "
                  f"parent {selected.parent_id or 'none'}"]
        definition = index.definition(selected.type)
        bindable = tuple(getattr(definition, "bindable_properties", ()) or ())
        lines.append("Bindable properties: " + (", ".join(bindable) if bindable else "none"))
        signals = tuple(getattr(definition, "action_signals", ()) or ())
        lines.append("Action signals: " + (", ".join(signals) if signals else "none"))
        lines.append("```json")
        lines.append(json.dumps(find_widget(project, selected_id).to_dict(), indent=2))
        lines.append("```")

    lines += ["", "## Tags", ""]
    tag_lines = []
    for entry in index.tags():
        readers = ", ".join(wid for wid, _ in entry.readers) or "nothing"
        writers = ", ".join(wid for wid, _ in entry.writers) or "nothing"
        line = f'- {entry.tag} [{entry.access or "-"}] read by {readers}; written by {writers}'
        if not entry.declared:
            line += " (not declared)"
        if entry.writable:
            line += " (writable)"
        tag_lines.append(line)
    lines += tag_lines or ["- none"]

    issues = index.issues()
    if issues:
        lines += ["", "## Issues", ""]
        for issue in issues:
            lines.append(f"- {issue.widget_id}.{issue.property}: {issue.detail}")

    lines += ["", "## Rules", "", RULES]
    text = "\n".join(lines)

    if max_chars and len(text) > max_chars:
        return _cut(text, max_chars)
    return text


def _cut(text: str, max_chars: int) -> str:
    """Drop whole lines from the end of the Tags section first, then the
    per-page lines, until it fits; Rules is never cut and the Selected widget
    JSON is never cut mid-line."""
    text, rules = text.split("## Rules", 1)
    body, sep, tags = text.partition("\n\n## Tags")
    body_lines = body.rstrip("\n").splitlines()
    design_head = body_lines[:2]
    page_lines = body_lines[2:]
    tag_lines = tags[len("## Tags"):].splitlines()

    def rendered(design, pages, tags):
        return "\n".join(design + pages + ["## Tags"] + tags + ["## Rules"])

    while len(rendered(design_head, page_lines, tag_lines)) > max_chars:
        if tag_lines:
            n = len(tag_lines)
            tag_lines = tag_lines[:-1] + [f"- ... {n - 1} more tags"]
        elif len(page_lines) > 1:
            n = len(page_lines)
            page_lines = page_lines[:-1] + [f"- ... {n - 1} more pages"]
        else:
            break

    return rendered(design_head, page_lines, tag_lines)


def quick_actions(index: DesignIndex | None, selected_id: str = "") -> list:
    """See the module docstring. index None -> [] ."""
    if index is None:
        return []
    actions = []
    selected = index.widget(selected_id) if selected_id else None
    if selected is not None:
        definition = index.definition(selected.type) or None
        bindable = tuple(p for p in (definition.bindable_properties if definition else ()) if p)
        actions.append(QuickAction(
            f"Explain {selected.id}",
            f"Explain what widget {selected.id} ({selected.type}) shows and how it is wired: "
            "its bindings, actions and the tags involved."))
        if bindable:
            actions.append(QuickAction(
                f"Bind {selected.id}...",
                f"Bind widget {selected.id}'s {bindable[0]} to a suitable tag in project.edsui. "
                "Use an existing tag of this design when one fits, otherwise a new CONTRACT 2.5 "
                "tag name, and say which you chose."))
        widget = find_widget(index.project, selected_id)
        if widget is not None and widget.bindings:
            first_bound = next(iter(widget.bindings))
            actions.append(QuickAction(
                f"Add alarm to {selected.id}",
                f"Add warning and critical thresholds to widget {selected.id}'s {first_bound} binding "
                "in project.edsui, with sensible values for its range."))
    if index.issues():
        actions.append(QuickAction(
            "Fix binding issues",
            "Fix the binding issues listed in the design context by editing project.edsui."))
    actions.append(QuickAction(
        "Write backend for tags",
        "Implement the read functions in backend/backend.py so each tag returns a realistic value "
        "for this design; keep the CONTRACT 2 wire format."))
    actions.append(QuickAction(
        "Summarise design",
        "Summarise this design: pages, what each page is for, and the tags it depends on."))
    return actions


def find_widget(project, widget_id: str):
    """The DesignerWidget with that id anywhere in project (nested too), or None."""
    for widget in project.all_widgets():
        if widget.id == widget_id:
            return widget
    return None


__all__ = ["design_brief", "quick_actions", "find_widget", "QuickAction", "RULES", "DEFAULT_MAX_CHARS"]

_ = json
