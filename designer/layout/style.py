"""designer/layout/style.py -- surfaces, type scale and semantic colour.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W3.

Geometry alone does not make a screen look designed: related things have to
sit on a surface, text has to come in three or four deliberate sizes rather
than a dozen accidental ones, and colour has to mean something. This pass
applies the kit's own tokens (Theme.qml, the same ones hmi-ui renders with)
to a laid-out page.
"""
from __future__ import annotations

# The type scale, in px, for a 1024x768 screen; scaled with the screen's
# diagonal for other sizes. display: the hero readout; title: a screen or
# card heading; body: a readout; caption: a label under a value.
TYPE_SCALE = {"display": 44, "title": 20, "body": 15, "caption": 12}


def apply_style(project, page, registry, grid=None) -> list[str]:
    """Style `page` in place; returns a note per change worth explaining.

    In order:
      1. Type scale: every Text widget's fontSize snaps to the nearest step
         of TYPE_SCALE for its role (the page's one title -> "title", labels
         under widgets -> "caption", the rest -> "body"), scaled for the
         screen; nothing ends up between two steps.
      2. Semantic colour: a widget bound to a tag with warning/critical
         thresholds gets the kit's warning/destructive tokens for its zones;
         success/ok states get the success token; nothing keeps a raw hex
         the model invented when a token means the same thing.
      3. Captions: a face with no label of its own (constraints.wants_caption)
         gets a Text caption under it, from its binding's tag or its id,
         sized "caption" and aligned to the face's left edge.
      4. Consistency: every widget that carries a corner radius or border
         colour takes the theme's radius/border so cards, tiles and buttons
         agree.
    The background of the screen is left alone: it is the design's own.
    """
    raise NotImplementedError


def group_into_cards(project, page, registry, grid=None) -> list[str]:
    """Put related widgets on ShCard surfaces, in place.

    Widgets that sit in the same grid band and share a role (a row of
    readouts, a column of status lamps) are wrapped in one ShCard with a
    title from what they have in common (the tag prefix, or the role), the
    children re-laid inside the card's content box with the grid's gutter.
    A group of one is not worth a card. Returns a note per card created.
    """
    raise NotImplementedError


def theme_colour(project, token: str) -> str:
    """The '#rrggbb' of a kit theme token ('warning', 'destructive',
    'success', 'card', 'border', 'mutedForeground', ...) for the project's
    theme, read from the same tokens the panel renders with."""
    raise NotImplementedError
