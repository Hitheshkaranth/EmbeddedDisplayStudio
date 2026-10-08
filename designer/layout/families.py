"""designer/layout/families.py -- a screen's layout family, searched by kind.

A planned screen is laid out on the spot by the family that recognises it: the
cab display is one family (designer/layout/cab.py lays it the standard way),
and any later family that recognises a page of a given shape lays it out too,
without the compiler caring which family won. A family is a name, a test for
"does this page look like a family X", and a compile that lays it out; the
compiler searches them in registration order and uses the first that fits.
"""
from __future__ import annotations

# Registered families, by name: a tuple of (applies, compile). A page is one
# family when its first-applies test is true, so registration order decides
# between families that both fit.
_FAMILIES: dict = {}


def _builtin() -> None:
    """Load the families the Studio ships, which register on import.

    Imported here rather than at the top: cab.py imports this module to
    register itself, so the search loads it on first use instead.
    """
    from . import cab  # noqa: F401


def register(name: str, applies, compile) -> None:
    """Register one layout family.

    ``applies(sections, header, width, height)`` returns True when a page of
    this shape is a family, and ``compile`` lays a page the family lays out --
    the compiler calls it as ``compile(project, page, registry, sections,
    title, header, report, width, height)``.
    """
    _FAMILIES[name] = (applies, compile)


def unregister(name: str) -> None:
    """Remove a family, so a test (or a later family) can re-open the search."""
    _FAMILIES.pop(name, None)


def names() -> list:
    """Every registered family's name, in registration order."""
    _builtin()
    return list(_FAMILIES)


def family_for(sections, header, width, height):
    """The first family that fits a page, as ``(name, compile)`` or None.

    ``sections`` and ``header`` are the page's content; ``width`` and
    ``height`` its size, because a family that fits one size (a cab display on
    a wide screen) may not fit another. A page no family fits gets None, and
    the caller falls back to its own default layout.
    """
    _builtin()
    for name, (applies, compile) in list(_FAMILIES.items()):
        try:
            if applies(sections, header, width, height):
                return name, compile
        except Exception:
            continue
    return None