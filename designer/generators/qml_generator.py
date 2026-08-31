"""Deterministic .edsui -> QML backend; independent of designer widgets."""
from __future__ import annotations
import json
import os
import re
from typing import Any


POSITIONERS = ("Row", "Column", "Grid")


class QmlGenerationError(ValueError):
    pass


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_literal(item) for item in value) + "]"
    text = str(value)
    if re.fullmatch(r"(?:Image\.|Qt\.|Text\.|Grid\.)[A-Za-z0-9_.]+", text):
        return text
    return json.dumps(text, ensure_ascii=False)


class QmlGenerator:
    def __init__(self, registry):
        self.registry = registry

    def generate(self, project, project_dir: str = "", known_tags=None) -> dict[str, str]:
        issues = project.validate(self.registry, project_dir, known_tags)
        if issues:
            raise QmlGenerationError("\n".join(str(issue) for issue in issues))
        output = {}
        for page in project.pages:
            filename = f"{page.name.replace(' ', '') or page.id}.qml"
            output[filename] = self._page(project, page)
        return output

    def write(self, project, output_dir: str, project_dir: str = "", known_tags=None):
        generated = self.generate(project, project_dir, known_tags)
        os.makedirs(output_dir, exist_ok=True)
        for filename, content in generated.items():
            path = os.path.join(output_dir, filename)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        return [os.path.join(output_dir, name) for name in generated]

    def _page(self, project, page) -> str:
        lines = ["// Generated from .edsui; edit the source model, not this file.",
                 "import QtQuick 2.15", "import QtQuick.Controls 2.15", "import QtQuick.Layouts 1.15",
                 "import Shadcn 1.0", "", "Rectangle {", "    id: root",
                 f"    width: {project.screen.width}", f"    height: {project.screen.height}",
                 f"    color: {_literal(project.screen.background)}"]
        for widget in page.widgets:
            lines.extend(self._widget(widget, 1))
        lines.extend(["}", ""])
        return "\n".join(lines)

    def _widget(self, widget, depth, parent_type=""):
        definition = self.registry.get(widget.type)
        indent = "    " * depth
        lines = ["", f"{indent}{definition.qml_component} {{", f"{indent}    id: {widget.id}"]
        for key in ("x", "y", "width", "height"):
            # A positioner assigns its children's x/y; emitting them is noise.
            if key in ("x", "y") and parent_type in POSITIONERS:
                continue
            value = widget.geometry[key]
            value = int(value) if float(value).is_integer() else value
            lines.append(f"{indent}    {key}: {value}")
        if widget.z:
            lines.append(f"{indent}    z: {widget.z}")
        aliases = {("ShValueTile", "title"): "label", ("ShGauge", "minimum"): "minValue",
                   ("ShGauge", "maximum"): "maxValue", ("Text", "fontSize"): "font.pixelSize",
                   ("Text", "bold"): "font.bold", ("Rectangle", "borderColor"): "border.color",
                   ("Rectangle", "borderWidth"): "border.width", ("ShCard", "borderColor"): "border.color",
                   ("ShCard", "borderWidth"): "border.width", ("ShTabs", "tabs"): "model"}
        for key, value in widget.properties.items():
            if key in widget.bindings or value == "":
                continue
            qml_key = aliases.get((widget.type, key), key)
            if key == "source" and isinstance(value, str) and value.startswith("assets/"):
                value = "../" + value
            if widget.type == "ShTabs" and key == "tabs":
                # ShTabs takes tab titles as a list; authors type them as text.
                value = [part.strip() for part in str(value).split(",") if part.strip()]
                if not value:
                    continue
            lines.append(f"{indent}    {qml_key}: {_literal(value)}")
        for key, binding in widget.bindings.items():
            expression = f'Bus.value({_literal(binding.tag)}, 0)'
            if binding.multiplier != 1.0:
                expression = f"({expression} * {binding.multiplier})"
            if binding.offset:
                expression = f"({expression} + {binding.offset})"
            if binding.format:
                expression = f'{_literal(binding.format)}.arg({expression})'
            lines.append(f"{indent}    {key}: {expression}")
        for child in widget.children:
            lines.extend(self._widget(child, depth + 1, widget.type))
        lines.append(f"{indent}}}")
        return lines
