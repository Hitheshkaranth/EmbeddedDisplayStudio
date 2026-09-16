"""Design presets — matched from the AI brief to append exemplar layouts.

Each preset bundles a hand-built ``.edsui`` template and a short style
guide.  When the brief matches a preset, its rules and a compact exemplar
are appended to the system prompt so the model composes in the same idiom.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Directory that holds this module so we can find templates relative to it.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_DIR = _ROOT / "designer" / "templates"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DesignPreset:
    """A design preset that maps a brief keyword to a template and style."""
    id: str            # e.g. "automotive-cluster"
    name: str          # e.g. "Automotive cluster"
    keywords: tuple    # lower-case words/phrases that select it
    template: str      # absolute path to the .edsui
    style: str         # composition rules for the model, <= 1200 characters


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------
def _templates_dir() -> Path:
    _dir = _TEMPLATES_DIR
    if not _dir.is_dir():
        _dir.mkdir(parents=True, exist_ok=True)
    return _dir


def _preset_file(name: str) -> str:
    return str(_templates_dir() / name)


def presets() -> tuple[DesignPreset, ...]:
    """Return every registered design preset."""
    tmpl_dir = _templates_dir()

    cluster_style = (
        "Palette: background #0b0f16, panels #141c28 with #22304a borders, "
        "accent #22a8ff, redline #ff2d55, text #ffffff, captions #8a97a8. "
        "Hierarchy: one hero gauge >= 45 % of screen height, secondary readouts "
        "at <= 25 % of its size, captions <= 14 px. Grouping: centre-left-right "
        "columns, aligned baselines, 24 px gutters, nothing within 40 px of the "
        "bezel. Use ShClusterGauge for speed/rpm/current, ShAutoLevel for "
        "fuel/temperature, ShTelltale for lamps, ShIconTile for menus, "
        "ShTripInfo for distance tables, ShSegmentBar for battery SOC, "
        "ShVehicleStatus for tyre pressures. Every value binds a tag; units on "
        "every readout; set red zones and thresholds."
    )

    ev_style = (
        "Palette: background #070b14, panels #141c28 with #22304a borders, "
        "accent #22a8ff, green #2fe07f, redline #ff2d55, text #ffffff, "
        "captions #8a97a8. Hierarchy: dual round gauges side by side as heroes, "
        "big numeric readouts in the centre, secondary cards below. Grouping: "
        "top bar, centre row with gauges + gear + tyre status, card row with "
        "trip/SOC/ODO, icon tile row. Use ShClusterGauge for speed/rpm/current, "
        "ShSegmentBar for battery SOC, ShAutoReadout for trip/odo, "
        "ShVehicleStatus for tyre pressures, ShIconTile for app menus, "
        "ShTelltale for status lamps. Bind live values; red zones for low SOC "
        "and tyre pressure."
    )

    return (
        DesignPreset(
            id="automotive-cluster",
            name="Automotive cluster",
            keywords=(
                "automotive", "cluster", "car", "vehicle", "dashboard",
                "speedometer", "tachometer", "rpm", "instrument cluster",
                "fuel", "gear", "odometer", "drive mode",
            ),
            template=_preset_file("automotive_cluster.edsui"),
            style=cluster_style,
        ),
        DesignPreset(
            id="ev-infotainment",
            name="EV infotainment cluster",
            keywords=(
                "ev", "electric", "infotainment", "soc", "battery",
                "tyre", "tire", "tpms", "carplay", "android auto", "media",
                "apps", "range", "charging",
            ),
            template=_preset_file("ev_infotainment.edsui"),
            style=ev_style,
        ),
    )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
def get_preset(preset_id: str) -> DesignPreset:
    """Return the preset with the given id.  Raises KeyError when unknown."""
    for p in presets():
        if p.id == preset_id:
            return p
    raise KeyError(preset_id)


def match_preset(brief: str) -> DesignPreset | None:
    """Return the preset whose keywords best match *brief* (lowest count of
    missing keywords), or None when no keyword matches at all."""
    if not brief:
        return None
    lower = brief.lower()
    best: DesignPreset | None = None
    best_score = float("inf")
    for preset in presets():
        missing = sum(1 for kw in preset.keywords if kw not in lower)
        if missing < best_score:
            best_score = missing
            best = preset
    # best_score < len(preset.keywords) means at least one keyword matched.
    if best is not None and best_score < len(best.keywords):
        return best
    return None


# ---------------------------------------------------------------------------
# Template loading & validation
# ---------------------------------------------------------------------------
def load_template(preset: DesignPreset) -> "DesignerProject":
    """Load and return the DesignerProject described by *preset*."""
    from designer.model.project import DesignerProject
    return DesignerProject.load(preset.template)


def _validate_template(preset: DesignPreset, registry) -> list[str]:
    """Validate the template against *registry*, return list of issue strings."""
    from designer.model.project import DesignerProject
    project = DesignerProject.load(preset.template)
    issues = project.validate(registry)
    return [str(issue) for issue in issues]


# ---------------------------------------------------------------------------
# Prompt section
# ---------------------------------------------------------------------------
def prompt_section(preset: DesignPreset, screen_width: int, screen_height: int) -> str:
    """Return the preset block appended to the system prompt.

    Format::

        Design preset: <name>
        <style>

        Exemplar (a section of a finished design at <w>x<h>):
        ```json
        { ... first page widgets scaled to w x h ... }
        ```
    """
    project = load_template(preset)
    page = project.pages[0] if project.pages else None
    if page is None:
        return (
            f"Design preset: {preset.name}\n\n{preset.style}\n\n"
            f"Exemplar (a section of a finished design at {screen_width}x{screen_height}):\n"
            f"```\nnull\n```"
        )

    # Compute scale factors from template screen to target.
    tw = project.screen.width or 1
    th = project.screen.height or 1
    sx = screen_width / tw
    sy = screen_height / th

    # Build exemplar widgets (at most 8 top-level widgets from the page).
    scaled_widgets = []
    for w in page.widgets[:8]:
        geo = w.geometry
        scaled_geo = {
            "x": round(geo.get("x", 0) * sx),
            "y": round(geo.get("y", 0) * sy),
            "width": round(geo.get("width", 100) * sx),
            "height": round(geo.get("height", 40) * sy),
        }
        props = {k: v for k, v in w.properties.items() if k not in ("opacity", "visible")}
        scaled_widgets.append({
            "type": w.type,
            "id": w.id,
            "geometry": scaled_geo,
            "properties": props,
        })

    # Build the exemplar section object (same shape build_system_prompt expects).
    exemplar = {
        "name": preset.name,
        "section": {"index": 1, "complete": False, "label": preset.name, "next": ""},
        "pages": [{
            "id": page.id,
            "name": page.name,
            "widgets": scaled_widgets,
        }],
    }
    exemplar_json = json.dumps(exemplar, indent=2, ensure_ascii=False)

    section = (
        f"Design preset: {preset.name}\n\n"
        f"{preset.style}\n\n"
        f"Exemplar (a section of a finished design at {screen_width}x{screen_height}):\n"
        f"```json\n{exemplar_json}\n```"
    )
    # Guard the 6000-character limit.
    if len(section) > 5900:
        section = (
            f"Design preset: {preset.name}\n\n"
            f"{preset.style}\n\n"
            f"Exemplar (a section of a finished design at {screen_width}x{screen_height}):\n"
            f"```json\n{exemplar_json[:2000]}\n```"
        )
    return section


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli_list():
    """Print id<TAB>name<TAB>keywords for every preset."""
    for p in presets():
        print(f"{p.id}\t{p.name}\t{', '.join(p.keywords)}")


def _cli_write(preset_id: str, out_dir: str):
    """Validate the template and write generated QML to *out_dir*."""
    from designer.generators import QmlGenerator
    from designer.palette.widget_registry import default_registry

    try:
        preset = get_preset(preset_id)
    except KeyError:
        print(f"unknown preset: {preset_id!r}", file=sys.stderr)
        sys.exit(1)

    registry = default_registry()
    project = load_template(preset)
    issues = project.validate(registry)
    if issues:
        for issue in issues:
            print(str(issue), file=sys.stderr)
        sys.exit(1)

    generator = QmlGenerator(registry)
    generator.write(project, out_dir)
    print(f"Wrote generated QML to {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Design presets CLI")
    parser.add_argument("--list", action="store_true", help="List available presets")
    parser.add_argument("--write", nargs=2, metavar=("ID", "OUT_DIR"), help="Validate and write QML for a preset")
    args = parser.parse_args()

    if args.list:
        _cli_list()
    elif args.write:
        _cli_write(args.write[0], args.write[1])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()