"""designer/layout/critic.py -- how well composed a screen is, in numbers.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W2.

"Beautiful" is enforced, not requested: every candidate screen is measured,
and the pipeline keeps the best. The measures are deliberately blunt and
objective -- a designer would call them the difference between a draft and
a layout:

    overlap    widgets on top of each other (the baseline had a button
               inside a fuel gauge)
    margins    anything crossing the safe band, or off the screen
    alignment  how few distinct left/right/top/bottom edges the screen uses
    grid       how much of the geometry sits on the grid
    hierarchy  is there one clear hero, and a readable size ladder
    balance    ink spread across the screen, and whitespace symmetry
    proportion widgets at the aspect their type wants
    clipping   text or faces cut off (pixels; needs a render)
    contrast   readable foreground against what is behind it (pixels)

Geometry axes need no render. The pixel axes (clipping, contrast) are
scored only when an image is supplied, and are reported as None otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass

# The axes `Critique.scores` always carries, each 0..100.
AXES = ("overlap", "margins", "alignment", "grid", "hierarchy", "balance", "proportion",
        "clipping", "contrast")
# Weight of each axis in the overall score; pixel axes count only when scored.
WEIGHTS = {"overlap": 2.0, "margins": 1.5, "alignment": 1.5, "grid": 1.0, "hierarchy": 1.5,
           "balance": 1.0, "proportion": 1.5, "clipping": 1.5, "contrast": 1.0}


@dataclass(frozen=True)
class Issue:
    """One thing wrong with the screen.

    Attributes:
        kind: the axis it belongs to ("overlap", "proportion", ...).
        severity: "error" (a defect anyone would see), "warning", "nit".
        widget_id: the widget at fault, or "" for a whole-screen issue.
        detail: one line, specific and quantified, shown to the user.
    """
    kind: str
    severity: str
    widget_id: str
    detail: str


@dataclass(frozen=True)
class Critique:
    """The verdict on one screen.

    Attributes:
        score: 0..100, the weighted mean of the scored axes.
        scores: axis -> 0..100, or None for a pixel axis with no render.
        issues: every Issue found, worst first.
    """
    score: float
    scores: dict
    issues: tuple

    def summary(self) -> str:
        """One line: the score and the worst two issues."""
        raise NotImplementedError

    def errors(self) -> tuple:
        """Only the issues of severity "error"."""
        raise NotImplementedError


def critique(project, page, registry, image=None, grid=None) -> Critique:
    """Measure the composition of `page`.

    Args:
        project: the DesignerProject (screen size, theme, background).
        page: the DesignerPage to measure.
        registry: the widget registry.
        image: a QImage of the page as hmi-ui rendered it, or None. When
            given, the pixel axes are scored too; the image is expected at
            the screen's size (any size is scaled to it).
        grid: the Grid to measure against, or None for grid_for(screen).

    Returns:
        Critique. A page with no widgets scores 0 with one "empty" issue.
    """
    raise NotImplementedError


def render_for_critique(project, page, renderer=None):
    """A QImage of the page from hmi-ui, or None when no renderer is
    available (designer.preview.NativeRenderer.render_page_sync)."""
    raise NotImplementedError
