"""designer/layout/fit.py -- make a design fit its screen before it is laid out.

Layout cannot repair a page that does not fit. A fighter-jet brief asked for
35 widgets in a 1024x768 panel, and polish handed back 33 overlapping pairs;
the same design at 1920x1080 composed with none. So the question "does this fit?" is
asked first, and the answer "no" becomes pages: the widgets that matter most
stay on an overview, the rest move to a page per group (Engine 1, Engine 2,
Fuel, Health, Trends, ...), linked both ways by navigate buttons.

compose_project() is the whole pass: split what does not fit, polish every
page, and when a page still reports overlaps, move its least important
widget to its group's page and polish again -- a design never reaches the
canvas with widgets stacked on each other while there is somewhere to put
them.
"""
from __future__ import annotations

import re

from designer.layout.constraints import rule_for
from designer.layout.grid import grid_for
from designer.model import DesignerAction, DesignerPage, DesignerWidget

#: The share of a page's content area the widgets' minimum footprints (each
#: with a gutter around it) may take. Measured by stripping the fighter-jet
#: design (35 widgets, 1024x768) one least-important widget at a time and
#: polishing each step: no overlaps up to 0.26 (17 widgets), 2 at 0.29, 20
#: at 0.55. An engine dashboard that composed cleanly sits at 0.20.
FILL_LIMIT = 0.27

#: Rounds of "move the least important overlapping widget, polish again".
MAX_EVICTIONS = 40

#: What stays on the overview first. Higher is kept first.
_PRIORITY_BY_TYPE = {
    "ShClusterGauge": 100, "ShEngineGauge": 95, "ShAttitude": 100, "ShCompass": 90,
    "ShHSI": 90, "ShGauge": 85, "ShTape": 80,
    "ShAlarmTable": 88, "ShAlert": 86, "ShAnnunciator": 84, "ShMasterWarning": 90,
    "ShStatDot": 60, "ShStatusDot": 60, "ShTelltale": 62,
    "ShNumDisplay": 55, "ShValueTile": 58, "ShDataField": 55, "ShAutoReadout": 55,
    "ShSegmentBar": 52, "ShFuelQuantity": 70, "ShEngineBar": 65, "ShProgress": 45,
    "ShTrendChart": 40, "ShIconTile": 35, "Text": 30, "Image": 25,
}
_CONTROL_PRIORITY = 82      # anything with an action: a panel you cannot operate is worse
_TITLE_PRIORITY = 97        # the screen's own title stays with the overview
_NAV_PRIORITY = 1000        # navigation this pass added is never moved

_ENGINE_RE = re.compile(r"(?:eng(?:ine)?)[_\-. ]?([1-4])")
_TOPICS = (
    ("Fuel", ("fuel",)),
    ("Health", ("oil", "vib", "health", "egt", "temp", "pressure", "nozzle")),
    ("Trends", ("trend", "history", "chart")),
    ("Alerts", ("alarm", "alert", "warn", "fault", "caution")),
)
NAV_MARK = "_fitNavigation"


def priority(widget) -> int:
    """How strongly `widget` belongs on the overview (higher stays)."""
    if widget.properties.get(NAV_MARK):
        return _NAV_PRIORITY
    ident = widget.id.lower()
    if widget.type == "Text" and ("title" in ident or "header" in ident):
        return _TITLE_PRIORITY
    if widget.actions:
        return max(_CONTROL_PRIORITY, _PRIORITY_BY_TYPE.get(widget.type, 50))
    return _PRIORITY_BY_TYPE.get(widget.type, 50)


def group_of(widget) -> str:
    """The detail page a widget belongs on: "Engine 2", "Fuel", ... or "Details"."""
    words = " ".join([widget.id] + [b.tag for b in widget.bindings.values()]).lower()
    engine = _ENGINE_RE.search(words)
    if engine:
        return f"Engine {engine.group(1)}"
    for name, needles in _TOPICS:
        if any(needle in words for needle in needles):
            return name
    return "Details"


def footprint(registry, widget, gutter: int) -> int:
    """Pixels the widget needs at its minimum readable size, gutter included."""
    rule = rule_for(registry, widget.type)
    return (rule.min_width + gutter) * (rule.min_height + gutter)


def load(project, page, registry) -> float:
    """Minimum footprints of `page` over its content area (1.0 = wall to wall)."""
    grid = grid_for(project.screen.width, project.screen.height)
    area = grid.content_width * grid.content_height
    return sum(footprint(registry, w, grid.gutter) for w in page.widgets) / max(1, area)


def _page_id(name: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "", name.title().replace(" ", "")) or "Details"
    base = base[0].lower() + base[1:]
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}{n}", n + 1
    return candidate


def _nav_button(registry, widget_id: str, text: str, target: str) -> DesignerWidget:
    definition = registry.get("ShButton")
    width = definition.default_width if definition else 120
    height = definition.default_height if definition else 44
    return DesignerWidget(
        "ShButton", widget_id, {"x": 0, "y": 0, "width": width, "height": height},
        {"text": text, NAV_MARK: True},
        actions={"clicked": DesignerAction("navigate", page=target)})


def _detail_page(project, registry, name: str, overview) -> DesignerPage:
    """The page for group `name`, created (with its navigation) if missing."""
    for page in project.pages:
        if page.name == name:
            return page
    taken_ids = {p.id for p in project.pages}
    page = DesignerPage(_page_id(name, taken_ids), name, [])
    project.pages.append(page)
    taken_widgets = {w.id for w in project.all_widgets()}
    back_id = _unique(f"backFrom{page.id[0].upper()}{page.id[1:]}", taken_widgets)
    page.widgets.append(_nav_button(registry, back_id, f"‹ {overview.name}", overview.id))
    open_id = _unique(f"open{page.id[0].upper()}{page.id[1:]}", taken_widgets | {back_id})
    overview.widgets.append(_nav_button(registry, open_id, name, page.id))
    return page


def _unique(base: str, taken: set) -> str:
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}{n}", n + 1
    return candidate


def split_to_fit(project, page, registry) -> list[str]:
    """Move what does not fit on `page` to per-group pages; return notes.

    The most important widgets stay (see priority) until the page's budget
    is spent; every other widget goes to the page of its group, which gains
    a button back while the overview gains a button to it.
    """
    if load(project, page, registry) <= FILL_LIMIT:
        return []
    grid = grid_for(project.screen.width, project.screen.height)
    budget = FILL_LIMIT * grid.content_width * grid.content_height
    # Room for the overview's buttons to the detail pages, one per group
    # (at most the distinct groups on the page).
    button = footprint(registry, _nav_button(registry, "x", "", ""), grid.gutter)
    budget -= button * len({group_of(w) for w in page.widgets})
    keep_ids, used = set(), 0
    for widget in sorted(page.widgets, key=lambda w: -priority(w)):
        cost = footprint(registry, widget, grid.gutter)
        if used + cost <= budget:
            keep_ids.add(widget.id)
            used += cost
    move = [w for w in page.widgets if w.id not in keep_ids]
    if not move:
        return []
    page.widgets[:] = [w for w in page.widgets if w.id in keep_ids]
    moved_to: dict[str, int] = {}
    for widget in move:
        target = _detail_page(project, registry, group_of(widget), page)
        target.widgets.append(widget)
        moved_to[target.name] = moved_to.get(target.name, 0) + 1
    size = f"{project.screen.width}×{project.screen.height}"
    return [f"{count} widget(s) moved to page “{name}”: “{page.name}” "
            f"could not hold them at {size}" for name, count in moved_to.items()]


def _place_strip(buttons, project, grid) -> None:
    """Lay navigation buttons out as one centred row along the foot."""
    count = len(buttons)
    height = max(int(b.geometry["height"]) for b in buttons)
    width = max(int(b.geometry["width"]) for b in buttons)
    room = grid.content_width - (count - 1) * grid.gutter
    width = max(64, min(width, room // count))
    total = count * width + (count - 1) * grid.gutter
    x = grid.margin + max(0, (grid.content_width - total) // 2)
    y = project.screen.height - grid.margin - height
    for button in buttons:
        button.geometry.update({"x": x, "y": y, "width": width, "height": height})
        x += width + grid.gutter


def _polish_page(project, page, registry, polish, brief, renderer):
    """Polish `page` with its navigation held out, in a strip of its own.

    Laid out as content, the buttons to the detail pages landed wherever an
    archetype slot was free -- one by the title, one mid-screen, one in a
    corner. The content is composed on the screen less the strip, and the
    buttons go in one row beneath it.
    """
    nav = [w for w in page.widgets if w.properties.get(NAV_MARK)]
    if not nav:
        return polish(project, page, registry, brief=brief, renderer=renderer)
    grid = grid_for(project.screen.width, project.screen.height)
    strip = max(int(w.geometry["height"]) for w in nav) + grid.gutter
    page.widgets[:] = [w for w in page.widgets if not w.properties.get(NAV_MARK)]
    height = project.screen.height
    project.screen.height = height - strip
    try:
        report = polish(project, page, registry, brief=brief, renderer=renderer)
    finally:
        project.screen.height = height
    _place_strip(nav, project, grid)
    page.widgets.extend(nav)
    return report


def _overlapping(verdict) -> list[str]:
    """Widget ids the critique blames for overlaps."""
    return [issue.widget_id for issue in getattr(verdict, "issues", ())
            if issue.kind == "overlap" and issue.severity == "error" and issue.widget_id]


def compose_project(project, registry, polish, brief: str = "", renderer=None) -> tuple:
    """Fit, polish and de-collide every page of `project`, in place.

    Args:
        project: the design; pages may be added.
        registry: the widget registry.
        polish: designer.layout.polish.polish, or a substitute in a test.
        brief: the user's words, for the archetype choice.
        renderer: optional NativeRenderer for the critique's pixel axes.

    Returns:
        (first PolishReport or None, notes): the notes say what moved where.
    """
    notes: list[str] = []
    overview = project.pages[0] if project.pages else None
    if overview is None:
        return None, notes
    # Split only the overview: detail pages are born from it. A page the model
    # made itself is laid out as it is, and de-collided below like any other.
    notes += split_to_fit(project, overview, registry)
    reports = {}
    for page in list(project.pages):
        # The brief describes the whole screen; a detail page is laid out
        # for what is on it ("engine" in the brief chose a hero layout for a
        # page of four readouts, which then sat in its corners).
        page_brief = brief if page is overview else ""
        reports[page.id] = _polish_page(project, page, registry, polish, page_brief, renderer)
    for _ in range(MAX_EVICTIONS):
        moved = False
        for page in list(project.pages):
            blamed = set(_overlapping(reports[page.id].after))
            victims = [w for w in page.widgets if w.id in blamed and not w.properties.get(NAV_MARK)]
            if not victims:
                continue
            victim = min(victims, key=priority)
            name = group_of(victim)
            if page.name == name:
                name = f"{name} (more)"
            pages_before = len(project.pages)
            target = _detail_page(project, registry, name, overview)
            page.widgets.remove(victim)
            target.widgets.append(victim)
            notes.append(f"{victim.id} moved to page “{target.name}”: it overlapped on "
                          f"“{page.name}”")
            touched = [page, target]
            if len(project.pages) > pages_before and overview not in touched:
                touched.append(overview)       # it just gained a button
            for touched_page in touched:
                reports[touched_page.id] = _polish_page(
                    project, touched_page, registry, polish,
                    brief if touched_page is overview else "", renderer)
            moved = True
            break
        if not moved:
            break
    return reports.get(overview.id), notes

