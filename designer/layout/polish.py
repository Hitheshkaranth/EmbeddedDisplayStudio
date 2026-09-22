"""designer/layout/polish.py -- the loop that turns a draft into a screen.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W4.

    archetype -> arrange -> style -> critique -> (fix and repeat)

and, when asked for variants, the same over several archetypes with the
best-scoring result kept. This is what the AI tab calls on every generated
section, and what the Designer's "Tidy up" runs on a hand-drawn page.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PolishReport:
    """What polishing did and how much it helped.

    Attributes:
        before, after: the Critique of the page as it arrived and as it left.
        archetype: the archetype id used.
        rounds: how many arrange/critique rounds ran.
        notes: the notes from every pass, in order.
        candidates: (archetype_id, score) for every variant tried, best first.
    """
    before: object
    after: object
    archetype: str
    rounds: int = 1
    notes: list = field(default_factory=list)
    candidates: list = field(default_factory=list)

    @property
    def gain(self) -> float:
        """after.score - before.score."""
        raise NotImplementedError


def polish(project, page, registry, brief: str = "", renderer=None,
           rounds: int = 2, variants: int = 1) -> PolishReport:
    """Compose `page` in place and report on it.

    Args:
        project, page, registry: what to work on.
        brief: the user's words, when there are any; picks the archetype.
        renderer: a designer.preview.NativeRenderer for the pixel axes of
            the critique, or None to score geometry only.
        rounds: how many arrange/critique rounds at most; a round that does
            not improve the score is rolled back and ends the loop.
        variants: how many archetypes to try (1 = only the best match).
            The highest-scoring result is the one left on `page`.

    Returns:
        PolishReport. Widget ids, types, properties, bindings and actions are
        never changed by polishing -- only geometry, the style pass's own
        properties (font sizes, colours, captions it adds) and card grouping.
    """
    raise NotImplementedError


def polish_candidates(project, page, registry, brief: str = "", renderer=None,
                      limit: int = 3) -> list:
    """Several composed versions of the same page, best first.

    Returns a list of (DesignerPage, Critique, archetype_id); `page` itself
    is not modified. The AI tab shows these as thumbnails to choose from.
    """
    raise NotImplementedError
