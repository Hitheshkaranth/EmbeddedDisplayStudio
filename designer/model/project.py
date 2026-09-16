"""Framework-independent model and JSON persistence for ``*.edsui`` files."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
import ntpath
import os
import re
from typing import Any


ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# CONTRACT 2.5: the dotted tag names a binding or an action may address.
TAG_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9_]+)+$")
# The comparison operators a threshold may use; the manifest's alarm entries
# (CONTRACT 4, "alarms") accept exactly this set, so a threshold the Designer
# accepts is one the panel's validator accepts. Two-character operators come
# first so ">=" is not read as ">" followed by "=5".
THRESHOLD_OPS = (">=", "<=", "!=", "==", ">", "<")
ACTION_KINDS = ("write", "pulse", "navigate")
# Pulse length limits, CONTRACT 2.2 ("ms": 1..10000).
PULSE_MS_MIN, PULSE_MS_MAX = 1, 10000


def parse_threshold(text):
    """Turn a binding threshold string into ``(op, number)``.

    Accepts ``> 80``, ``>= 80``, ``< 10``, ``<= 10``, ``== 1``, ``!= 0`` and a
    bare number, which means ``>=`` (the reading has reached the level).
    Whitespace is free. Returns None for an empty or unparseable string so a
    caller can treat "no threshold" and "nonsense" alike -- validate() is
    what reports the nonsense.
    """
    text = str(text or "").strip()
    if not text:
        return None
    op = ">="
    for candidate in THRESHOLD_OPS:
        if text.startswith(candidate):
            op, text = candidate, text[len(candidate):].strip()
            break
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return op, number


@dataclass
class DesignerBinding:
    tag: str
    format: str = ""
    multiplier: float = 1.0
    offset: float = 0.0
    unit: str = ""
    warning: str = ""
    critical: str = ""

    @classmethod
    def from_data(cls, value: Any) -> "DesignerBinding":
        if isinstance(value, str):
            return cls(tag=value)
        if not isinstance(value, dict):
            raise ValueError("binding must be a tag string or object")
        data = {k: value[k] for k in cls.__dataclass_fields__ if k in value}
        # The generator writes multiplier and offset straight into a QML
        # expression; a project file is untrusted input, so anything that is
        # not a number is rejected here rather than emitted as code.
        for key in ("multiplier", "offset"):
            if key in data:
                if isinstance(data[key], bool):
                    raise ValueError(f"binding {key} must be a number")
                try:
                    data[key] = float(data[key])   # "0.001" from a model's JSON is fine
                except (TypeError, ValueError):
                    raise ValueError(f"binding {key} must be a number") from None
        for key in ("tag", "format", "unit", "warning", "critical"):
            if key in data:
                data[key] = str(data[key])
        return cls(**data)


@dataclass
class DesignerAction:
    """What a widget does when one of its signals fires.

    kind   -- ``write``: ``Bus.write(tag, value)``; with ``value`` None the
              control's own state (checked / value / currentIndex) is sent.
              ``pulse``: ``Bus.pulse(tag, ms)``.
              ``navigate``: ask the page host to show ``page``.
    tag    -- dotted CONTRACT 2.5 tag for write / pulse.
    value  -- JSON scalar sent by ``write``; None means "the control's state".
    ms     -- pulse length in milliseconds, 1..10000.
    page   -- id of the page a ``navigate`` action shows.
    """
    kind: str = "write"
    tag: str = ""
    value: Any = None
    ms: int = 250
    page: str = ""

    @classmethod
    def from_data(cls, value: Any) -> "DesignerAction":
        if isinstance(value, str):
            return cls(kind="write", tag=value)
        if not isinstance(value, dict):
            raise ValueError("action must be a tag string or object")
        data = {k: value[k] for k in cls.__dataclass_fields__ if k in value}
        if "ms" in data:
            data["ms"] = int(data["ms"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        if self.kind == "navigate":
            data["page"] = self.page
        else:
            data["tag"] = self.tag
            if self.kind == "pulse":
                data["ms"] = int(self.ms)
            elif self.value is not None:
                data["value"] = self.value
        return data


@dataclass
class DesignerWidget:
    type: str
    id: str
    geometry: dict[str, float]
    properties: dict[str, Any] = field(default_factory=dict)
    bindings: dict[str, DesignerBinding] = field(default_factory=dict)
    children: list["DesignerWidget"] = field(default_factory=list)
    locked: bool = False
    z: int = 0
    # Keyed by the signal that fires the action ("clicked", "toggled", ...).
    actions: dict[str, DesignerAction] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesignerWidget":
        geometry = {key: float(data.get("geometry", {}).get(key, default)) for key, default in (
            ("x", 0), ("y", 0), ("width", 100), ("height", 40)
        )}
        return cls(
            type=str(data.get("type", "Rectangle")), id=str(data.get("id", "widget")),
            geometry=geometry, properties=dict(data.get("properties") or {}),
            bindings={k: DesignerBinding.from_data(v) for k, v in (data.get("bindings") or {}).items()},
            children=[cls.from_dict(item) for item in data.get("children", [])],
            locked=bool(data.get("locked", False)), z=int(data.get("z", 0)),
            actions={k: DesignerAction.from_data(v) for k, v in (data.get("actions") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["geometry"] = {
            key: int(value) if float(value).is_integer() else value
            for key, value in self.geometry.items()
        }
        # A widget with no actions serialises exactly as it did before actions
        # existed, so an untouched design does not change on disk.
        data.pop("actions", None)
        if self.actions:
            data["actions"] = {signal: action.to_dict() for signal, action in self.actions.items()}
        data["children"] = [child.to_dict() for child in self.children]
        return data

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class DesignerPage:
    id: str = "main"
    name: str = "Main"
    widgets: list[DesignerWidget] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesignerPage":
        return cls(str(data.get("id", "main")), str(data.get("name", "Main")),
                   [DesignerWidget.from_dict(item) for item in data.get("widgets", [])])

    def walk(self):
        for widget in self.widgets:
            yield from widget.walk()


@dataclass
class DesignerScreen:
    width: int = 1280
    height: int = 800
    background: str = "#101418"
    # The Shadcn colour mode this design assumes. It travels to the panel in
    # the manifest, because the app cannot set Theme.mode itself: the shell
    # assigns it after the Loader has already completed the app.
    theme: str = "dark"


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass
class DesignerProject:
    version: int = 1
    name: str = ""
    screen: DesignerScreen = field(default_factory=DesignerScreen)
    pages: list[DesignerPage] = field(default_factory=lambda: [DesignerPage()])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesignerProject":
        if not isinstance(data, dict):
            raise ValueError(".edsui root must be an object")
        if data.get("version", 1) != 1:
            raise ValueError(f"unsupported .edsui version {data.get('version')!r}")
        raw_screen = data.get("screen") or {}
        screen = DesignerScreen(
            int(raw_screen.get("width", 1280)), int(raw_screen.get("height", 800)),
            str(raw_screen.get("background", "#101418")),
            "light" if str(raw_screen.get("theme", "dark")) == "light" else "dark",
        )
        pages = [DesignerPage.from_dict(page) for page in data.get("pages", [])]
        return cls(1, str(data.get("name", "")).strip(), screen,
                   pages or [DesignerPage()])

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "name": self.name,
                "screen": asdict(self.screen),
                "pages": [{"id": p.id, "name": p.name,
                           "widgets": [w.to_dict() for w in p.widgets]} for p in self.pages]}

    @classmethod
    def load(cls, path: str) -> "DesignerProject":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(self.to_dict(), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)

    def all_widgets(self):
        for page in self.pages:
            yield from page.walk()

    def unique_id(self, base: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_]", "", base) or "widget"
        if base[0].isdigit():
            base = "widget" + base
        used = {widget.id for widget in self.all_widgets()}
        candidate, index = base, 2
        while candidate in used:
            candidate, index = f"{base}{index}", index + 1
        return candidate

    def required_tags(self) -> list[str]:
        """Every tag the generated app reads or writes -- bindings and actions."""
        # "*" is the alarm table's "every alarm" wildcard, not a tag.
        tags = {binding.tag for widget in self.all_widgets()
                for binding in widget.bindings.values() if binding.tag and binding.tag != "*"}
        tags |= {action.tag for widget in self.all_widgets()
                 for action in widget.actions.values()
                 if action.kind in ("write", "pulse") and action.tag}
        return sorted(tags)

    def alarms(self) -> list[dict[str, Any]]:
        """Manifest ``alarms`` entries derived from binding thresholds.

        One entry per tag, in the shape the panel's validator accepts
        (CONTRACT 4): ``{"tag", "label", "unit"?, "warning"?, "critical"?}``.
        The label is the widget's own caption -- ``label``, ``title`` or
        ``text`` -- so the alarm reads the way the screen does; the first
        widget bound to a tag wins when several carry thresholds for it.
        """
        entries: dict[str, dict[str, Any]] = {}
        for widget in self.all_widgets():
            for binding in widget.bindings.values():
                if not binding.tag or binding.tag in entries:
                    continue
                warning = parse_threshold(binding.warning)
                critical = parse_threshold(binding.critical)
                if not (warning or critical):
                    continue
                label = next((str(widget.properties[key]) for key in ("label", "title", "text")
                              if widget.properties.get(key)), binding.tag)
                entry: dict[str, Any] = {"tag": binding.tag, "label": label}
                if binding.unit:
                    entry["unit"] = binding.unit
                if warning:
                    entry["warning"] = {"op": warning[0], "value": warning[1]}
                if critical:
                    entry["critical"] = {"op": critical[0], "value": critical[1]}
                entries[binding.tag] = entry
        return list(entries.values())

    def validate(self, registry=None, project_dir: str = "", known_tags=None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if self.screen.width <= 0 or self.screen.height <= 0:
            issues.append(ValidationIssue("screen", "width and height must be positive"))
        seen: set[str] = set()
        known = set(known_tags) if known_tags is not None else None
        page_ids = {page.id for page in self.pages}
        seen_pages: set[str] = set()
        seen_stems: set[str] = set()
        for page_index, page in enumerate(self.pages):
            ppath = f"pages[{page_index}]"
            # The id keys the host's page table and the name becomes the
            # page's QML file name, so both must be plain identifiers.
            if not ID_RE.fullmatch(page.id):
                issues.append(ValidationIssue(ppath, "invalid page id"))
            if page.id in seen_pages:
                issues.append(ValidationIssue(ppath, "duplicate page id"))
            seen_pages.add(page.id)
            # The name becomes the page's file name with everything but
            # [A-Za-z0-9_] dropped; "Main - Overview" is fine, two names that
            # collapse to the same stem are not.
            stem = re.sub(r"[^A-Za-z0-9_]", "", page.name) or page.id
            if stem in seen_stems:
                issues.append(ValidationIssue(ppath, f"page name {page.name!r} collides with another page's file name"))
            seen_stems.add(stem)
            for widget in page.walk():
                path = f"pages[{page_index}].{widget.id}"
                if not ID_RE.fullmatch(widget.id):
                    issues.append(ValidationIssue(path, "invalid QML id"))
                if widget.id in seen:
                    issues.append(ValidationIssue(path, "duplicate widget id"))
                seen.add(widget.id)
                if registry is not None and registry.get(widget.type) is None:
                    issues.append(ValidationIssue(path, f"unsupported component {widget.type!r}"))
                if widget.geometry.get("width", 0) <= 0 or widget.geometry.get("height", 0) <= 0:
                    issues.append(ValidationIssue(path, "width and height must be positive"))
                source = widget.properties.get("source")
                if source:
                    normalized = os.path.normpath(str(source))
                    # A design is portable between the Windows Studio and a
                    # Linux panel. os.path.isabs() only recognises the host's
                    # path syntax, so Linux previously accepted C:/private as
                    # a project-relative asset.
                    if (os.path.isabs(normalized)
                            or ntpath.isabs(str(source))
                            or normalized.startswith("..")):
                        issues.append(ValidationIssue(path, "asset path must be project-relative"))
                    elif project_dir and not os.path.isfile(os.path.join(project_dir, normalized)):
                        issues.append(ValidationIssue(path, f"missing asset {source!r}"))
                for prop, binding in widget.bindings.items():
                    for name in ("multiplier", "offset"):
                        if not math.isfinite(getattr(binding, name)):
                            issues.append(ValidationIssue(f"{path}.bindings.{prop}", f"{name} must be finite"))
                    if not binding.tag:
                        issues.append(ValidationIssue(f"{path}.bindings.{prop}", "empty tag binding"))
                    elif known is not None and binding.tag not in known:
                        issues.append(ValidationIssue(f"{path}.bindings.{prop}", "tag is not defined"))
                    for name, text in (("warning", binding.warning), ("critical", binding.critical)):
                        if text and parse_threshold(text) is None:
                            issues.append(ValidationIssue(f"{path}.bindings.{prop}",
                                                          f"{name} threshold {text!r} is not '<op> <number>'"))
                definition = registry.get(widget.type) if registry is not None else None
                for signal, action in widget.actions.items():
                    apath = f"{path}.actions.{signal}"
                    if definition is not None and signal not in definition.action_signals:
                        issues.append(ValidationIssue(apath, f"{widget.type} has no action signal {signal!r}"))
                    if action.kind not in ACTION_KINDS:
                        issues.append(ValidationIssue(apath, f"unknown action kind {action.kind!r}"))
                    elif action.kind == "navigate":
                        if action.page not in page_ids:
                            issues.append(ValidationIssue(apath, f"navigate target page {action.page!r} does not exist"))
                    elif signal == "alarmActivated":
                        pass  # the table supplies the alarm; the action acknowledges it
                    else:
                        if not TAG_RE.fullmatch(action.tag or ""):
                            issues.append(ValidationIssue(apath, f"action tag {action.tag!r} is not a dotted tag name"))
                        if action.kind == "pulse" and not (PULSE_MS_MIN <= int(action.ms) <= PULSE_MS_MAX):
                            issues.append(ValidationIssue(apath, f"pulse ms must be {PULSE_MS_MIN}..{PULSE_MS_MAX}"))
        return issues
