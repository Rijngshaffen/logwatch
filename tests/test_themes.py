import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtDBus import QDBusMessage, QDBusPendingCall, QDBusPendingCallWatcher, QDBusVariant
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication

from logwatch.gui import MainWindow
from logwatch.themes import COLORS, SystemThemeWatcher, stylesheet


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_live_system_updates_manual_override_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "appearance.ini"), QSettings.Format.IniFormat)
            watcher = SystemThemeWatcher(use_portal=False)
            watcher.qt_changed(Qt.ColorScheme.Light)
            original_palette = QPalette(self.app.palette())
            window = MainWindow(preferences=settings, system_theme=watcher)
            window.show()
            self.assertEqual(window.active_theme, "light")
            watcher.hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
            self.assertEqual(window.active_theme, "dark")
            window.theme_choice.setCurrentIndex(window.theme_choice.findData("light"))
            watcher.qt_changed(Qt.ColorScheme.Light)
            watcher.qt_changed(Qt.ColorScheme.Dark)
            self.assertEqual(window.active_theme, "light")
            self.assertEqual(window.log_model.theme, "light")
            self.assertEqual(window.json_highlighter.theme, "light")
            self.assertEqual(window.palette().color(QPalette.ColorRole.Window).name(), COLORS["light"]["background"])
            self.assertEqual(self.app.palette(), original_palette)
            window.close()
            restored = MainWindow(preferences=settings, system_theme=watcher)
            self.assertEqual(restored.theme_choice.currentData(), "light")
            self.assertEqual(restored.active_theme, "light")
            restored.theme_choice.setCurrentIndex(restored.theme_choice.findData("system"))
            self.assertEqual(restored.active_theme, "dark")
            watcher.portal_changed("org.freedesktop.appearance", "color-scheme", QDBusVariant(2))
            self.assertEqual(restored.active_theme, "light")
            restored.close()
            window.deleteLater()
            restored.deleteLater()
            watcher.deleteLater()

    def test_portal_variants_no_preference_fallback_and_stale_reply(self):
        watcher = SystemThemeWatcher(use_portal=False)
        watcher.qt_changed(Qt.ColorScheme.Light)
        watcher.portal_changed("other.namespace", "color-scheme", QDBusVariant(1))
        self.assertEqual(watcher.current_theme, "light")
        watcher.portal_changed("org.freedesktop.appearance", "color-scheme", QDBusVariant(QDBusVariant(1)))
        self.assertEqual(watcher.current_theme, "dark")
        old_revision = watcher.portal_revision
        watcher.portal_changed("org.freedesktop.appearance", "color-scheme", QDBusVariant(2))
        message = QDBusMessage.createMethodCall(watcher.service, watcher.path, watcher.interface, "Read")
        reply = QDBusPendingCallWatcher(QDBusPendingCall.fromCompletedCall(message.createReply([QDBusVariant(1)])))
        watcher.portal_read_finished(reply, old_revision)
        self.assertEqual(watcher.current_theme, "light")
        current_reply = QDBusPendingCallWatcher(QDBusPendingCall.fromCompletedCall(message.createReply([QDBusVariant(1)])))
        watcher.portal_read_finished(current_reply, watcher.portal_revision)
        self.assertEqual(watcher.current_theme, "dark")
        watcher.qt_changed(Qt.ColorScheme.Dark)
        watcher.portal_changed("org.freedesktop.appearance", "color-scheme", QDBusVariant(0))
        self.assertEqual(watcher.current_theme, "dark")
        watcher.qt_changed(Qt.ColorScheme.Unknown)
        expected = "dark" if self.app.palette().color(QPalette.ColorRole.Window).lightness() < 128 else "light"
        self.assertEqual(watcher.current_theme, expected)
        self.assertIsNone(watcher.portal_value("invalid"))
        watcher.deleteLater()

    def test_both_stylesheets_resolve_completely(self):
        self.assertIn("#f4f5fb", stylesheet("light"))
        self.assertIn("#0c101c", stylesheet("dark"))

    def test_application_shutdown_removes_global_theme_hooks(self):
        code = '''
import tempfile
from pathlib import Path
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication
from logwatch.gui import MainWindow
app = QApplication([])
with tempfile.TemporaryDirectory() as directory:
    settings = QSettings(str(Path(directory) / 'appearance.ini'), QSettings.Format.IniFormat)
    window = MainWindow(preferences=settings)
    window.show()
    window.theme_choice.setCurrentIndex(window.theme_choice.findData('light'))
    QTimer.singleShot(50, window.close)
    assert app.exec() == 0
    assert window.system_theme.closed
'''
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
