"""designer/layout/arrange.py -- snap, fit, align and de-overlap a page.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W1.

The deterministic half of making a draft look designed: every widget sized
to what its type needs, every edge on the grid, peers sharing edges and
baselines, and no two widgets on top of each other. It never invents or
drops a widget -- ids and types are the model's business, geometry is this
module's.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArrangeReport:
    """What one arrange pass did.

    Attributes:
        moved: widgets whose position changed.
        resized: widgets whose size changed.
        overlaps_before, overlaps_after: overlapping pairs on the page.
        offscreen_before, offscreen_after: widgets crossing the margins.
        notes: one short line per decision worth explaining to a user.
    """
    moved: int = 0
    resized: int = 0
    overlaps_before: int = 0
    overlaps_after: int = 0
    offscreen_before: int = 0
    offscreen_after: int = 0
    notes: list[str] = field(default_factory=list)


def arrange(project, page, registry, grid=None) -> ArrangeReport:
    """Lay `page` out on the grid, in place.

    Order of operations (each step keeps what the previous one achieved):
      1. fit every widget to its type's rule (constraints.fit_size);
      2. snap every rectangle to the grid;
      3. pull near-equal edges into alignment (within one gutter, left,
         right, top, bottom and centre lines) and give equal-role peers in
         a row the same height (and in a column the same width);
      4. resolve overlaps by pushing the smaller widget of each pair to the
         nearest free grid position, preferring the direction with room;
      5. keep everything inside the margins, shrinking rather than clipping.

    Containers are laid out with their children: a child's geometry is
    relative to its parent, so the parent is fitted first and children are
    arranged inside its content box.

    Args:
        project: the DesignerProject (screen size, theme).
        page: the DesignerPage to lay out; its widgets are mutated.
        registry: the widget registry.
        grid: the Grid to use, or None for grid_for(screen).

    Returns:
        ArrangeReport.
    """
    raise NotImplementedError


def overlaps(page) -> list[tuple[str, str, int]]:
    """Every overlapping pair of top-level widgets as (id_a, id_b, area)."""
    raise NotImplementedError


def align_edges(page, grid, tolerance: int | None = None) -> int:
    """Pull edges that are nearly equal into exact alignment; returns how
    many widgets moved. `tolerance` defaults to the grid's gutter."""
    raise NotImplementedError
