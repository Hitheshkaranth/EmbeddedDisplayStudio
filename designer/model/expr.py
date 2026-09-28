"""The CONTRACT 13.2 expression language, in Python. FROZEN API (wave 1, W2).

Identical to native/hmi-ui/src/expr.c: CONTRACT 13.2 is the specification
and tests/fixtures/expr_cases.json the shared acceptance table (every row
gives the same result, or an error, on both sides).

Values: None (null), bool, float (numbers are always float), str.
"""
from __future__ import annotations

import math
import re

MAX_LENGTH = 512
MAX_TAGS = 16
MAX_DEPTH = 32
FUNCTIONS = {"abs": (1, 1), "floor": (1, 1), "ceil": (1, 1), "round": (1, 2),
             "min": (2, None), "max": (2, None), "clamp": (3, 3)}

_KEYWORDS = {"true", "false"}
_OPS = {"+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">="}
_COMPARATORS = {"==", "!=", "<", "<=", ">", ">="}
_TAG_RE = re.compile(r"[a-z][a-z0-9]*(\.[a-z0-9_]+)+$")


class ExprError(ValueError):
    """A compile error; str(e) is a one-line reason."""


class Expr:
    """A compiled expression."""

    text: str
    tags: tuple   # distinct tags, first-appearance order

    def evaluate(self, values: dict):
        """The value with `values` (tag -> value; a missing tag is null).
        Returns None, bool, float or str. Never raises."""
        if self._root is None:
            return None
        return self._root.evaluate(_lookup(values))

    __call__ = evaluate


def compile_expr(text: str) -> Expr:
    """Compile or raise ExprError."""
    return _Parser(text).parse()


def truthy(value) -> bool:
    """CONTRACT 13.1/13.2 truthy (same rule as actions_v2.truthy)."""
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value not in ("", "false", "0")
    if isinstance(value, (list, tuple)):
        return bool(value)
    return True


class _Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value=None, pos=0):
        self.kind = kind
        self.value = value
        self.pos = pos


class _Lexer:
    _NUMBERS = frozenset("0123456789")
    _DIGITS = frozenset("0123456789")

    def __init__(self, text: str):
        self.text = text
        self.i = 0
        self.n = len(text)

    def error(self, msg):
        raise ExprError(f"{msg} at {self.i}")

    def _peek(self, offset=0):
        j = self.i + offset
        return self.text[j] if j < self.n else ""

    def tokenize(self):
        toks = []
        while self.i < self.n:
            c = self.text[self.i]
            if c.isspace():
                self.i += 1
                continue
            if c in self._NUMBERS:
                toks.append(self._number())
                continue
            if c == '"':
                toks.append(self._string())
                continue
            if c.isalpha() or c == "_":
                word = self._identifier()
                if word in _KEYWORDS:
                    toks.append(_Token("keyword", word, self.i))
                elif word in _OPS:
                    toks.append(_Token("op", word, self.i))
                else:
                    toks.append(_Token("tag", word, self.i))
                continue
            if c in "+-*/%":
                toks.append(_Token("op", c, self.i)); self.i += 1; continue
            if c == "(":
                toks.append(_Token("lparen", c, self.i)); self.i += 1; continue
            if c == ")":
                toks.append(_Token("rparen", c, self.i)); self.i += 1; continue
            if c == ",":
                toks.append(_Token("comma", c, self.i)); self.i += 1; continue
            if c == "?":
                toks.append(_Token("qmark", c, self.i)); self.i += 1; continue
            if c == ":":
                toks.append(_Token("colon", c, self.i)); self.i += 1; continue
            if c == "!":
                if self._peek(1) == "=":
                    toks.append(_Token("op", "!=", self.i)); self.i += 2
                else:
                    toks.append(_Token("op", "!", self.i)); self.i += 1
                continue
            if c == "&" and self._peek(1) == "&":
                toks.append(_Token("op", "&&", self.i)); self.i += 2; continue
            if c == "|" and self._peek(1) == "|":
                toks.append(_Token("op", "||", self.i)); self.i += 2; continue
            if c == "=" and self._peek(1) == "=":
                toks.append(_Token("op", "==", self.i)); self.i += 2; continue
            if c == "<":
                if self._peek(1) == "=":
                    toks.append(_Token("op", "<=", self.i)); self.i += 2
                else:
                    toks.append(_Token("op", "<", self.i)); self.i += 1
                continue
            if c == ">":
                if self._peek(1) == "=":
                    toks.append(_Token("op", ">=", self.i)); self.i += 2
                else:
                    toks.append(_Token("op", ">", self.i)); self.i += 1
                continue
            self.error("invalid character " + repr(c))
        toks.append(_Token("end"))
        return toks

    def _number(self):
        start = self.i
        while self.i < self.n and self.text[self.i] in self._DIGITS:
            self.i += 1
        if self.i < self.n and self.text[self.i] == "." and self._peek(1) in self._DIGITS:
            self.i += 1
            while self.i < self.n and self.text[self.i] in self._DIGITS:
                self.i += 1
        token = self.text[start:self.i]
        try:
            value = float(token)
        except ValueError:
            self.error("invalid number " + token)
        return _Token("number", value, start)

    def _string(self):
        start = self.i
        self.i += 1
        out = []
        while self.i < self.n and self.text[self.i] != '"':
            c = self.text[self.i]
            if c == "\\":
                if self.i + 1 >= self.n:
                    self.error("unterminated string")
                nxt = self.text[self.i + 1]
                if nxt == '"':
                    out.append('"')
                elif nxt == "\\":
                    out.append("\\")
                else:
                    self.error("invalid escape \\%s" % nxt)
                self.i += 2
            else:
                out.append(c)
                self.i += 1
        if self.i >= self.n:
            self.error("unterminated string")
        self.i += 1
        return _Token("string", "".join(out), start)

    def _identifier(self):
        start = self.i
        while self.i < self.n and (self.text[self.i].isalnum() or self.text[self.i] == "_"):
            self.i += 1
        while (self.i < self.n and self.text[self.i] == "."
               and self.i + 1 < self.n and self.text[self.i + 1].isalpha()):
            self.i += 1
            while self.i < self.n and (self.text[self.i].isalnum() or self.text[self.i] == "_"):
                self.i += 1
        return self.text[start:self.i]


class _Lookup:
    def __init__(self, values: dict):
        self._values = values

    def __call__(self, name):
        return self._values.get(name)


def _lookup(values):
    return _Lookup(values)


class _Node:
    def evaluate(self, lookup):  # pragma: no cover - abstract
        raise NotImplementedError


class _Number(_Node):
    def __init__(self, value):
        self._value = float(value)

    def evaluate(self, lookup):
        return self._value


class _String(_Node):
    def __init__(self, value):
        self._value = value

    def evaluate(self, lookup):
        return self._value


class _Bool(_Node):
    def __init__(self, value):
        self._value = value

    def evaluate(self, lookup):
        return self._value


class _Tag(_Node):
    def __init__(self, name):
        self._name = name

    def evaluate(self, lookup):
        value = lookup(self._name)
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        return value


class _Unary(_Node):
    _OPS = {"!", "-", "neg"}

    def __init__(self, op, operand):
        self._op = op
        self._operand = operand

    def evaluate(self, lookup):
        if self._op == "!":
            v = self._operand.evaluate(lookup)
            return not truthy(v)
        v = self._operand.evaluate(lookup)
        if v is None:
            return None
        if self._op == "-":
            if isinstance(v, bool):
                return -float(v)
            if isinstance(v, (int, float)):
                return -float(v)
            return None
        return None


class _Binary(_Node):
    _OPS = {"+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">="}

    def __init__(self, op, left, right):
        self._op = op
        self._left = left
        self._right = right

    def evaluate(self, lookup):
        op = self._op
        if op == "&&":
            return truthy(self._left.evaluate(lookup)) and truthy(self._right.evaluate(lookup))
        if op == "||":
            return truthy(self._left.evaluate(lookup)) or truthy(self._right.evaluate(lookup))
        lt = self._left.evaluate(lookup)
        rt = self._right.evaluate(lookup)
        if op in ("==", "!="):
            if lt is None or rt is None:
                return False
            if isinstance(lt, str) or isinstance(rt, str):
                same = lt == rt
            elif isinstance(lt, bool) or isinstance(rt, bool):
                same = lt == rt
            else:
                same = lt == rt
            return (lt == rt) if op == "==" else (lt != rt)
        if op in ("<", "<=", ">", ">="):
            if lt is None or rt is None:
                return False
            if isinstance(lt, str) or isinstance(rt, str):
                return False
            if isinstance(lt, bool) and not isinstance(rt, bool):
                lt = float(lt)
            if isinstance(rt, bool) and not isinstance(lt, bool):
                rt = float(rt)
            try:
                if op == "<":
                    return lt < rt
                if op == "<=":
                    return lt <= rt
                if op == ">":
                    return lt > rt
                return lt >= rt
            except TypeError:
                return False
        if lt is None or rt is None:
            return None
        if isinstance(lt, str) or isinstance(rt, str):
            return None
        if isinstance(lt, bool):
            lt = float(lt)
        if isinstance(rt, bool):
            rt = float(rt)
        if op == "+":
            return lt + rt
        if op == "-":
            return lt - rt
        if op == "*":
            r = lt * rt
            if r in (float("inf"), float("-inf")) or r != r:
                return None
            return r
        if op == "/":
            if rt == 0:
                return None
            return lt / rt
        if op == "%":
            if rt == 0:
                return None
            return math.fmod(lt, rt)


class _Ternary(_Node):
    def __init__(self, condition, then_part, else_part):
        self._condition = condition
        self._then_part = then_part
        self._else_part = else_part

    def evaluate(self, lookup):
        return self._then_part.evaluate(lookup) if truthy(self._condition.evaluate(lookup)) \
            else self._else_part.evaluate(lookup)


class _Call(_Node):
    def __init__(self, name, args):
        self._name = name
        self._args = args

    def evaluate(self, lookup):
        args = [arg.evaluate(lookup) for arg in self._args]
        name = self._name
        if name == "abs":
            return _abs(args[0])
        if name == "floor":
            return _floor(args[0])
        if name == "ceil":
            return _ceil(args[0])
        if name == "round":
            n = args[1] if len(args) > 1 else None
            return _round(args[0], n)
        if name == "min":
            if any(a is None for a in args):
                return None
            r = args[0]
            for a in args[1:]:
                if a < r:
                    r = a
            return r
        if name == "max":
            if any(a is None for a in args):
                return None
            r = args[0]
            for a in args[1:]:
                if a > r:
                    r = a
            return r
        if name == "clamp":
            lo, hi = args[1], args[2]
            if args[0] is None or lo is None or hi is None:
                return None
            return max(lo, min(args[0], hi))
        return None


def _abs(x):
    if x is None or isinstance(x, str):
        return None
    if isinstance(x, bool):
        return 1.0
    return abs(float(x))


def _floor(x):
    if x is None or isinstance(x, str):
        return None
    if isinstance(x, bool):
        return float(x)
    return float(math.floor(float(x)))


def _ceil(x):
    if x is None or isinstance(x, str):
        return None
    if isinstance(x, bool):
        return float(x)
    return float(math.ceil(float(x)))


def _round(x, n=None):
    if isinstance(x, bool):
        x = float(x)
    if x is None or isinstance(x, str):
        return None
    if n is None:
        return float(_round_half(float(x)))
    if n < 0 or n > 6:
        return None
    factor = 10 ** int(n)
    return round(_round_half(float(x) * factor)) / factor


def _round_half(x):
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


class _Parser:
    def __init__(self, text: str):
        if len(text) > MAX_LENGTH:
            raise ExprError("expression too long")
        self._tokens = _Lexer(text).tokenize()
        self._pos = 0
        self._tags = []
        self._depth = 0
        self._root = None

    def error(self, msg):
        raise ExprError(msg)

    def parse(self):
        node = self._or_expr()
        if self._cur().kind != "end":
            self.error("unexpected %s" % self._cur().kind)
        expr = Expr()
        expr.text = None
        expr.tags = tuple(self._tags)
        expr._root = node
        return expr

    def _cur(self):
        return self._tokens[self._pos]

    def _next(self):
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _check(self, kind):
        return self._cur().kind == kind

    def _accept(self, kind):
        if self._cur().kind == kind:
            tok = self._next()
            return tok
        return None

    def _expect(self, kind):
        if self._cur().kind != kind:
            self.error("unexpected %s" % self._cur().kind)
        return self._next()

    def _tag(self, name):
        if not _TAG_RE.fullmatch(name):
            self.error("bad tag %r" % name)
        if len(self._tags) >= MAX_TAGS and name not in self._tags:
            self.error("too many tags")
        if name not in self._tags:
            self._tags.append(name)
        return _Tag(name)

    def _call(self, name):
        min_a, max_a = FUNCTIONS[name]
        self._enter()
        self._next()
        args = [self._or_expr()]
        while self._accept("comma"):
            args.append(self._or_expr())
        self._leave()
        self._expect("rparen")
        count = len(args)
        if count < min_a or (max_a is not None and count > max_a):
            self.error("function %s takes %s args" %
                       (name, min_a if max_a is None else "%d..%d" % (min_a, max_a)))
        return _Call(name, args)

    def _enter(self):
        self._depth += 1
        if self._depth > MAX_DEPTH:
            self.error("too deeply nested")

    def _leave(self):
        self._depth -= 1

    def _or_expr(self):
        cond = self._parse_condition()
        if self._cur().kind == "qmark":
            self._enter()
            self._next()
            then_part = self._or_expr()
            self._expect("colon")
            else_part = self._or_expr()
            self._leave()
            return _Ternary(cond, then_part, else_part)
        return cond

    def _parse_condition(self):
        node = self._and_expr()
        while self._cur().kind == "op" and self._cur().value == "||":
            op = self._next().value
            right = self._and_expr()
            node = _Binary(op, node, right)
        return node

    def _and_expr(self):
        node = self._comparison()
        while self._cur().kind == "op" and self._cur().value == "&&":
            op = self._next().value
            right = self._comparison()
            node = _Binary(op, node, right)
        return node

    def _comparison(self):
        node = self._additive()
        if self._cur().kind == "op" and self._cur().value in _COMPARATORS:
            op = self._next().value
            right = self._additive()
            node = _Binary(op, node, right)
        return node

    def _additive(self):
        node = self._multiplicative()
        while self._cur().kind == "op" and self._cur().value in ("+", "-"):
            op = self._next().value
            right = self._multiplicative()
            node = _Binary(op, node, right)
        return node

    def _multiplicative(self):
        node = self._unary()
        while self._cur().kind == "op" and self._cur().value in ("*", "/", "%"):
            op = self._next().value
            right = self._unary()
            node = _Binary(op, node, right)
        return node

    def _unary(self):
        if self._cur().kind == "op" and self._cur().value in ("!", "-"):
            op = self._next().value
            operand = self._unary()
            return _Unary(op, operand)
        return self._primary()

    def _primary(self):
        tok = self._cur()
        if tok.kind == "number":
            self._next()
            return _Number(tok.value)
        if tok.kind == "string":
            self._next()
            return _String(tok.value)
        if tok.kind == "keyword":
            self._next()
            return _Bool(tok.value == "true")
        if tok.kind == "tag":
            name = self._next().value
            if self._cur().kind == "lparen" and name in FUNCTIONS:
                return self._call(name)
            return self._tag(name)
        if tok.kind == "lparen":
            self._enter()
            self._next()
            node = self._or_expr()
            self._leave()
            self._expect("rparen")
            return node
        if tok.kind in ("op", "rparen", "comma", "qmark", "colon", "end"):
            self.error("unexpected %s" % tok.value if tok.kind == "op" else tok.kind)
        self.error("unexpected %s" % tok.kind)


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    cases = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
    for row in cases:
        try:
            got = compile_expr(row["expr"]).evaluate(row.get("values", {}))
        except ExprError as e:
            print(row["expr"], "ERROR:", e)
            continue
        print(row["expr"], "->", repr(got))