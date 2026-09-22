"""designer/code -- the code views of a design (the Studio's Code window).

The Studio draws a design; this package renders what the design *is* as
text: the QML the generator emits for a widget or a whole screen, and the
`.edsui` JSON fragment the widget or page is stored as. The Code window
(designer/ui/code_window.py) shows these next to a preview of the same
section and lets the design JSON be edited and applied back.
"""
from .code_model import (
    CodeError,
    CodeSection,
    page_edsui,
    page_qml,
    parse_page_edsui,
    parse_widget_edsui,
    section_for,
    widget_edsui,
    widget_qml,
)

__all__ = [
    "CodeError", "CodeSection", "page_edsui", "page_qml", "parse_page_edsui",
    "parse_widget_edsui", "section_for", "widget_edsui", "widget_qml",
]
