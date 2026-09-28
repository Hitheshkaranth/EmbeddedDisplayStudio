"""The CONTRACT 13.2 expression language, in Python. FROZEN API (wave 1, W2).

Identical to native/hmi-ui/src/expr.c: CONTRACT 13.2 is the specification
and tests/fixtures/expr_cases.json the shared acceptance table (every row
gives the same result, or an error, on both sides).

Values: None (null), bool, float (numbers are always float), str.
"""
from __future__ import annotations

MAX_LENGTH = 512
MAX_TAGS = 16
MAX_DEPTH = 32
FUNCTIONS = {"abs": (1, 1), "floor": (1, 1), "ceil": (1, 1), "round": (1, 2),
             "min": (2, None), "max": (2, None), "clamp": (3, 3)}


class ExprError(ValueError):
    """A compile error; str(e) is a one-line reason."""


class Expr:
    """A compiled expression."""

    text: str
    tags: tuple   # distinct tags, first-appearance order

    def evaluate(self, values: dict):
        """The value with `values` (tag -> value; a missing tag is null).
        Returns None, bool, float or str. Never raises."""
        raise NotImplementedError


def compile_expr(text: str) -> Expr:
    """Compile or raise ExprError."""
    raise NotImplementedError


def truthy(value) -> bool:
    """CONTRACT 13.1/13.2 truthy (same rule as actions_v2.truthy)."""
    raise NotImplementedError
