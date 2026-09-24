"""designer/layout -- what makes a generated screen look designed.

A model asked for absolute geometry produces overlapping, unaligned,
wrongly-proportioned screens (see tests/fixtures/layout/ai-baseline.edsui,
a real run). This package turns such a draft into a composed screen and can
say, in numbers, how well composed any screen is:

    grid        the 12-column grid every screen is laid out on
    constraints what each widget type needs to look right (min size, aspect)
    arrange     snap, fit, align and de-overlap a page on the grid
    archetypes  human-designed slot templates (hero-centre, thirds, ...)
    style       surfaces, typography scale and semantic colour
    critic      measurable composition quality, geometry and pixels
    polish      the loop: archetype -> arrange -> style -> critique -> fix
    fit         pages for what one screen cannot hold, then polish, then
                move whatever still overlaps

Nothing here talks to a model: the AI tab calls `polish` on whatever the
model produced, and the same functions serve the Designer's own
"Tidy up" action.
"""
from .arrange import ArrangeReport, arrange
from .archetypes import Archetype, Slot, apply_archetype, archetype_for, archetypes, role_for
from .constraints import WidgetRule, fit_size, rule_for
from .critic import Critique, Issue, critique
from .grid import Grid, grid_for
from .polish import PolishReport, polish
from .style import apply_style

__all__ = [
    "ArrangeReport", "arrange", "Archetype", "Slot", "apply_archetype", "archetype_for",
    "archetypes", "role_for", "WidgetRule", "fit_size", "rule_for", "Critique", "Issue",
    "critique", "Grid", "grid_for", "PolishReport", "polish", "apply_style",
]
