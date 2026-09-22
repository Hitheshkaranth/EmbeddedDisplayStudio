"""designer/preview/native_renderer.py -- previews rendered by hmi-ui.

FROZEN CONTRACT (native previews swarm, 2026-09-22). Owner: W2. Public
names, signatures, signals and attributes below are the contract; W2 fills
the bodies and may add private helpers.

The renderer is a drop-in for designer/canvas/qml_previews.QmlPreviewRenderer
(same `image_for` / `ready` / `clear` / `enabled` surface, same
`preview_key` from that module) so the Designer scene and the Code section
can hold either. It runs the headless hmi-ui binary as a child process
(never in-process) per render, a few at a time, and caches by key.

How a render is made (both scopes go through a temporary bundle directory
holding a one-page project.edsui, so containers with children and pages
render exactly as on the panel):
    hmi-ui --apps-dir <tmp> --headless <tmp>/out.png --kit <kit> --theme <theme>
The temporary project's screen is width x height, background `background`,
theme `theme`; a widget render places a copy of the widget at 0,0 with its
bindings and actions stripped (a still of the design, like the QML
renderer) and its properties as they are. The PNG is loaded into a QImage
(ARGB32), scaled by `scale` with smooth transformation when scale != 1.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

# Where hmi-ui's headless binary is looked for, in order:
#   $HMI_UI_BIN; a frozen Studio's bundle dir (sys._MEIPASS)/hmi-ui/hmi-ui[.exe];
#   <repo>/native/hmi-ui/out/win64/hmi-ui.exe on Windows,
#   <repo>/native/hmi-ui/out/hmi-ui elsewhere.
def find_hmi_ui() -> str | None:
    """Absolute path of a usable hmi-ui binary (exists and is executable), or None."""
    raise NotImplementedError


def kit_dir() -> str:
    """The kit directory hmi-ui renders with (ui/qml/Shadcn: fonts/ and icons/),
    in the repository or in a frozen Studio's bundle."""
    raise NotImplementedError


class NativeRenderer(QObject):
    """Renders design sections with hmi-ui, one child process per render.

    Signals:
        ready(str): a render for this key has landed; repaint what uses it.
        failed(str, str): (key, message) when hmi-ui could not render it.

    Attributes:
        enabled: False makes image_for return None without scheduling.
        available: True when a binary was found at construction.
        binary: the path used (or None).
        background: the screen colour behind a widget render ('#rrggbb');
            the workspace sets it to the design's screen background.
        parallel: how many child processes may run at once (default 2).
    """

    ready = Signal(str)
    failed = Signal(str, str)

    def __init__(self, binary: str | None = None, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    # ----------------------------------------------------------------- API

    def image_for(self, widget, width, height, theme, scale=1.0):
        """The cached render, or None -- in which case one is scheduled and
        `ready` fires with `preview_key(widget, width, height, theme, scale)`
        when it lands. Same contract as QmlPreviewRenderer.image_for."""
        raise NotImplementedError

    def page_image_for(self, project, page, theme, scale=1.0):
        """The cached render of the whole page at the project's screen size,
        or None with a render scheduled; `ready` fires with `page_key(project,
        page, theme, scale)`."""
        raise NotImplementedError

    def render_page_sync(self, project, page, theme, timeout_ms: int = 10000):
        """Blocking render of a page (bezel, tests): a QImage, or None on failure."""
        raise NotImplementedError

    def render_widget_sync(self, widget, width, height, theme, timeout_ms: int = 10000):
        """Blocking render of one widget: a QImage, or None on failure."""
        raise NotImplementedError

    def clear(self) -> None:
        """Drops the cache and the queue (running renders finish and are discarded)."""
        raise NotImplementedError

    def shutdown(self) -> None:
        """Kills running child processes; call before the Studio exits."""
        raise NotImplementedError


def page_key(project, page, theme, scale=1.0) -> str:
    """Cache key for a page render: covers the screen geometry/background,
    the theme, the scale and the full content of the page's widgets."""
    raise NotImplementedError
