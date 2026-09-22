"""designer/layout/grid.py -- the grid every generated screen is laid out on.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W1. Signatures and
docstrings are the contract; W1 fills the bodies and may add private helpers.

One grid per screen size: a safe margin, a gutter, 12 columns and as many
rows as fit at roughly the gutter's rhythm. Every geometry the pipeline
produces lands on it, which is what makes edges line up and whitespace
read as deliberate.
"""
from __future__ import annotations

from dataclasses import dataclass

COLUMNS = 12


@dataclass(frozen=True)
class Grid:
    """The layout grid of one screen.

    Attributes:
        width, height: the screen in pixels.
        margin: the band at every edge no widget may enter.
        gutter: the gap between columns and between rows.
        columns: always COLUMNS (12).
        rows: how many rows the content area holds.
    """
    width: int
    height: int
    margin: int
    gutter: int
    columns: int
    rows: int

    @property
    def content_width(self) -> int:
        """Width inside the margins."""
        raise NotImplementedError

    @property
    def content_height(self) -> int:
        raise NotImplementedError

    def col_x(self, col: int) -> int:
        """Left edge of column `col` (0-based)."""
        raise NotImplementedError

    def col_span(self, span: int) -> int:
        """Width of `span` columns, gutters between them included."""
        raise NotImplementedError

    def row_y(self, row: int) -> int:
        raise NotImplementedError

    def row_span(self, span: int) -> int:
        raise NotImplementedError

    def cell(self, col: int, row: int, cspan: int = 1, rspan: int = 1) -> tuple[int, int, int, int]:
        """The (x, y, w, h) of a block of cells, clamped to the content area."""
        raise NotImplementedError

    def snap(self, x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        """The nearest grid-aligned rectangle to (x, y, w, h).

        Left and right edges go to column edges, top and bottom to row edges,
        the result is at least one cell and never leaves the content area.
        A rectangle already on the grid comes back unchanged.
        """
        raise NotImplementedError

    def nearest_cell(self, x: float, y: float) -> tuple[int, int]:
        """The (col, row) whose top-left is closest to the point."""
        raise NotImplementedError


def grid_for(width: int, height: int) -> Grid:
    """The grid for a screen of this size.

    Margin and gutter scale with the screen so a 480x272 panel is not given a
    desktop's whitespace: margin = clamp(round(min(w, h) * 0.035), 12, 40),
    gutter = clamp(round(margin * 0.6), 8, 24), rows = the number of gutter-
    rhythm rows that fit the content height (at least 6, at most 24).
    """
    raise NotImplementedError
