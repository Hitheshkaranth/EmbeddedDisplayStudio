"""
Test suite validating the integrity and synchronization between tokens.json 
and the QML Theme.qml singleton.
"""

import json
import re
import unittest
from pathlib import Path

class TestTokens(unittest.TestCase):
    """
    Test cases to ensure the QML theme matches the JSON tokens source of truth.
    """
    
    @classmethod
    def setUpClass(cls):
        """
        Loads the JSON tokens and QML content for use in test methods.
        If files are missing, it will raise an error that fails the tests.
        """
        cls.base_dir = Path(__file__).resolve().parent.parent
        
        tokens_path = cls.base_dir / "tokens.json"
        if not tokens_path.exists():
            raise FileNotFoundError(f"tokens.json not found at {tokens_path}")
            
        with open(tokens_path, "r", encoding="utf-8") as f:
            cls.tokens = json.load(f)
            
        qml_path = cls.base_dir / "qml" / "Shadcn" / "Theme.qml"
        if not qml_path.exists():
            raise FileNotFoundError(
                f"Theme.qml not found at {qml_path}. The design system must provide "
                "a QML Theme singleton to synchronize with tokens."
            )
            
        with open(qml_path, "r", encoding="utf-8") as f:
            cls.qml_content = f.read()

    def test_colors_match(self):
        """
        Invariant: Every colour defined in tokens.json (for both light and dark modes)
        must exactly match the corresponding property literal in Theme.qml.
        
        Why: This ensures UI components in Qt Widgets and QML use the exact same
        design language, preventing visual discrepancies.
        """
        light_palette = self.tokens["palettes"]["light"]
        dark_palette = self.tokens["palettes"]["dark"]
        
        for name in light_palette.keys():
            light_val = light_palette[name].lower()
            dark_val = dark_palette[name].lower()
            
            # Look for property color <name>: mode === "light" ? "<light_val>" : "<dark_val>"
            # using regex that ignores exact spacing
            pattern = rf'property\s+color\s+{name}\s*:\s*mode\s*===\s*"light"\s*\?\s*"([^"]+)"\s*:\s*"([^"]+)"'
            match = re.search(pattern, self.qml_content)
            
            self.assertIsNotNone(
                match, 
                f"Could not find property color '{name}' in Theme.qml matching the expected ternary format."
            )
            
            qml_light = match.group(1).lower()
            qml_dark = match.group(2).lower()
            
            self.assertEqual(
                qml_light, light_val,
                f"Light color mismatch for '{name}': JSON={light_val}, QML={qml_light}"
            )
            self.assertEqual(
                qml_dark, dark_val,
                f"Dark color mismatch for '{name}': JSON={dark_val}, QML={qml_dark}"
            )

    def test_radii_match(self):
        """
        Invariant: All border radii values in tokens.json must match Theme.qml.
        
        Why: Ensures corner rounding consistency across widgets and QML.
        """
        radii = self.tokens.get("radii", {})
        for name, val in radii.items():
            if name.startswith("_"):
                continue
            
            # property int radius<Name>: <val> OR property real radius<Name>: <val>
            # capitalize name e.g., 'sm' -> 'Sm', 'full' -> 'Full'
            cap_name = name.capitalize()
            pattern = rf'property\s+(?:int|real)\s+radius{cap_name}\s*:\s*([0-9.]+)'
            match = re.search(pattern, self.qml_content)
            
            self.assertIsNotNone(
                match, 
                f"Could not find property 'radius{cap_name}' in Theme.qml."
            )
            
            qml_val = float(match.group(1))
            self.assertEqual(
                qml_val, float(val),
                f"Radius mismatch for '{name}': JSON={val}, QML={qml_val}"
            )

    def test_typography_sizes_match(self):
        """
        Invariant: Font sizes defined in tokens.json must match Theme.qml.

        Why: Consistency in typography hierarchy across UI frameworks.

        The tokens.json uses names like '2xl' and '3xl' which cannot be used
        directly as QML identifiers (they start with a digit).  Theme.qml
        maps them: 2xl -> Xxl, 3xl -> Xxxl.  This test must apply the same
        mapping.
        """
        sizes = self.tokens["typography"]["sizes"]

        # Mapping from tokens.json key to the suffix used in Theme.qml's
        # property name (fontSizeXxx).  Keys starting with a digit get a
        # spelled-out form; the rest are simply capitalised.
        name_map = {
            "xs":   "Xs",
            "sm":   "Sm",
            "base": "Base",
            "lg":   "Lg",
            "xl":   "Xl",
            "2xl":  "Xxl",
            "3xl":  "Xxxl",
        }

        for name, val in sizes.items():
            if name.startswith("_"):
                continue

            qml_suffix = name_map.get(name)
            if qml_suffix is None:
                # Fallback for any future sizes: capitalize if possible
                qml_suffix = name.capitalize() if not name[0].isdigit() else name
            pattern = rf'property\s+(?:int|real)\s+fontSize{qml_suffix}\s*:\s*([0-9.]+)'
            match = re.search(pattern, self.qml_content)

            self.assertIsNotNone(
                match,
                f"Could not find property 'fontSize{qml_suffix}' in Theme.qml."
            )

            qml_val = float(match.group(1))
            self.assertEqual(
                qml_val, float(val),
                f"Font size mismatch for '{name}': JSON={val}, QML={qml_val}"
            )

if __name__ == "__main__":
    unittest.main()
