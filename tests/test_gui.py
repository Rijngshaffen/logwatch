import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import time
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings

from logwatch.gui import MainWindow


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def pump(self, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition())

    def test_start_filter_inspect_stop_restart_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.log"
            source.write_text("Oct  6 12:00:00 host worker[123]: INFO job completed\n"
                              "Oct  6 12:00:01 host kernel: Out of memory: oom-killer invoked\n")
            preferences = QSettings(str(Path(directory) / "preferences.ini"), QSettings.Format.IniFormat)
            window = MainWindow(preferences=preferences)
            window.source.setCurrentIndex(1)
            window.path.setText(str(source))
            window.from_start.setChecked(True)
            window.output.setText(str(Path(directory) / "alerts.jsonl"))
            window.show()
            window.start_monitoring()
            self.pump(lambda: len(window.log_model.records) == 2)
            self.assertEqual(len(window.alert_model.records), 1)
            self.assertFalse(window.settings.isEnabled())
            self.assertTrue(window.theme_choice.isEnabled())
            window.theme_choice.setCurrentIndex(window.theme_choice.findData("light"))
            self.assertEqual(window.active_theme, "light")
            window.theme_choice.setCurrentIndex(window.theme_choice.findData("dark"))
            self.assertEqual(window.active_theme, "dark")
            self.assertEqual(len(window.log_model.records), 2)
            window.search.setText("oom-killer")
            self.assertEqual(window.proxy.rowCount(), 1)
            window.search.setText("no such event")
            self.assertEqual(window.log_content.currentIndex(), 1)
            window.search.clear()
            window.nav_buttons[1].click()
            self.assertEqual(window.tabs.currentIndex(), 1)
            window.alert_table.selectRow(0)
            self.assertEqual(json.loads(window.json_view.toPlainText())["score"], 95)
            window.copy_button.click()
            self.assertEqual(json.loads(self.app.clipboard().text())["score"], 95)
            window.stop_monitoring()
            self.pump(lambda: window.monitor is None)
            self.assertTrue(window.start.isEnabled())
            window.start_monitoring()
            self.pump(lambda: len(window.log_model.records) == 2)
            window.close()
            self.pump(lambda: not window.isVisible())
            self.assertIsNone(window.monitor)


if __name__ == "__main__":
    unittest.main()
