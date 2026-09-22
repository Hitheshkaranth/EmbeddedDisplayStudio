"""designer/layout/archetypes.py -- the compositions a screen can have.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W3.

Composition is the part a language model is worst at and a designer is best
at, so it is not asked for: a handful of human-designed slot templates on
the 12-column grid carry it, and the model's widgets are placed into the
slots by role. Every archetype has one hero, a legible reading order and
balanced whitespace by construction.
"""
from __future__ import annotations

from dataclasses import dataclass

# What a widget is for, which decides the slot it can take.
ROLES = ("hero", "primary", "secondary", "control", "status", "caption", "table", "rail")


@dataclass(frozen=True)
class Slot:
    """One place on the grid an archetype offers.

    Attributes:
        name: "hero", "left-rail", "footer-3", ... unique in the archetype.
        col, row, cspan, rspan: the block of grid cells it covers.
        role: which ROLES value belongs here.
        priority: lower is filled first when there are fewer widgets than slots.
    """
    name: str
    col: int
    row: int
    cspan: int
    rspan: int
    role: str
    priority: int = 0


@dataclass(frozen=True)
class Archetype:
    """A named composition.

    Attributes:
        id: "hero-centre", "thirds", "header-hero-rail", "card-grid", "split".
        name, description: shown to the user when a variant is offered.
        slots: the slots, in reading order.
        keywords: words in a brief that suggest this composition.
    """
    id: str
    name: str
    description: str
    slots: tuple
    keywords: tuple

    def slots_for(self, role: str) -> tuple:
        """Slots of this role, in priority order."""
        raise NotImplementedError


def archetypes() -> tuple:
    """Every archetype, in the order they are offered as variants.

    At least these five, each with one hero slot and 6-14 slots in total:
      hero-centre        one big instrument centred, rails either side,
                         a caption band at the top and controls at the foot
      thirds             three equal columns, hero in the middle column
      header-hero-rail   title band, hero left, a rail of cards on the right
      card-grid          a 2x3 or 3x3 grid of equal cards, no single hero
                         (hero slot spans two cells of the first row)
      split              two halves: instruments left, table/log right
    """
    raise NotImplementedError


def archetype_for(brief: str, widget_count: int, page=None) -> Archetype:
    """The archetype that suits this brief and this many widgets.

    Keyword match first ("cluster", "gauge" -> hero-centre; "alarm", "log",
    "table" -> split; "menu", "tiles", "overview" -> card-grid); otherwise by
    count: <= 4 hero-centre, <= 8 thirds, <= 12 header-hero-rail, else card-grid.
    """
    raise NotImplementedError


def role_for(registry, widget) -> str:
    """What this widget is for, from its type and size.

    Faces and charts are "primary" ("hero" when they are the largest face on
    the page), tiles and readouts "secondary", anything with signals
    "control", dots/telltales/alerts "status", Text "caption", tables
    "table"; a widget the archetype has no room for takes "rail".
    """
    raise NotImplementedError


def apply_archetype(project, page, archetype, registry, grid=None) -> list[str]:
    """Place every widget of `page` into `archetype`'s slots, in place.

    Widgets are ranked by role and by current area, and assigned to the
    slots of their role in priority order; a widget with no slot of its role
    left takes the next free slot of an adjacent role rather than being
    dropped. Each widget is then sized with constraints.fit_size inside its
    slot and centred in it. Containers keep their children.

    Returns:
        One note per placement decision worth explaining.
    """
    raise NotImplementedError
