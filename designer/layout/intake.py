"""designer/layout/intake.py -- read what a model wrote the way it meant it.

Two faults cost whole designs before layout ever ran:

* One malformed character in the model's JSON (a missing closing quote,
  ``"critical": "> 95}}}``) failed ``json.loads`` for the entire payload, and
  the salvage path then put ``Partial_ShStatDot`` placeholders on the screen.
  ``loads_lenient`` repairs the faults models actually make -- comments,
  trailing commas, Python literals, an unclosed string, a truncated tail --
  and only gives up when the text is not JSON-shaped at all.
* A model names a property the way another widget spells it
  (``minimumValue`` on an ShGauge, which takes ``minimum``; ``label`` on an
  ShValueTile, which takes ``title``). The registry filter then dropped it and
  the face drew its default caption ("Gauge", "Button"). ``normalise_properties``
  maps every synonym onto the spelling this type declares.
"""
from __future__ import annotations

import json
import re

# -- lenient JSON ------------------------------------------------------------

_MAX_REPAIRS = 24
# Where an object keeps the keys that followed a duplicate key (see _pairs).
SPILL_KEY = "__spill__"


def _pairs(pairs):
    """object_pairs_hook: a repeated key starts a new object.

    `]}],"title": "Day Tank", "role": ...` -- a model that writes `],`
    where a section should open gives the page a second "title", and plain
    json keeps the last one: the page loses its title and the section its
    identity. Keeping the first value and spilling the rest lets the reader
    put the section back (tools/hmi_deployer/ai_generator._fold_stray_sections).
    """
    result, spills, current = {}, [], None
    for key, value in pairs:
        target = result if current is None else current
        if key in target:
            current = {}
            spills.append(current)
            target = current
        target[key] = value
    if spills:
        result[SPILL_KEY] = spills
    return result


def _loads(text):
    return json.loads(text, object_pairs_hook=_pairs)


def loads_lenient(text: str):
    """``json.loads`` that survives the mistakes models make.

    Returns the parsed value, or raises ``ValueError`` when the text cannot
    be repaired into JSON.
    """
    text = str(text or "").strip()
    try:
        return _loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    candidate = base = _python_literals(_strip_trailing_commas(_strip_comments(text)))
    for _ in range(_MAX_REPAIRS):
        try:
            return _loads(candidate)
        except json.JSONDecodeError as exc:
            repaired = _repair_at(candidate, exc)
            if repaired is None or repaired == candidate:
                break
            candidate = repaired
    # A reply cut off mid-widget: keep every value that was finished. Tried
    # on the repaired text and on the text as it came, since a repair aimed
    # at the cut can make it look closed.
    for source in (candidate, base):
        closed = _close_truncated(source)
        if closed is None:
            continue
        try:
            return _loads(_strip_trailing_commas(closed))
        except json.JSONDecodeError:
            continue
    raise ValueError("not repairable JSON")


def _scan(text):
    """Yield (index, char, in_string) for every character, string-aware."""
    in_string = escaped = False
    for index, char in enumerate(text):
        if in_string:
            yield index, char, True
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            yield index, char, True
            continue
        yield index, char, False


def _strip_comments(text: str) -> str:
    out, skip_until = [], -1
    for index, char, in_string in _scan(text):
        if index < skip_until:
            continue
        if not in_string and char == "/" and text[index + 1:index + 2] == "/":
            end = text.find("\n", index)
            skip_until = len(text) if end < 0 else end
            continue
        if not in_string and char == "/" and text[index + 1:index + 2] == "*":
            end = text.find("*/", index + 2)
            skip_until = len(text) if end < 0 else end + 2
            continue
        out.append(char)
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    out = []
    for _index, char, in_string in _scan(text):
        if not in_string and char in "}]":
            # Drop a comma (and the whitespace after it) right before a closer.
            tail = len(out)
            while tail and out[tail - 1].isspace():
                tail -= 1
            if tail and out[tail - 1] == ",":
                del out[tail - 1]
        out.append(char)
    return "".join(out)


_PY_LITERALS = {"True": "true", "False": "false", "None": "null"}


def _python_literals(text: str) -> str:
    out, word = [], []
    for _index, char, in_string in _scan(text + " "):
        if not in_string and (char.isalnum() or char == "_"):
            word.append(char)
            continue
        if word:
            token = "".join(word)
            out.append(_PY_LITERALS.get(token, token))
            word = []
        out.append(char)
    return "".join(out[:-1])


def _repair_at(text: str, exc: json.JSONDecodeError):
    """One local fix for the error json reported, or None."""
    message = exc.msg
    position = exc.pos
    if not text[position:].strip(" \t\r\n}]"):
        # The error is in the closing run: the brackets do not balance (a
        # model drops one `}` at the end of a long payload).
        balanced = _balance(text)
        if balanced != text:
            return balanced
    early = _closed_early(text, position)
    if early is not None:
        return early
    if message.startswith("Expecting ',' delimiter") and text[position:position + 1] in ("}", "]"):
        # One closer too many: `}}}}]}` where `}}}]}` closes the widget, so a
        # `}` meets the widget list. Drop the closer that does not match
        # what is open, and every section after it survives.
        stack = []
        for _index, char, in_string in _scan(text[:position]):
            if in_string:
                continue
            if char in "{[":
                stack.append(char)
            elif char in "}]" and stack:
                stack.pop()
        if stack and {"[": "}", "{": "]"}[stack[-1]] == text[position]:
            return text[:position] + text[position + 1:]
    if message.startswith("Expecting ',' delimiter") or message.startswith("Expecting ':' delimiter") \
            or message.startswith("Expecting property name"):
        # The usual cause: a string value whose closing quote is missing, so
        # the string swallowed the structure after it (`"> 95}}},{"type"`).
        opening = _last_string_start(text, position)
        if opening is not None and text[:opening].rstrip().endswith(":"):
            body_start = opening + 1
            for index in range(body_start, position):
                if text[index] in "}]," and text[index - 1] != "\\":
                    fixed = text[:index] + '"' + text[index:]
                    if fixed != text:
                        return fixed
    if message.startswith("Expecting ',' delimiter"):
        # Two values with no comma between them (`}{` or `"a" "b"`).
        return text[:position] + "," + text[position:]
    if message.startswith("Unterminated string"):
        end = text.find("\n", position)
        end = len(text) if end < 0 else end
        return text[:end] + '"' + text[end:]
    if message.startswith("Invalid control character"):
        return text[:position] + " " + text[position + 1:]
    if message.startswith("Extra data"):
        if text[position:].lstrip().startswith(","):
            # The document closed early -- a stray `}]` mid-reply -- and the
            # rest continues a list. Reopen it, one closer at a time, rather
            # than throw away every section after the slip.
            start = position
            while start > 0 and text[start - 1] in "}] \t\r\n":
                start -= 1
            closers = [text[i] for i in range(start, position) if text[i] in "}]"]
            for drop in range(1, len(closers) + 1):
                kept = "".join(closers[:len(closers) - drop])
                reopened = _balance(text[:start] + kept + text[position:])
                try:
                    json.loads(reopened)
                    return reopened
                except json.JSONDecodeError as later:
                    # The same slip often repeats further on: progress is
                    # enough, the repair loop takes the next one.
                    if later.pos > position + 1:
                        return reopened
        return text[:position]
    return None


_KEY_AHEAD_RE = re.compile(r'[\s,]*"[^"\\]*"\s*:')


def _closed_early(text: str, position: int):
    """`{"type": "X", "unit": "A"}, "bindings": {...}}` -- the model dropped
    `"properties": {` and so closed the widget one brace early; a key then
    follows where a value belongs. Removing that brace keeps the widget whole."""
    if not _KEY_AHEAD_RE.match(text, position):
        # json may report it one token later: it read `"bindings"` as the
        # next list item and then met the colon.
        if text[position:position + 1] != ":":
            return None
        opening = _last_string_start(text, position)
        if opening is None:
            return None
        position = opening
    back = position - 1
    while back >= 0 and text[back] in " \t\r\n,":
        back -= 1
    if back < 0 or text[back] != "}":
        return None
    # Only when the key would land in an array (a list of widgets), never
    # where a key is legal anyway.
    stack = []
    for _index, char, in_string in _scan(text[:back]):
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
        elif char in "}]" and stack:
            stack.pop()
    # stack[-1] is the object that brace closes; what holds it must be a list.
    if len(stack) < 2 or stack[-1] != "{" or stack[-2] != "[":
        return None
    # After dropping the brace the object stays open: the key belongs to it.
    return text[:back] + text[back + 1:]


def _last_string_start(text: str, position: int):
    """Index of the opening quote of the last string that began before *position*."""
    start, in_string, escaped = None, False, False
    for index, char in enumerate(text[:position]):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string, start = True, index
    return start


def _balance(text: str) -> str:
    """Insert the closers a payload is missing: before a closer that does not
    match the innermost opener, and at the end."""
    out, stack = [], []
    for _index, char, in_string in _scan(text):
        if not in_string and char in "{[":
            stack.append(char)
        elif not in_string and char in "}]":
            wanted = "{" if char == "}" else "["
            if wanted in stack:
                while stack and stack[-1] != wanted:
                    out.append("}" if stack.pop() == "{" else "]")
                stack.pop()
            else:
                continue                 # a stray closer: drop it
        out.append(char)
    out.extend("}" if opener == "{" else "]" for opener in reversed(stack))
    return "".join(out)


def _close_truncated(text: str):
    """Cut a truncated payload back to its last complete value and close it."""
    stack, last_good, in_string_end = [], None, False
    for index, char, in_string in _scan(text):
        in_string_end = in_string
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack:
                return None
            stack.pop()
            last_good = (index + 1, list(stack))
    if not stack and not in_string_end:
        return None
    if last_good is None:
        return None
    end, open_stack = last_good
    closers = "".join("}" if opener == "{" else "]" for opener in reversed(open_stack))
    return text[:end] + closers


# -- property synonyms -------------------------------------------------------

# Each group lists the spellings of one idea across the kit, in the order a
# target is preferred when a type declares more than one of them.
SYNONYM_GROUPS = (
    ("label", "title", "caption", "text", "name", "heading"),
    ("minimum", "minimumValue", "minValue", "min", "rangeMin", "lowerLimit"),
    ("maximum", "maximumValue", "maxValue", "max", "rangeMax", "upperLimit", "capacity"),
    ("unit", "units", "readoutUnit", "unitLabel", "suffix"),
    ("thresholdWarning", "warningValue", "valueWarning", "cautionValue", "cautionHigh",
     "warnAbove", "warningHigh", "warning", "warningThreshold", "warnHigh"),
    ("thresholdFault", "criticalValue", "valueFault", "faultHigh", "redlineFrom", "critical",
     "criticalThreshold", "fault", "alarmValue"),
    ("decimals", "decimalPlaces", "precision"),
    ("checked", "on", "active", "lit", "state"),
    ("onLabel", "onText", "trueText"),
    ("offLabel", "offText", "falseText"),
    ("options", "items", "choices", "modes", "gears"),
    ("currentIndex", "selectedIndex", "index"),
    ("description", "message", "body", "detail"),
    ("source", "src", "image", "imageSource", "url", "path", "file", "logo"),
)
_GROUP_OF = {}
for _group in SYNONYM_GROUPS:
    for _name in _group:
        _GROUP_OF.setdefault(_name.lower(), _group)


def normalise_properties(definition, properties: dict) -> tuple[dict, list]:
    """Rename the properties *definition* does not declare onto the synonym it does.

    Returns (properties, notes). Keys the type already declares are kept as
    they are; a synonym never overwrites a key the model set explicitly.
    Unknown keys with no synonym are left for the registry filter to drop.
    """
    if definition is None or not definition.properties:
        return dict(properties or {}), []
    declared = definition.properties
    lowered = {name.lower(): name for name in declared}
    result, notes = {}, []
    pending = []
    for key, value in (properties or {}).items():
        if key in declared:
            result[key] = value
        elif key.lower() in lowered:
            result[lowered[key.lower()]] = value
        else:
            pending.append((key, value))
    for key, value in pending:
        group = _GROUP_OF.get(key.lower())
        if not group:
            result[key] = value          # the registry filter decides
            continue
        target = next((name for name in group if name in declared and name not in result), None)
        if target is None:
            continue
        # A boolean idea mapped onto a non-boolean slot ("state" is a choice
        # on some faces) is not the same idea: leave it out.
        if declared.get(target) is bool and not isinstance(value, bool):
            continue
        result[target] = value
        notes.append(f"{definition.type}: {key} -> {target}")
    for key, value in list(result.items()):
        # A list where the widget takes text ("gears": ["P", "R", "N", "D"]
        # for "P,R,N,D") drew nothing at all.
        if isinstance(value, (list, tuple)) and declared.get(key) is str:
            result[key] = ",".join(str(item) for item in value)
            notes.append(f"{definition.type}: {key} list joined")
    if "icon" in result and "icon" in declared and isinstance(result["icon"], str):
        icon = kit_icon(result["icon"])
        if icon != result["icon"]:
            notes.append(f"{definition.type}: icon {result['icon']!r} -> {icon or 'default'}")
            if icon:
                result["icon"] = icon
            else:
                del result["icon"]
    return result, notes


def label_property(definition) -> str:
    """The property this type shows its caption in, or ''."""
    if definition is None:
        return ""
    for name in SYNONYM_GROUPS[0]:
        if name in definition.properties and definition.properties.get(name) in (str, None):
            return name
    for name in SYNONYM_GROUPS[0]:
        if name in definition.properties:
            return name
    return ""


_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def humanise(identifier: str) -> str:
    """``dischargePressure`` / ``mb.discharge_pressure`` -> ``Discharge pressure``."""
    text = str(identifier or "").split(".")[-1]
    words = _WORD_RE.findall(text.replace("_", " ").replace("-", " "))
    words = [w for w in words if w.lower() not in ("sh", "widget", "gauge", "tile", "readout", "display")] or words
    if not words:
        return ""
    phrase = " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in words)
    return phrase[:1].upper() + phrase[1:]


# -- icons --------------------------------------------------------------------
# hmi-ui draws `<kit>/icons/<name>.png`; a name that is not there draws a red
# box. Models reach for Material / FontAwesome names, so the common ones are
# mapped onto the kit's Tabler set and anything else falls back to the type's
# default icon.
ICON_ALIASES = {
    "thermometer": "temperature", "temp": "temperature", "heat": "flame", "fire": "flame",
    "water": "droplet", "drop": "droplet", "humidity": "droplet", "level": "droplet",
    "lightbulb": "bulb", "light": "bulb", "lamp": "bulb", "headlight": "bulb", "headlights": "bulb",
    "battery-full": "battery", "battery-warning": "battery-2", "battery-low": "battery-2",
    "charging": "battery-charging", "charging-station": "plug", "ev-station": "plug",
    "fuel": "gas-station", "gas": "gas-station", "speed": "gauge", "speedometer": "gauge",
    "warning": "alert-triangle", "alert": "alert-triangle", "error": "alert-circle",
    "fault": "alert-circle", "info": "info-circle", "ok": "circle-check", "success": "circle-check",
    "fan": "car-fan", "air": "wind", "ventilation": "wind", "cooling": "snowflake",
    "cold": "snowflake", "power-off": "power", "stop": "player-stop", "play": "player-play",
    "start": "player-play", "pump": "refresh", "motor": "engine", "valve": "adjustments",
    "seatbelt": "alert-circle", "door-open": "door", "parking-brake": "parking", "brake": "parking",
    "clock": "clock", "time": "clock", "settings": "settings", "gear": "settings", "cog": "settings",
    "home": "dashboard", "trip": "road", "distance": "road", "map": "road", "electric": "bolt",
    "bolt": "bolt", "voltage": "bolt", "current": "bolt", "pressure": "gauge", "flow": "wind",
    "file-text": "clipboard-text", "list": "list-tree", "history": "history", "chart": "activity",
    "trend": "activity", "sun": "sun", "night": "moon", "lock": "lock", "unlock": "lock-open",
}
_ICON_CACHE: dict = {}


def kit_icons() -> frozenset:
    """Names of the icons the kit ships (ui/qml/Shadcn/icons/*.png)."""
    cached = _ICON_CACHE.get("names")
    if cached is not None:
        return cached
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ui", "qml",
                                        "Shadcn", "icons"))
    try:
        names = frozenset(os.path.splitext(n)[0] for n in os.listdir(root) if n.endswith(".png"))
    except OSError:
        names = frozenset()
    _ICON_CACHE["names"] = names
    return names


def kit_icon(name) -> str:
    """The kit icon for *name*, or '' when there is none worth drawing."""
    names = kit_icons()
    key = str(name or "").strip().lower().replace("_", "-").replace(" ", "-")
    for prefix in ("mdi-", "fa-", "ti-", "icon-", "material-"):
        key = key.removeprefix(prefix)
    if not key:
        return ""
    if not names:
        return key                       # nothing to check against: trust it
    if key in names:
        return key
    alias = ICON_ALIASES.get(key)
    if alias in names:
        return alias
    for part in key.split("-"):
        alias = ICON_ALIASES.get(part, part)
        if alias in names:
            return alias
    return ""
