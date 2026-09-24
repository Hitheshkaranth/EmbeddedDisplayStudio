"""designer/layout/polish.py -- the loop that turns a draft into a screen.

    archetype -> arrange -> style -> critique -> (fix and repeat)

and, when asked for variants, the same over several archetypes with the
best-scoring result kept. This is what the AI tab calls on every generated
section, and what the Designer's "Tidy up" runs on a hand-drawn page.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

# A caption is the style pass's invention, not part of the design, so a
# second polish has to rebuild it rather than compose around it: otherwise
# the second run lays out more widgets than the first and the pipeline stops
# being idempotent. Polish marks what the style pass added with this
# property and takes it away again at the start of the next run, where the
# same pass puts the same caption straight back.
CAPTION_MARK = "_composedCaption"


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
        return _score(self.after) - _score(self.before)


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
    archetypes_module, _arrange, critic_module, grid_module, _style = _modules()
    grid = _grid_for(project, grid_module)
    before = critic_module.critique(project, page, registry,
                                    image=_image(project, page, renderer, critic_module),
                                    grid=grid)
    # The page belongs to the caller: if any pass raises, it goes back as it came.
    original = copy.deepcopy(page.widgets)
    try:
        _strip_captions(page.widgets)
        count = sum(1 for _ in _walk(page.widgets))
        results = []
        for archetype in _archetype_order(archetypes_module, brief, count, page, variants):
            trial_page = copy.deepcopy(page)
            verdict, notes, ran = _compose(_trial(project, trial_page), trial_page, registry,
                                           archetype, grid, rounds, renderer)
            results.append((_score(verdict), archetype, trial_page, verdict, notes, ran))
        if not results:
            page.widgets[:] = original
            return PolishReport(before=before, after=before, archetype="", rounds=0)
        best = results[0]
        for item in results[1:]:
            if item[0] > best[0] + 1e-9:
                best = item
        page.widgets[:] = best[2].widgets
        after = critic_module.critique(project, page, registry,
                                       image=_image(project, page, renderer, critic_module),
                                       grid=grid)
    except Exception:
        page.widgets[:] = original
        raise
    candidates = sorted(((getattr(item[1], "id", ""), item[0]) for item in results),
                        key=lambda entry: (-entry[1], entry[0]))
    return PolishReport(before=before, after=after, archetype=getattr(best[1], "id", ""),
                        rounds=best[5], notes=list(best[4]), candidates=candidates)


def polish_candidates(project, page, registry, brief: str = "", renderer=None,
                      limit: int = 3) -> list:
    """Several composed versions of the same page, best first.

    Returns a list of (DesignerPage, Critique, archetype_id); `page` itself
    is not modified. The AI tab shows these as thumbnails to choose from.
    """
    archetypes_module, _arrange, _critic, grid_module, _style = _modules()
    grid = _grid_for(project, grid_module)
    base = copy.deepcopy(page)
    _strip_captions(base.widgets)
    count = sum(1 for _ in _walk(base.widgets))
    results = []
    for archetype in _archetype_order(archetypes_module, brief, count, base, limit):
        trial_page = copy.deepcopy(base)
        verdict, _notes, _ran = _compose(_trial(project, trial_page), trial_page, registry,
                                         archetype, grid, 2, renderer)
        results.append((trial_page, verdict, getattr(archetype, "id", "")))
    results.sort(key=lambda entry: (-_score(entry[1]), entry[2]))
    return results


def summary(report) -> str:
    """``Composed: hero-centre, 62 -> 88`` -- one line for a run log."""
    if report is None:
        return ""
    return "Composed: %s, %.0f → %.0f" % (report.archetype or "as drawn",
                                               _score(report.before), _score(report.after))


def _modules():
    """The sibling passes, imported late so the package still imports while a
    dependency is a skeleton, and so a test may stand one of them in.

    Through importlib, not `from . import ...`: the package re-exports
    `arrange` and `archetypes` as functions, which shadow the submodules of
    the same name once __init__ has run.
    """
    import importlib
    return tuple(importlib.import_module(f"{__package__}.{name}")
                 for name in ("archetypes", "arrange", "critic", "grid", "style"))


def _score(verdict) -> float:
    try:
        return float(getattr(verdict, "score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _walk(widgets):
    for widget in widgets:
        yield widget
        yield from _walk(widget.children)


def _grid_for(project, grid_module, grid=None):
    if grid is not None:
        return grid
    return grid_module.grid_for(int(project.screen.width), int(project.screen.height))


def _trial(project, page):
    """A stand-in project holding only `page`.

    The style pass asks the project for a free widget id; with the original
    page still in it, a caption rebuilt under the same face would come back
    named `fuelCaption2`, which is how an idempotent pipeline stops being one.
    """
    trial = copy.copy(project)
    trial.pages = [page]
    return trial


def _image(project, page, renderer, critic_module):
    """The page as hmi-ui draws it, or None: the pixel axes are a bonus, and
    a missing binary or a dead child process must not fail a polish."""
    if renderer is None:
        return None
    try:
        return critic_module.render_for_critique(project, page, renderer)
    except Exception:
        return None


def _strip_captions(widgets) -> int:
    """Drop the captions a previous polish added; returns how many went."""
    removed, keep = 0, []
    for widget in widgets:
        removed += _strip_captions(widget.children)
        if widget.properties.get(CAPTION_MARK) and not widget.children:
            removed += 1
            continue
        keep.append(widget)
    widgets[:] = keep
    return removed


def _mark_captions(page, known_ids) -> None:
    """Mark the leaf text the style pass just invented as polish's own."""
    for widget in _walk(page.widgets):
        if widget.id in known_ids or widget.children or widget.type != "Text":
            continue
        widget.properties[CAPTION_MARK] = True


def _archetype_order(archetypes_module, brief, count, page, limit):
    """The archetype that suits the brief, then the rest in offer order."""
    chosen = archetypes_module.archetype_for(brief or "", count, page)
    order, seen = [], set()
    for candidate in [chosen] + list(archetypes_module.archetypes() or ()):
        if candidate is None:
            continue
        identity = getattr(candidate, "id", None)
        if identity in seen:
            continue
        seen.add(identity)
        order.append(candidate)
    return order[:max(1, int(limit))]


def _compose(project, page, registry, archetype, grid, rounds, renderer):
    """One archetype, all the way through; returns (critique, notes, rounds)."""
    archetypes_module, arrange_module, critic_module, _grid, style_module = _modules()

    notes = list(archetypes_module.apply_archetype(project, page, archetype, registry, grid) or [])
    report = arrange_module.arrange(project, page, registry, grid)
    notes += list(getattr(report, "notes", None) or [])
    known = {widget.id for widget in _walk(page.widgets)}
    notes += list(style_module.apply_style(project, page, registry, grid) or [])
    _mark_captions(page, known)

    verdict = critic_module.critique(project, page, registry,
                                     image=_image(project, page, renderer, critic_module),
                                     grid=grid)
    ran = 1
    while ran < max(1, int(rounds)):
        # Every extra round is a bet: keep what it produced only when the
        # score went up, and stop at the first round that does not pay.
        snapshot = copy.deepcopy(page.widgets)
        again = arrange_module.arrange(project, page, registry, grid)
        ran += 1
        candidate = critic_module.critique(project, page, registry,
                                           image=_image(project, page, renderer, critic_module),
                                           grid=grid)
        if _score(candidate) > _score(verdict) + 1e-9:
            verdict = candidate
            notes += list(getattr(again, "notes", None) or [])
        else:
            page.widgets[:] = snapshot
            break
    return verdict, notes, ran
