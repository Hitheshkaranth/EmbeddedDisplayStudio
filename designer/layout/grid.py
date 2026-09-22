"""designer/layout/grid.py -- the grid every generated screen is laid out on.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W1. Signatures and
docstrings are the contract; W1 fills the bodies and may add private helpers.

One grid per screen size: a safe margin, a gutter, 12 columns and as many
rows as fit at roughly the gutter's rhythm. Every geometry the pipeline
produces lands on it, which is what makes edges line up and whitespace
read as deliberate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

COLUMNS = 12
# A screen is never cut into fewer than six or more than twenty-four rows:
# below six a row is a band rather than a rhythm, above it a cell is smaller
# than the gutter beside it.
MIN_ROWS = 6
MAX_ROWS = 24


def _round(value: float) -> int:
    """Half-up rounding -- Python's round() is half-to-even, which would make
    one screen size's margin differ from its neighbour's for no reason."""
    return int(math.floor(float(value) + 0.5))


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _tile(total: int, count: int, gap: int) -> tuple[int, list[int]]:
    """`count` equal slots separated by `count - 1` gaps, tiling `total`.

    Every slot is the same size, so the width of a span is one number rather
    than a number per starting column; the pixels that do not divide evenly
    are handed out one at a time to the first gaps, which keeps the last
    slot's far edge exactly on `total`.
    """
    count = max(1, int(count))
    gap = max(0, int(gap))
    inner = total - gap * (count - 1)
    size = max(1, inner // count)
    spare = max(0, total - (size * count + gap * (count - 1)))
    gaps = [gap + (1 if index < spare else 0) for index in range(count - 1)]
    return size, gaps


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

    # -- the two axes ----------------------------------------------------
    def _cols(self) -> tuple[int, list[int]]:
        return _tile(self.content_width, self.columns, self.gutter)

    def _rows(self) -> tuple[int, list[int]]:
        return _tile(self.content_height, self.rows, self.gutter)

    @property
    def content_width(self) -> int:
        """Width inside the margins."""
        return max(1, int(self.width) - 2 * int(self.margin))

    @property
    def content_height(self) -> int:
        return max(1, int(self.height) - 2 * int(self.margin))

    @property
    def content_right(self) -> int:
        """The first pixel column outside the content area."""
        return self.margin + self.content_width

    @property
    def content_bottom(self) -> int:
        return self.margin + self.content_height

    def col_x(self, col: int) -> int:
        """Left edge of column `col` (0-based)."""
        size, gaps = self._cols()
        col = _clamp(int(col), 0, self.columns - 1)
        return self.margin + col * size + sum(gaps[:col])

    def col_span(self, span: int) -> int:
        """Width of `span` columns, gutters between them included."""
        size, gaps = self._cols()
        span = _clamp(int(span), 1, self.columns)
        return span * size + sum(gaps[:span - 1])

    def row_y(self, row: int) -> int:
        size, gaps = self._rows()
        row = _clamp(int(row), 0, self.rows - 1)
        return self.margin + row * size + sum(gaps[:row])

    def row_span(self, span: int) -> int:
        size, gaps = self._rows()
        span = _clamp(int(span), 1, self.rows)
        return span * size + sum(gaps[:span - 1])

    def cell(self, col: int, row: int, cspan: int = 1, rspan: int = 1) -> tuple[int, int, int, int]:
        """The (x, y, w, h) of a block of cells, clamped to the content area."""
        col = _clamp(int(col), 0, self.columns - 1)
        row = _clamp(int(row), 0, self.rows - 1)
        cspan = _clamp(int(cspan), 1, self.columns - col)
        rspan = _clamp(int(rspan), 1, self.rows - row)
        x, y = self.col_x(col), self.row_y(row)
        width = self.col_x(col + cspan - 1) + self._cols()[0] - x
        height = self.row_y(row + rspan - 1) + self._rows()[0] - y
        return x, y, min(width, self.content_right - x), min(height, self.content_bottom - y)

    # -- edges -----------------------------------------------------------
    def col_lefts(self) -> list[int]:
        """The left edge of every column."""
        return [self.col_x(col) for col in range(self.columns)]

    def col_rights(self) -> list[int]:
        """The right edge of every column."""
        size = self._cols()[0]
        return [left + size for left in self.col_lefts()]

    def row_tops(self) -> list[int]:
        """The top edge of every row."""
        return [self.row_y(row) for row in range(self.rows)]

    def row_bottoms(self) -> list[int]:
        """The bottom edge of every row."""
        size = self._rows()[0]
        return [top + size for top in self.row_tops()]

    def snap(self, x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        """The nearest grid-aligned rectangle to (x, y, w, h).

        Left and right edges go to column edges, top and bottom to row edges,
        the result is at least one cell and never leaves the content area.
        A rectangle already on the grid comes back unchanged.
        """
        left, right = _snap_axis(self.col_lefts(), self.col_rights(), x, w)
        top, bottom = _snap_axis(self.row_tops(), self.row_bottoms(), y, h)
        return left, top, right - left, bottom - top

    def nearest_cell(self, x: float, y: float) -> tuple[int, int]:
        """The (col, row) whose top-left is closest to the point."""
        return nearest_edge(self.col_lefts(), x), nearest_edge(self.row_tops(), y)


def nearest_edge(edges: list[int], value: float) -> int:
    """Index of the edge closest to `value`; the lower edge wins a tie."""
    return min(range(len(edges)), key=lambda index: (abs(edges[index] - value), index))


def _snap_axis(starts: list[int], ends: list[int], position: float, length: float) -> tuple[int, int]:
    """The nearest whole run of cells to one side of a rectangle."""
    first = nearest_edge(starts, position)
    far = position + max(0.0, float(length))
    last = min(range(first, len(ends)), key=lambda index: (abs(ends[index] - far), index))
    return starts[first], ends[last]


def grid_for(width: int, height: int) -> Grid:
    """The grid for a screen of this size.

    Margin and gutter scale with the screen so a 480x272 panel is not given a
    desktop's whitespace: margin = clamp(round(min(w, h) * 0.035), 12, 40),
    gutter = clamp(round(margin * 0.6), 8, 24), rows = the number of gutter-
    rhythm rows that fit the content height (at least 6, at most 24).
    """
    width = max(1, int(width))
    height = max(1, int(height))
    shortest = min(width, height)
    margin = _clamp(_round(shortest * 0.035), 12, 40)
    # A panel small enough for that margin to eat it keeps a quarter of itself.
    margin = min(margin, max(1, shortest // 4))
    gutter = _clamp(_round(margin * 0.6), 8, 24)

    content_width = max(1, width - 2 * margin)
    content_height = max(1, height - 2 * margin)
    column = _tile(content_width, COLUMNS, gutter)[0]
    # Square-ish cells: the row count whose row height lands closest to a
    # column's width. A tie goes to the smaller count -- fewer, larger cells.
    rows = min(range(MIN_ROWS, MAX_ROWS + 1),
               key=lambda count: (abs(_tile(content_height, count, gutter)[0] - column), count))
    return Grid(width=width, height=height, margin=margin, gutter=gutter,
                columns=COLUMNS, rows=rows)
