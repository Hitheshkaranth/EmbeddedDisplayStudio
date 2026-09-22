"""designer/preview -- the Studio's previews drawn by the panel's own renderer.

`native_renderer.NativeRenderer` runs the headless `hmi-ui` binary (the C +
LVGL runtime that draws the panel) to render a widget or a whole page to an
image, so what the Studio shows in the Designer canvas, the bezel and the
Code section is what the glass will show, pixel for pixel. The Qt/QML
renderer (designer/canvas/qml_previews.py) remains the fallback where no
binary is available.
"""
from .native_renderer import NativeRenderer, find_hmi_ui, kit_dir

__all__ = ["NativeRenderer", "find_hmi_ui", "kit_dir"]
