import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from designer.ui import DesignerWorkspace


class DesignerTextCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_add_set_bind_remove(self):
        workspace = DesignerWorkspace()
        self.assertIn("Added", workspace.apply_text_command("add Value Tile named inputVoltage"))
        workspace.apply_text_command("set inputVoltage title=Input Voltage")
        workspace.apply_text_command("bind inputVoltage value=power.input_voltage")
        widget = workspace.current_page.widgets[0]
        self.assertEqual(widget.properties["title"], "Input Voltage")
        self.assertEqual(widget.bindings["value"].tag, "power.input_voltage")
        workspace.apply_text_command("remove inputVoltage")
        self.assertEqual(workspace.current_page.widgets, [])
        workspace.close()


if __name__ == "__main__":
    unittest.main()
