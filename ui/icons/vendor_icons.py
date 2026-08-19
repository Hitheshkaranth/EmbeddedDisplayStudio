"""
Downloads Tabler Icons SVGs from unpkg and generates registry files.

This script fetches requested icons from the tabler-icons package on unpkg,
extracts their inner SVG content, and writes registries for Python and QML/JS.
"""

import os
import sys
import re
import urllib.request
import urllib.error
import time

ICON_LIST = [
    "upload", "download", "plug", "plug-connected", "plug-off", "refresh", 
    "rotate-clockwise", "device-desktop", "device-imac", "cpu", "server", 
    "terminal-2", "file-code", "folder-open", "folder-plus", "trash", "settings", 
    "adjustments", "sun", "moon", "alert-triangle", "circle-check", "circle-x", 
    "info-circle", "loader-2", "player-play", "player-stop", "power", "bolt", 
    "activity", "gauge", "wifi", "wifi-off", "key", "search", "plus", "x", 
    "chevron-down", "chevron-right", "clipboard-text", "history"
]

BASE_URL = "https://unpkg.com/@tabler/icons@3.31.0/icons/outline/{name}.svg"

def fetch_icon(name):
    """
    Fetches the SVG content for a given icon name from unpkg.
    
    Args:
        name (str): The name of the icon to fetch.
        
    Returns:
        str: The full SVG content as a string, or None if the download fails.
    """
    url = BASE_URL.format(name=name)
    max_retries = 2
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8')
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print(f"Warning: Failed to fetch {name}: {e}", file=sys.stderr)
    return None

def extract_inner_svg(svg_content):
    """
    Extracts the inner content of an SVG tag.
    
    Args:
        svg_content (str): The complete SVG XML string.
        
    Returns:
        str: The inner elements of the SVG.
    """
    # Find the start and end of the SVG tag
    match = re.search(r'<svg[^>]*>(.*?)</svg>', svg_content, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    
    inner = match.group(1).strip()
    
    # We leave stroke="currentColor" and keep path data intact as requested.
    return inner

def generate_python_registry(icons_dict, filepath):
    """
    Generates a Python dictionary file containing the SVG data.
    
    Args:
        icons_dict (dict): Mapping of icon name to inner SVG content.
        filepath (str): The absolute path to save the generated file.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('"""\nGenerated Tabler Icons Registry.\n"""\n\n')
        f.write('TABLER_ICONS = {\n')
        for name, content in icons_dict.items():
            # Escape single quotes and newlines
            safe_content = content.replace("'", "\\'").replace('\\n', '').replace('\n', '')
            f.write(f"    '{name}': '{safe_content}',\n")
        f.write('}\n')

def generate_qml_js_registry(icons_dict, filepath):
    """
    Generates a JS module containing the SVG data for QML usage.
    
    Args:
        icons_dict (dict): Mapping of icon name to inner SVG content.
        filepath (str): The absolute path to save the generated file.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('// Generated Tabler Icons Registry for QML.\n.pragma library\n\n')
        f.write('var icons = {\n')
        for name, content in icons_dict.items():
            safe_content = content.replace("'", "\\'").replace('\\n', '').replace('\n', '')
            f.write(f"    '{name}': '{safe_content}',\n")
        f.write('};\n')

def main():
    """
    Main execution function.
    """
    print("Starting icon vendoring...", file=sys.stderr)
    icons_dict = {}
    for name in ICON_LIST:
        print(f"Fetching {name}...", file=sys.stderr)
        svg_content = fetch_icon(name)
        if svg_content:
            inner_content = extract_inner_svg(svg_content)
            icons_dict[name] = inner_content
            
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(base_dir))
    
    python_reg_path = os.path.join(base_dir, "tabler_icons.py")
    js_reg_path = os.path.join(project_root, "ui", "qml", "Shadcn", "TablerIcons.js")
    
    print(f"Generating Python registry at {python_reg_path}...", file=sys.stderr)
    generate_python_registry(icons_dict, python_reg_path)
    
    print(f"Generating JS registry at {js_reg_path}...", file=sys.stderr)
    generate_qml_js_registry(icons_dict, js_reg_path)
    
    print("Done.", file=sys.stderr)

if __name__ == "__main__":
    main()
