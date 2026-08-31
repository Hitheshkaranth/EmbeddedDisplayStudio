"""Framework-independent model and JSON persistence for ``*.edsui`` files."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
from typing import Any


ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
        return cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})


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
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["geometry"] = {
            key: int(value) if float(value).is_integer() else value
            for key, value in self.geometry.items()
        }
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
        return sorted({binding.tag for widget in self.all_widgets()
                       for binding in widget.bindings.values() if binding.tag})

    def validate(self, registry=None, project_dir: str = "", known_tags=None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if self.screen.width <= 0 or self.screen.height <= 0:
            issues.append(ValidationIssue("screen", "width and height must be positive"))
        seen: set[str] = set()
        known = set(known_tags) if known_tags is not None else None
        for page_index, page in enumerate(self.pages):
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
                    if os.path.isabs(normalized) or normalized.startswith(".."):
                        issues.append(ValidationIssue(path, "asset path must be project-relative"))
                    elif project_dir and not os.path.isfile(os.path.join(project_dir, normalized)):
                        issues.append(ValidationIssue(path, f"missing asset {source!r}"))
                for prop, binding in widget.bindings.items():
                    if not binding.tag:
                        issues.append(ValidationIssue(f"{path}.bindings.{prop}", "empty tag binding"))
                    elif known is not None and binding.tag not in known:
                        issues.append(ValidationIssue(f"{path}.bindings.{prop}", "tag is not defined"))
        return issues
