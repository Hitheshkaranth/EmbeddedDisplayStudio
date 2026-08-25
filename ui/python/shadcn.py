"""
Shadcn/UI design system port for Qt.
Provides helpers for the Qt Widgets side, loading ui/tokens.json.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Union, Any

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor, QIcon, QFont, QPalette, QPixmap, QPainter
except ImportError:
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QColor, QIcon, QFont, QPalette, QPixmap, QPainter
    except ImportError:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QColor, QIcon, QFont, QPalette, QPixmap, QPainter

logger = logging.getLogger(__name__)

FONT_STACK = ('Inter', 'Noto Sans', 'DejaVu Sans', 'sans-serif')

_tokens_cache = None

def load_tokens(path: str = None) -> dict:
    """
    Load and return the parsed tokens.json.
    
    Default path resolves to ui/tokens.json relative to this file's location.
    Caches the result. Raises FileNotFoundError with a descriptive message if missing.
    
    Args:
        path (str, optional): Custom path to tokens.json. Defaults to None.
        
    Returns:
        dict: The parsed tokens data.
        
    Raises:
        FileNotFoundError: If tokens.json does not exist.
    """
    global _tokens_cache
    if _tokens_cache is not None and path is None:
        return _tokens_cache
        
    if path is None:
        base_dir = Path(__file__).resolve().parent.parent
        tokens_path = base_dir / "tokens.json"
    else:
        tokens_path = Path(path)
        
    if not tokens_path.exists():
        raise FileNotFoundError(f"tokens.json not found at {tokens_path}. Ensure it exists.")
        
    with open(tokens_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if path is None:
        _tokens_cache = data
        
    return data

def color(name: str, theme: str = 'light') -> str:
    """
    Return the hex colour string for the given token name in the given theme.
    
    Args:
        name (str): The token name (e.g., 'primary', 'background').
        theme (str): 'light' or 'dark'. Defaults to 'light'.
        
    Returns:
        str: The hex colour string.
        
    Raises:
        KeyError: If the theme or token name is unknown.
    """
    if theme not in ('light', 'dark'):
        raise KeyError(f"Unknown theme: '{theme}'. Must be 'light' or 'dark'.")
        
    tokens = load_tokens()
    palettes = tokens.get("palettes", {})
    theme_palette = palettes.get(theme, {})
    
    if name not in theme_palette:
        raise KeyError(f"Unknown colour token: '{name}' in theme '{theme}'.")
        
    return theme_palette[name]

def qss(theme: str = 'light') -> str:
    """
    Generate and return the complete Qt stylesheet string for the given theme.
    
    This stylesheet covers QWidget, QMainWindow, QPushButton, QLineEdit, 
    QComboBox, QLabel, QGroupBox, QPlainTextEdit, QTextEdit, QTabWidget, 
    QTabBar, QProgressBar, QCheckBox, QRadioButton, QListWidget, QTreeView, 
    QToolTip, QMenu, QScrollBar, QSplitter, and QStatusBar.
    
    Args:
        theme (str): 'light' or 'dark'. Defaults to 'light'.
        
    Returns:
        str: The generated QSS string.
    """
    t = load_tokens()
    p = t['palettes'][theme]
    r = t['radii']
    sizes = t['typography']['sizes']
    scale = t['spacing']['scale']
    
    def hex_to_rgba(hex_str: str, alpha: float) -> str:
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 6:
            r_val = int(hex_str[0:2], 16)
            g_val = int(hex_str[2:4], 16)
            b_val = int(hex_str[4:6], 16)
            return f"rgba({r_val}, {g_val}, {b_val}, {alpha})"
        return "#" + hex_str
        
    return f"""
/* ========================================================================
   QWidget & Base
   ======================================================================== */
QWidget {{
    background-color: {p['background']};
    color: {p['foreground']};
    font-family: "{FONT_STACK[0]}", "{FONT_STACK[1]}", "{FONT_STACK[2]}", "{FONT_STACK[3]}";
    font-size: {sizes['base']}px;
}}

/* ========================================================================
   QMainWindow
   ======================================================================== */
QMainWindow {{
    background-color: {p['background']};
}}

/* ========================================================================
   QPushButton
   ======================================================================== */
QPushButton {{
    background-color: {p['primary']};
    color: {p['primaryForeground']};
    border: 1px solid transparent;
    border-radius: {r['md']}px;
    padding: {scale[1]}px {scale[3]}px;
    height: 36px;
}}
QPushButton:hover {{
    background-color: {hex_to_rgba(p['primary'], 0.9)};
}}
QPushButton:pressed {{
    background-color: {hex_to_rgba(p['primary'], 0.8)};
}}
QPushButton:disabled {{
    background-color: {hex_to_rgba(p['primary'], 0.5)};
    color: {hex_to_rgba(p['primaryForeground'], 0.5)};
}}
QPushButton[deploymentAction="true"] {{
    min-height: 28px;
    max-height: 28px;
    padding-top: 2px;
    padding-bottom: 2px;
}}

QPushButton[variant="secondary"] {{
    background-color: {p['secondary']};
    color: {p['secondaryForeground']};
}}
QPushButton[variant="secondary"]:hover {{
    background-color: {hex_to_rgba(p['secondary'], 0.8)};
}}

QPushButton[variant="destructive"] {{
    background-color: {p['destructive']};
    color: {p['destructiveForeground']};
}}
QPushButton[variant="destructive"]:hover {{
    background-color: {hex_to_rgba(p['destructive'], 0.9)};
}}

QPushButton[variant="outline"] {{
    background-color: transparent;
    color: {p['foreground']};
    border: 1px solid {p['border']};
}}
QPushButton[variant="outline"]:hover {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
}}
/* An outline button's own transparent background overrides the base
   QPushButton:pressed rule, so without these it was the one variant that
   looked identical whether or not it had been clicked. */
QPushButton[variant="outline"]:pressed {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
    border-color: {p['ring']};
}}
/* Held for as long as the action is actually running, not just while the
   mouse is down: a click that starts a multi-second remote command has to
   stay visibly engaged after the button is released. */
QPushButton[variant="outline"][busy="true"] {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
    border: 2px solid {p['ring']};
}}
QPushButton[variant="outline"][busy="true"]:disabled {{
    background-color: {p['accent']};
    color: {hex_to_rgba(p['accentForeground'], 0.7)};
    border: 2px solid {p['ring']};
}}

QPushButton[variant="ghost"] {{
    background-color: transparent;
    color: {p['foreground']};
    border: 1px solid transparent;
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
}}

/* ========================================================================
   QLineEdit
   ======================================================================== */
QLineEdit {{
    height: 36px;
    background-color: transparent;
    border: 1px solid {p['input']};
    border-radius: {r['md']}px;
    padding: {scale[1]}px {scale[2]}px;
    color: {p['foreground']};
}}
QLineEdit:focus {{
    border: 2px solid {p['ring']};
}}
QLineEdit::placeholder {{
    color: {p['mutedForeground']};
}}

/* ========================================================================
   QComboBox
   ======================================================================== */
QComboBox {{
    height: 36px;
    background-color: transparent;
    border: 1px solid {p['input']};
    border-radius: {r['md']}px;
    padding: {scale[1]}px {scale[2]}px;
    color: {p['foreground']};
}}
QComboBox:focus {{
    border: 2px solid {p['ring']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    width: 12px;
    height: 12px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['popover']};
    color: {p['popoverForeground']};
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
    selection-background-color: {p['accent']};
    selection-color: {p['accentForeground']};
}}

/* ========================================================================
   QLabel
   ======================================================================== */
QLabel {{
    color: {p['foreground']};
    background-color: transparent;
}}

/* ========================================================================
   QGroupBox (Card)
   ======================================================================== */
QGroupBox {{
    background-color: {p['card']};
    color: {p['cardForeground']};
    border: 1px solid {p['border']};
    border-radius: {r['xl']}px;
    margin-top: {scale[4]}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 {scale[3]}px;
    margin-top: {scale[2]}px;
    font-weight: 600;
}}

/* ========================================================================
   QPlainTextEdit, QTextEdit
   ======================================================================== */
QPlainTextEdit, QTextEdit {{
    background-color: {p['muted']};
    color: {p['mutedForeground']};
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
    font-family: monospace;
    padding: {scale[2]}px;
}}
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {p['ring']};
}}

/* ========================================================================
   QTabWidget, QTabBar
   ======================================================================== */
QTabWidget::pane {{
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
}}
QTabBar {{
    background-color: {p['muted']};
    border-radius: {r['md']}px;
    padding: 4px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {p['mutedForeground']};
    padding: 6px 12px;
    border-radius: {r['sm']}px;
}}
QTabBar::tab:selected {{
    background-color: {p['background']};
    color: {p['foreground']};
}}
QTabBar::tab:hover:!selected {{
    background-color: {hex_to_rgba(p['foreground'], 0.05)};
}}

/* ========================================================================
   QProgressBar
   ======================================================================== */
QProgressBar {{
    background-color: {p['secondary']};
    border: none;
    border-radius: {r['full']}px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {p['primary']};
    border-radius: {r['full']}px;
}}
QProgressBar#deploymentProgressBar {{
    background-color: {p['background']};
    border: 1px solid {p['accent']};
    border-radius: 6px;
    min-height: 10px;
    max-height: 10px;
    color: transparent;
}}
QProgressBar#deploymentProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {p['primary']}, stop:1 {p['ring']});
    border-radius: 5px;
}}
/* The capacity bars on System Profile state a measurement, so they are sized
   to be read and share the deploy bar's chunk. Anything else makes the one
   tab that reports numbers the one tab that does not look like the product. */
QProgressBar#profileCapacityBar {{
    background-color: {p['muted']};
    border: 1px solid {p['input']};
    border-radius: 6px;
    min-height: 10px;
    max-height: 10px;
    color: transparent;
}}
/* Brand blue, not `primary`: in the light palette primary and ring are both
   near-black, which drew a black chunk that swallowed the reading painted on
   top of it. The measurement now sits beside the bar (profileBarValue). */
QProgressBar#profileCapacityBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {p['brand']}, stop:1 {p['info']});
    border-radius: 5px;
}}
QLabel#profileBarValue {{
    color: {p['mutedForeground']};
    font-size: 11px;
    font-weight: 600;
}}

/* ========================================================================
   QCheckBox, QRadioButton
   ======================================================================== */
QCheckBox, QRadioButton {{
    color: {p['foreground']};
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p['primary']};
    border-radius: {r['sm']}px;
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {p['primary']};
}}
QCheckBox::indicator:unchecked, QRadioButton::indicator:unchecked {{
    background-color: transparent;
}}

/* ========================================================================
   QListWidget, QTreeView
   ======================================================================== */
QListWidget, QTreeView {{
    background-color: {p['background']};
    color: {p['foreground']};
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
    alternate-background-color: {p['muted']};
}}
QListWidget::item, QTreeView::item {{
    padding: 4px;
    border-radius: {r['sm']}px;
}}
QListWidget::item:selected, QTreeView::item:selected {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
}}
QListWidget::item:hover:!selected, QTreeView::item:hover:!selected {{
    background-color: {hex_to_rgba(p['accent'], 0.5)};
}}

/* ========================================================================
   QToolTip
   ======================================================================== */
QToolTip {{
    background-color: {p['popover']};
    color: {p['popoverForeground']};
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
    padding: 4px 8px;
}}

/* ========================================================================
   QMenu
   ======================================================================== */
QMenu {{
    background-color: {p['popover']};
    color: {p['popoverForeground']};
    border: 1px solid {p['border']};
    border-radius: {r['md']}px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 12px;
    border-radius: {r['sm']}px;
}}
QMenu::item:selected {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
}}

/* ========================================================================
   QScrollBar
   ======================================================================== */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    width: 8px;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p['mutedForeground']};
    border-radius: 4px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    border: none;
    background: none;
    width: 0px;
    height: 0px;
}}

/* ========================================================================
   QSplitter
   ======================================================================== */
QSplitter::handle {{
    background-color: {p['border']};
    width: 1px;
    height: 1px;
}}

/* ========================================================================
   QStatusBar
   ======================================================================== */
QStatusBar {{
    background-color: {p['muted']};
    color: {p['mutedForeground']};
    border-top: 1px solid {p['border']};
}}

/* ========================================================================
   EmbeddedDisplay Studio console skin
   ======================================================================== */
QWidget#previewPanel {{
    background-color: {p['card']};
    border: 1px solid transparent;
    border-radius: {r['md']}px;
    padding: 12px;
}}
QWidget#devicePanel {{ background-color: transparent; border: none; }}
QLabel#studioMark {{
    background-color: {p['card']};
    border: 1px solid {p['border']};
    border-radius: {r['lg']}px;
    padding: 1px;
}}
QLabel#productTitle {{
    font-size: 17px;
    font-weight: 700;
    color: {p['foreground']};
}}
QWidget#deployConsolePage {{ background-color: transparent; }}
QWidget#deploymentProgressSlot {{ background-color: transparent; }}
QLabel#consolePageTitle {{
    color: {p['foreground']};
    font-size: 20px;
    font-weight: 700;
}}
QLabel#consolePageSubtitle {{
    color: {p['mutedForeground']};
    font-size: 12px;
}}
QLabel#sectionIcon {{
    background-color: {p['muted']};
    border-radius: 10px;
}}
/* The page title's mark, one step up from a section's: same treatment, sized
   to sit against 20px type rather than 14px. */
QLabel#pageTitleIcon {{
    background-color: {p['muted']};
    border-radius: 13px;
}}
QLabel#sectionTitle {{
    color: {p['foreground']};
    font-size: 14px;
    font-weight: 700;
}}
QGroupBox[class="consoleSectionPanel"] {{
    background-color: {p['secondary']};
    border: 1px solid transparent;
    border-radius: {r['lg']}px;
    margin-top: 0;
    padding: 0;
}}
QFrame[class="consoleSectionBody"] {{
    background-color: {p['card']};
    border: 1px solid transparent;
    border-radius: {r['md']}px;
}}
QLabel#productSubtitle, QLabel#eyebrowLabel {{
    font-size: 10px;
    font-weight: 600;
    color: {p['mutedForeground']};
    letter-spacing: 1.1px;
}}
QLabel#connectionBadge {{
    background-color: {p['muted']};
    border: 1px solid {p['border']};
    border-radius: 16px;
    color: {p['mutedForeground']};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .7px;
    height: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 14px;
}}
QLabel#connectionBadge[state="connected"] {{ color: {p['success']}; }}
QLabel#connectionBadge[state="fault"] {{ color: {p['destructive']}; }}
QTabBar#primaryNav {{
    background-color: transparent;
    border: none;
    padding: 0;
}}
QTabBar#primaryNav::tab {{
    background-color: {p['muted']};
    color: {p['mutedForeground']};
    border: 1px solid {p['border']};
    border-radius: 16px;
    min-width: 0;
    margin-right: 8px;
    padding: 9px 18px;
    font-size: 12px;
    font-weight: 600;
}}
QTabBar#primaryNav::tab:hover:!selected {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
}}
QTabBar#primaryNav::tab:selected {{
    background-color: {p['accent']};
    color: {p['foreground']};
    border-color: transparent;
}}
QLabel#connectionFieldLabel {{
    color: {p['mutedForeground']};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .8px;
}}
/* One pill geometry for every control the user operates the target with:
   Open Bundle, New App, Target IP, Port, Connect, the link badge, and the
   User/Key fields. The 36px height and 16px radius are the navigation tab's
   own -- "Display Console" is the reference the rest of the chrome is matched
   to, so a row of controls reads as one family rather than five sizes.
   Heights are pinned at both ends because a QSS `height` alone is a hint the
   layout is free to stretch, which is what left these controls at 54px. */
QPushButton#topBarAction {{
    height: 34px;
    min-height: 34px;
    max-height: 34px;
    border-radius: 16px;
    padding-top: 0;
    padding-bottom: 0;
    padding-left: 18px;
    padding-right: 18px;
}}
/* The outline variant draws its shape entirely with `border`, and in the dark
   palette that token is #00000000 -- so Open Bundle was bare text with no pill
   at all. Up here it wears the unselected navigation tab's own fill, which is
   the shape it is being asked to match. */
QPushButton#topBarAction[variant="outline"] {{
    background-color: {p['muted']};
    border: 1px solid {p['border']};
    color: {p['foreground']};
}}
QPushButton#topBarAction[variant="outline"]:hover {{
    background-color: {p['accent']};
    color: {p['accentForeground']};
}}
QLineEdit#targetHostInput, QLineEdit#targetPortInput {{
    background-color: {p['background']};
    border-color: {p['ring']};
    border-radius: 16px;
    font-size: 13px;
    height: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 {scale[2]}px;
}}
/* Brand blue in both themes, deliberately not `primary`: that token is
   #006fee in dark but near-black in light, so the one control the operator
   reaches for first changed colour with the theme. */
QPushButton#connectButton {{
    background-color: {p['brand']};
    color: {p['brandForeground']};
    height: 34px;
    min-height: 34px;
    max-height: 34px;
    border-radius: 16px;
    padding-top: 0;
    padding-bottom: 0;
    padding-left: 18px;
    padding-right: 18px;
}}
/* Without these the base :hover rule reaches back for `primary` and the
   button turns near-black under the cursor in light mode. */
QPushButton#connectButton:hover {{
    background-color: {hex_to_rgba(p['brand'], 0.9)};
    color: {p['brandForeground']};
}}
QPushButton#connectButton:pressed {{
    background-color: {hex_to_rgba(p['brand'], 0.8)};
    color: {p['brandForeground']};
}}
QPushButton#connectButton:disabled {{
    background-color: {hex_to_rgba(p['brand'], 0.5)};
    color: {hex_to_rgba(p['brandForeground'], 0.6)};
}}
QLineEdit#targetDetailInput {{
    border-radius: 16px;
    height: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 {scale[2]}px;
}}
QTabWidget#workspaceTabs::pane {{
    background-color: {p['card']};
    border: 1px solid {p['border']};
    border-radius: {r['xl']}px;
    top: -1px;
}}
QTabWidget#workspaceTabs QTabBar {{
    background-color: {p['muted']};
    border: 1px solid {p['border']};
    border-radius: {r['full']}px;
    padding: 4px;
}}
QTabWidget#workspaceTabs QTabBar::tab {{
    min-width: 96px;
    padding: 8px 14px;
    font-size: 12px;
    font-weight: 600;
}}
QTabWidget#workspaceTabs QTabBar::tab:selected {{
    background-color: {p['primary']};
    color: {p['primaryForeground']};
}}
QGroupBox {{
    background-color: {p['card']};
    border: 1px solid {p['border']};
    border-radius: {r['xl']}px;
    margin-top: 18px;
    padding-top: 6px;
}}
QGroupBox::title {{
    color: {p['foreground']};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: .3px;
    subcontrol-origin: margin;
    padding: 0 10px;
}}
QLineEdit, QComboBox {{
    background-color: {p['background']};
    border-color: {p['input']};
    border-radius: {r['lg']}px;
    min-height: 28px;
}}
QPushButton {{
    border-radius: {r['lg']}px;
    font-weight: 600;
    min-height: 28px;
}}
QPushButton[variant="secondary"] {{ background-color: {p['secondary']}; }}
QPlainTextEdit, QTextEdit {{
    background-color: #0a0b0e;
    color: {p['mutedForeground']};
    border-color: {p['border']};
    border-radius: {r['lg']}px;
}}
QTableWidget {{
    background-color: {p['background']};
    alternate-background-color: {p['muted']};
    border: 1px solid {p['border']};
    border-radius: {r['lg']}px;
    gridline-color: {p['border']};
}}
QHeaderView::section {{
    background-color: {p['muted']};
    color: {p['mutedForeground']};
    border: none;
    border-bottom: 1px solid {p['border']};
    padding: 8px;
    font-size: 11px;
    font-weight: 700;
}}
"""

# The theme last handed to apply(). Icons are rendered as pixmaps, so unlike
# everything the stylesheet reaches they cannot re-colour themselves; they need
# to be told which palette is on screen.
_ACTIVE_THEME = 'light'


def active_theme() -> str:
    """Return the theme most recently applied to the application."""
    return _ACTIVE_THEME


def apply(app: QApplication, theme: str = 'light') -> None:
    """
    Apply the shadcn theme to a QApplication.
    
    Sets the stylesheet, configures the font (using FONT_STACK with fallback),
    and sets the palette. Side effect: modifies app's stylesheet, font, and palette.
    
    Args:
        app (QApplication): The application instance to style.
        theme (str): 'light' or 'dark'. Defaults to 'light'.
    """
    global _ACTIVE_THEME
    _ACTIVE_THEME = theme
    app.setStyleSheet(qss(theme))
    
    font = QFont()
    font.setFamilies(list(FONT_STACK))
    t = load_tokens()
    font.setPixelSize(t['typography']['sizes']['base'])
    app.setFont(font)
    
    p = t['palettes'][theme]
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(p['background']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(p['foreground']))
    palette.setColor(QPalette.ColorRole.Base, QColor(p['background']))
    palette.setColor(QPalette.ColorRole.Text, QColor(p['foreground']))
    palette.setColor(QPalette.ColorRole.Button, QColor(p['primary']))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(p['primaryForeground']))
    app.setPalette(palette)

def qml_import_path() -> str:
    """
    Return the absolute path to ui/qml/ so callers can add it to QQmlEngine's import path list.
    
    Returns:
        str: Absolute path to the ui/qml directory.
    """
    base_dir = Path(__file__).resolve().parent.parent
    return str(base_dir / "qml")

def icon(name: str, size: int = 18, color: Union[str, QColor, None] = None) -> QIcon:
    """
    Return a QIcon rendering the named Tabler icon at the given size.

    Uses the vendored icon registry from ui/icons/tabler_icons.py, loaded by
    file path so it works regardless of whether ui/ is on sys.path.  The SVG
    body is wrapped in a full <svg> element with the requested stroke colour
    and rendered via QSvgRenderer to produce a crisp pixmap.

    Unknown name returns a placeholder icon (red X on grey) and logs a warning.
    Never raises an exception.

    Args:
        name (str): The Tabler icon name (e.g. "upload", "settings").
        size (int): Render size in px, both width and height.  Defaults to 18.
        color (str | QColor | None): Stroke colour.  None follows the theme
            last applied, using its 'foreground' token.

    Returns:
        QIcon: The requested icon, or a visible placeholder if the name is
        unknown or the registry cannot be loaded.

    Side effects:
        Logs a warning via the module logger for unknown icon names or load
        failures.  Never raises.
    """
    # -- resolve colour -------------------------------------------------
    if color is None:
        # The default used to be the light theme's foreground, spelled out as a
        # literal. Under the dark theme that painted every icon in near-black
        # on a near-black bar: present, aligned, and invisible.
        try:
            color_str = globals()["color"]("foreground", _ACTIVE_THEME)
        except Exception:
            color_str = "#020817"
    elif isinstance(color, QColor):
        color_str = color.name()
    else:
        color_str = str(color)

    # -- load the vendored registry by file path ------------------------
    svg_body = None
    try:
        icons_path = Path(__file__).resolve().parent.parent / "icons" / "tabler_icons.py"
        if icons_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("tabler_icons", str(icons_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            registry = getattr(mod, "TABLER_ICONS", {})
            svg_body = registry.get(name)
    except Exception as exc:
        logger.warning("Failed to load tabler_icons registry: %s", exc)

    if svg_body is not None:
        # Wrap in a complete SVG element matching Tabler's 24x24 viewBox,
        # outline style (stroke-width 2, round caps/joins, no fill).
        svg_xml = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 24 24" stroke="{color_str}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" fill="none">'
            f'{svg_body}</svg>'
        )
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtCore import QByteArray
            renderer = QSvgRenderer(QByteArray(svg_xml.encode("utf-8")))
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(0, 0, 0, 0))  # transparent background
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            return QIcon(pixmap)
        except ImportError:
            logger.warning("QSvgRenderer not available; returning placeholder for '%s'", name)
        except Exception as exc:
            logger.warning("SVG render failed for '%s': %s", name, exc)

    # -- fallback placeholder: grey square with red X -------------------
    logger.warning("Returning placeholder for unknown or unrenderable icon '%s'", name)
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#94a3b8"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#ef4444"))
    painter.drawLine(2, 2, size - 2, size - 2)
    painter.drawLine(2, size - 2, size - 2, 2)
    painter.end()
    return QIcon(pixmap)

def generate_qss_files() -> None:
    """
    Generate ui/qss/shadcn_light.qss and ui/qss/shadcn_dark.qss from tokens.json.
    
    Called by the developer to regenerate after token changes.
    """
    base_dir = Path(__file__).resolve().parent.parent
    qss_dir = base_dir / "qss"
    qss_dir.mkdir(parents=True, exist_ok=True)
    
    for theme in ['light', 'dark']:
        qss_content = qss(theme)
        out_path = qss_dir / f"shadcn_{theme}.qss"
        # newline="\n" is required, not cosmetic: without it Python's text mode
        # translates every \n to \r\n on Windows, so regenerating on a Windows
        # host would rewrite these committed files with CRLF and produce a
        # spurious diff on a repository that is LF-only by policy.
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(qss_content)
        print(f"Generated {out_path}")

if __name__ == "__main__":
    generate_qss_files()
