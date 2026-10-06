"""Shared dark/light appearance tokens and native desktop theme notifications."""
import re

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher, QDBusPendingReply, QDBusServiceWatcher, QDBusVariant
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

DARK_STYLE = """
QWidget { background: transparent; color: #d5dbeb; font-size: 13px; }
QMainWindow, QWidget#workspace { background: #0c101c; }
QWidget#sidebar { background: #111625; border-right: 1px solid #242b40; }
QLabel { border: none; }
QLabel#brand { font-size: 21px; font-weight: 700; color: #f4f5ff; }
QLabel#brandMark { background: #7662ed; border-radius: 10px; padding: 9px; }
QLabel#title { font-size: 27px; font-weight: 700; color: #f4f5ff; }
QLabel#subtitle, QLabel#cardNote { color: #8d99b2; font-size: 12px; }
QLabel#eyebrow { color: #77849f; font-size: 10px; font-weight: 600; }
QLabel#cardHeading { color: #a8b1c8; font-size: 12px; }
QLabel#metric { font-size: 32px; font-weight: 700; }
QLabel#sectionTitle { color: #f0f2fc; font-size: 16px; font-weight: 600; }
QLabel#statusBadge { background: #222a40; color: #a9b4cd; border-radius: 12px; padding: 6px 13px; font-size: 11px; font-weight: 600; }
QLabel#statusBadge[state="live"] { background: #14372f; color: #74e2bf; }
QLabel#statusBadge[state="stopping"] { background: #3c3020; color: #ffc780; }
QWidget#metricCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1b2135,stop:1 #141a2b); border: 1px solid #2a324a; border-radius: 13px; }
QWidget#sourcePanel, QWidget#baselinePanel { background: #141a2b; border: 1px solid #252e43; border-radius: 11px; }
QGroupBox { background: #141a2b; border: 1px solid #2a324a; border-radius: 12px; margin-top: 18px; padding: 20px; }
QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 7px; color: #b9c1d9; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox { background: #101625; border: 1px solid #303a52; border-radius: 7px; padding: 9px 11px; selection-background-color: #6452ca; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #9a88ff; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox::down-arrow { width: 0; height: 0; }
QSpinBox::up-button, QSpinBox::down-button { background: #1b2438; border: none; width: 25px; }
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0; height: 0; }
QComboBox QAbstractItemView { background: #1b2236; border: 1px solid #39435e; selection-background-color: #383258; padding: 5px; }
QPushButton { background: #1c2438; border: 1px solid #34415a; border-radius: 7px; padding: 10px 15px; font-weight: 500; }
QPushButton:hover { background: #29334b; border-color: #606887; }
QPushButton:pressed { background: #333d58; }
QPushButton#start { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #8b75f4,stop:1 #6c58de); color: white; border: 1px solid #a393fa; font-weight: 600; }
QPushButton#start:hover { background: #9983ff; }
QPushButton#start:disabled { background: #202639; color: #68748e; border: 1px solid #2d3549; }
QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #65718a; border-color: #273047; }
QPushButton#nav { text-align: left; background: transparent; border: 1px solid transparent; padding: 13px; color: #97a3bd; border-radius: 8px; }
QPushButton#nav:hover { background: #1c2337; color: #e8e6ff; }
QPushButton#nav:checked { background: #2a2545; color: #c7bbff; border-color: #403662; }
QTabWidget::pane { background: #111726; border: 1px solid #283149; border-radius: 12px; }
QTableView { background: #111726; alternate-background-color: #151c2e; border: 0; selection-background-color: #2a3050; selection-color: #f2efff; }
QTableView::item { padding: 6px; border-bottom: 1px solid #20283c; }
QTableView::item:selected { background: #2a3050; }
QHeaderView { background: #1a2235; }
QHeaderView::section { background: #1a2235; color: #8896b2; border: none; padding: 12px 7px; font-size: 11px; font-weight: 600; }
QPlainTextEdit { background: #0e1422; color: #cbd5e1; border: 1px solid #29334b; border-radius: 8px; padding: 10px; selection-background-color: #3e3763; }
QProgressBar { border: 0; background: #2a3149; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #9380ff,stop:1 #69d6c0); border-radius: 3px; }
QCheckBox { color: #a6b1c9; spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #4a5573; border-radius: 4px; background: #131a2a; }
QCheckBox::indicator:checked { background: #8370ee; border-color: #b2a4ff; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle { background: #3a4560; border-radius: 3px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: #626e91; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: #29334b; width: 1px; }
QStatusBar { background: #0c101c; color: #8794af; font-size: 11px; border-top: 1px solid #20283b; }
QToolTip { background: #222b42; color: #eef0ff; border: 1px solid #4c5571; padding: 6px; }
"""

# One-pass replacement preserves layout and avoids cascading color substitutions.
LIGHT_CSS_COLORS = {
    "#0c101c": "#f4f5fb", "#0e1422": "#f8f9fd", "#101625": "#ffffff",
    "#111625": "#ffffff", "#111726": "#ffffff", "#131a2a": "#ffffff",
    "#141a2b": "#ffffff", "#14372f": "#daf4e8", "#151c2e": "#f7f8fc",
    "#1a2235": "#eef0f8", "#1b2135": "#ffffff", "#1b2236": "#ffffff",
    "#1b2438": "#eef0f8", "#1c2337": "#f0eefb", "#1c2438": "#ffffff",
    "#202639": "#eceef5", "#20283b": "#dce0ee", "#20283c": "#e8ebf4",
    "#222a40": "#e8ebf4", "#222b42": "#ffffff", "#242b40": "#dfe3ef",
    "#252e43": "#dfe3ef", "#273047": "#dfe3ef", "#283149": "#dce1ef",
    "#29334b": "#e7eaf6", "#2a2545": "#eee9ff", "#2a3050": "#e8e1ff",
    "#2a3149": "#e4e8f3", "#2a324a": "#dfe3ef", "#2d3549": "#dfe3ef",
    "#303a52": "#d0d7e8", "#333d58": "#e4defa", "#34415a": "#d0d7e8",
    "#383258": "#e8e1ff", "#39435e": "#d0d7e8", "#3a4560": "#bcc5d9",
    "#3c3020": "#fff0d6", "#3e3763": "#e8e1ff", "#403662": "#dbd0ff",
    "#4a5573": "#b8c1d7", "#4c5571": "#c4cce0", "#606887": "#a69acb",
    "#626e91": "#929fb9", "#6452ca": "#e8e1ff", "#65718a": "#929bb0",
    "#68748e": "#8a95ad", "#69d6c0": "#26a78c", "#6c58de": "#6548ce",
    "#74e2bf": "#177653", "#7662ed": "#7656e7", "#77849f": "#69758e",
    "#8370ee": "#7656e7", "#8794af": "#63718b", "#8896b2": "#52617e",
    "#8b75f4": "#8164e9", "#8d99b2": "#63708a", "#9380ff": "#8064e8",
    "#97a3bd": "#5d6b87", "#9983ff": "#7553e1", "#9a88ff": "#8566e7",
    "#a393fa": "#9c83ef", "#a6b1c9": "#5b6985", "#a8b1c8": "#576680",
    "#a9b4cd": "#596883", "#b2a4ff": "#957ce5", "#b9c1d9": "#455371",
    "#c7bbff": "#6346bb", "#cbd5e1": "#36435e", "#d5dbeb": "#303c55",
    "#e8e6ff": "#6346bb", "#eef0ff": "#303c55", "#f0f2fc": "#26334f",
    "#f2efff": "#303c55", "#f4f5ff": "#202c48", "#ffc780": "#945e09",
}

COLORS = {
    "dark": dict(text="#d5dbeb", muted="#93a0b9", service="#99d9cd", control="#a6b1c9",
                 disabled="#586580", disabled_check="#a19abf", chart_grid="#293149",
                 key="#a99bff", string="#88dbc6", literal="#ffc780",
                 events="#b1a2ff", alerts="#ff9cac", saved="#76dfc3", delivered="#83bfff",
                 background="#0c101c", base="#101625", alternate="#151c2e", button="#1c2438",
                 selection="#2a3050", selected_text="#f2efff", placeholder="#8d99b2"),
    "light": dict(text="#303c55", muted="#63708a", service="#187966", control="#5b6985",
                  disabled="#929bb0", disabled_check="#ddd6f2", chart_grid="#dce1ef",
                  key="#704dbb", string="#15785e", literal="#986010",
                  events="#7353c6", alerts="#b83f60", saved="#16765b", delivered="#276aaa",
                  background="#f4f5fb", base="#ffffff", alternate="#f7f8fc", button="#ffffff",
                  selection="#e8e1ff", selected_text="#303c55", placeholder="#63708a"),
}


def stylesheet(theme):
    if theme == "light":
        return re.sub(r"#[0-9a-f]{6}", lambda match: LIGHT_CSS_COLORS[match[0]], DARK_STYLE)
    return DARK_STYLE


def theme_color(widget, role):
    return COLORS[getattr(widget.window(), "active_theme", "dark")][role]


def window_palette(theme):
    palette = QPalette(QApplication.palette())
    colors = COLORS[theme]
    for role, name in [(QPalette.ColorRole.Window, "background"), (QPalette.ColorRole.Base, "base"),
                       (QPalette.ColorRole.AlternateBase, "alternate"), (QPalette.ColorRole.Button, "button"),
                       (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Text, "text"),
                       (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "base"),
                       (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Highlight, "selection"),
                       (QPalette.ColorRole.HighlightedText, "selected_text"),
                       (QPalette.ColorRole.PlaceholderText, "placeholder"), (QPalette.ColorRole.Link, "events")]:
        palette.setColor(role, QColor(colors[name]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
    return palette


class SystemThemeWatcher(QObject):
    """Read-only Qt + XDG Settings portal integration; never changes the desktop."""
    changed = pyqtSignal(str)
    service = "org.freedesktop.portal.Desktop"
    path = "/org/freedesktop/portal/desktop"
    interface = "org.freedesktop.portal.Settings"

    def __init__(self, parent=None, use_portal=True):
        super().__init__(parent if parent is not None else QApplication.instance())
        self.closed = False
        self.portal_theme = None
        self.portal_revision = 0
        self.hints = QApplication.styleHints()
        self.qt_scheme = self.hints.colorScheme()
        self.current_theme = self.resolve()
        self.hints.colorSchemeChanged.connect(self.qt_changed)
        QApplication.instance().installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.stop)
        self.bus = None
        if use_portal:
            self.bus = QDBusConnection.sessionBus()
            if self.bus.isConnected():
                self.bus.connect(self.service, self.path, self.interface, "SettingChanged", self.portal_changed)
                self.service_watcher = QDBusServiceWatcher(self.service, self.bus,
                    QDBusServiceWatcher.WatchModeFlag.WatchForOwnerChange, self)
                self.service_watcher.serviceOwnerChanged.connect(self.portal_owner_changed)
                QTimer.singleShot(0, self.read_portal)

    def resolve(self):
        if self.portal_theme:
            return self.portal_theme
        if self.qt_scheme == Qt.ColorScheme.Dark:
            return "dark"
        if self.qt_scheme == Qt.ColorScheme.Light:
            return "light"
        # Use the untouched application/system palette, not our window's override.
        return "dark" if QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128 else "light"

    def refresh(self):
        if self.closed:
            return
        resolved = self.resolve()
        if resolved != self.current_theme:
            self.current_theme = resolved
            self.changed.emit(resolved)

    def qt_changed(self, scheme):
        self.qt_scheme = scheme
        self.refresh()

    def eventFilter(self, watched, event):
        if not self.closed and event.type() == QEvent.Type.ApplicationPaletteChange:
            QTimer.singleShot(0, self.refresh)
        return False

    @staticmethod
    def portal_value(value):
        while isinstance(value, QDBusVariant):
            value = value.variant()
        return {1: "dark", 2: "light"}.get(value) if isinstance(value, int) else None

    @pyqtSlot(str, str, QDBusVariant)
    def portal_changed(self, namespace, key, value):
        if namespace == "org.freedesktop.appearance" and key == "color-scheme":
            self.portal_revision += 1
            self.portal_theme = self.portal_value(value)
            self.refresh()

    def portal_owner_changed(self, service, old_owner, new_owner):
        self.portal_revision += 1
        self.portal_theme = None
        self.refresh()
        if new_owner:
            self.read_portal()

    def read_portal(self):
        if self.closed or not self.bus or not self.bus.isConnected():
            return
        request = QDBusMessage.createMethodCall(self.service, self.path, self.interface, "Read")
        request.setArguments(["org.freedesktop.appearance", "color-scheme"])
        revision = self.portal_revision
        watcher = QDBusPendingCallWatcher(self.bus.asyncCall(request, 1500), self)
        watcher.finished.connect(lambda done: self.portal_read_finished(done, revision))

    def portal_read_finished(self, watcher, revision):
        reply = QDBusPendingReply(watcher).reply()
        if not self.closed and revision == self.portal_revision and reply.type() == QDBusMessage.MessageType.ReplyMessage and reply.arguments():
            self.portal_theme = self.portal_value(reply.arguments()[0])
            self.refresh()
        watcher.deleteLater()

    def stop(self):
        """Remove global hooks before Qt tears down its platform integration."""
        if self.closed:
            return
        self.closed = True
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        try:
            self.hints.colorSchemeChanged.disconnect(self.qt_changed)
        except (TypeError, RuntimeError):
            pass
        if self.bus and self.bus.isConnected():
            self.bus.disconnect(self.service, self.path, self.interface, "SettingChanged", self.portal_changed)
        if hasattr(self, "service_watcher"):
            self.service_watcher.blockSignals(True)
