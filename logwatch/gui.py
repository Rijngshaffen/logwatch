from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSettings, QSortFilterProxyModel, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QMainWindow, QMessageBox, QScrollArea,
    QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QStackedWidget,
    QTabWidget, QTableView, QVBoxLayout, QWidget,
)

from .delivery import AlertSender, DeliveryConfig
from .detector import DetectorConfig
from .models import utc_now
from .monitor import Monitor, SourceConfig
from .ui_components import JsonHighlighter, MetricCard, ModernCheckBox, ModernComboBox, ModernSpinBox, SeverityDelegate, icon
from .themes import COLORS, SystemThemeWatcher, stylesheet, window_palette


class RecordModel(QAbstractTableModel):
    def __init__(self, alerts=False):
        super().__init__()
        self.records = []
        self.alerts = alerts
        self.theme = "dark"
        self.capacity = 500 if alerts else 3000
        self.headers = ["Detected at", "Severity", "Score", "Reason", "Service"] if alerts else ["Timestamp", "Level", "Service", "Message"]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        record = self.records[index.row()]
        level = record["severity"] if self.alerts else record.level
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS[self.theme]["muted" if index.column() == 0 else "service" if index.column() == (4 if self.alerts else 2) else "text"])
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if self.alerts:
                values = [record["timestamp"], level.upper(), record["score"],
                          ", ".join(r["type"] for r in record["reasons"]), record["event"]["service"]]
            else:
                values = [record.timestamp, level.upper(), record.service, record.message]
            value = str(values[index.column()])
            if role == Qt.ItemDataRole.DisplayRole and index.column() == 0 and "T" in value and (value.endswith("+00:00") or value.endswith("Z")):
                return value.split("T", 1)[1][:12] + " UTC"
            return value if role == Qt.ItemDataRole.ToolTipRole else value[:1000]

    def append(self, records):
        records = records[-self.capacity:]
        excess = max(0, len(self.records) + len(records) - self.capacity)
        if excess:
            self.beginRemoveRows(QModelIndex(), 0, excess - 1)
            del self.records[:excess]
            self.endRemoveRows()
        if records:
            start = len(self.records)
            self.beginInsertRows(QModelIndex(), start, start + len(records) - 1)
            self.records.extend(records)
            self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self.records.clear()
        self.endResetModel()


class LogFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.level = "All levels"

    def filterAcceptsRow(self, row, parent):
        record = self.sourceModel().records[row]
        return (self.level == "All levels" or record.level == self.level.lower()) and (
            not self.query or self.query in f"{record.timestamp} {record.service} {record.message}".lower())

    def update_filter(self, query, level):
        self.query, self.level = query.lower(), level
        self.invalidateFilter()


def table(model):
    widget = QTableView()
    widget.setModel(model)
    widget.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QTableView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
    widget.setAlternatingRowColors(True)
    widget.setWordWrap(False)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(40)
    widget.setShowGrid(False)
    widget.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setColumnWidth(0, 160)
    widget.setColumnWidth(1, 105)
    widget.setColumnWidth(2, 140)
    widget.setItemDelegateForColumn(1, SeverityDelegate(widget))
    return widget





class MainWindow(QMainWindow):
    def __init__(self, demo=False, preferences=None, system_theme=None):
        super().__init__()
        self.setWindowTitle("LogWatch — Linux anomaly monitor")
        self.resize(1440, 940)
        self.setMinimumSize(1024, 720)
        self.monitor = self.sender = self.cleanup = None
        self.closing = False
        self.notices = queue.Queue(maxsize=100)
        self.last_chart_at = 0
        self.previous_counters = {}
        self.preferences = preferences if preferences is not None else QSettings("LogWatch", "LogWatch")
        self.system_theme = system_theme or SystemThemeWatcher(self)
        self.active_theme = "dark"
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(194)
        rail = QVBoxLayout(sidebar)
        rail.setContentsMargins(16, 28, 16, 20)
        rail.setSpacing(9)
        brand_row = QHBoxLayout()
        brand_mark = QLabel()
        brand_mark.setObjectName("brandMark")
        brand_mark.setPixmap(icon("pulse", "#ffffff", 22).pixmap(22, 22))
        brand_row.addWidget(brand_mark)
        brand = QLabel("LogWatch")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        rail.addLayout(brand_row)
        tagline = QLabel("SYSTEM OBSERVABILITY")
        tagline.setObjectName("eyebrow")
        rail.addWidget(tagline)
        rail.addSpacing(35)
        section = QLabel("WORKSPACE")
        section.setObjectName("eyebrow")
        rail.addWidget(section)
        self.nav_buttons = []
        for index, (label, glyph) in enumerate([("Live logs", "logs"), ("Alerts", "alerts"), ("Settings", "settings"), ("Activity", "activity")]):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setIcon(icon(glyph))
            button.setIconSize(QSize(18, 18))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(lambda checked, page=index: self.tabs.setCurrentIndex(page))
            self.nav_buttons.append(button)
            rail.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        rail.addStretch()
        local_note = QLabel("LOCAL ANALYSIS")
        local_note.setObjectName("eyebrow")
        rail.addWidget(local_note)
        note = QLabel("Adaptive statistics.\nClear reasons for every alert.")
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        rail.addWidget(note)
        rail.addSpacing(20)
        version = QLabel("●  Linux  /  v1.0")
        version.setObjectName("subtitle")
        rail.addWidget(version)
        outer.addWidget(sidebar)
        workspace = QWidget()
        workspace.setObjectName("workspace")
        outer.addWidget(workspace, 1)
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(26, 26, 26, 16)
        layout.setSpacing(18)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        self.page_title = QLabel("Live log explorer")
        self.page_title.setObjectName("title")
        heading.addWidget(self.page_title)
        subtitle = QLabel("Understand your system. Catch what stands out.")
        subtitle.setObjectName("subtitle")
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self.status_badge = QLabel("●  READY")
        self.status_badge.setObjectName("statusBadge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setFixedHeight(30)
        header.addWidget(self.status_badge)
        header.addSpacing(10)
        self.start = QPushButton("Start monitoring")
        self.start.setObjectName("start")
        self.start.setIcon(icon("play", "#ffffff", 16))
        self.start.clicked.connect(self.start_monitoring)
        self.stop = QPushButton("Stop")
        self.stop.setIcon(icon("stop", "#b3bdd4", 16))
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.stop_monitoring)
        header.addWidget(self.start)
        header.addWidget(self.stop)
        layout.addLayout(header)

        source_panel = QWidget()
        source_panel.setObjectName("sourcePanel")
        source_row = QHBoxLayout(source_panel)
        source_row.setContentsMargins(14, 12, 14, 12)
        source_caption = QLabel("LOG SOURCE")
        source_caption.setObjectName("eyebrow")
        source_row.addWidget(source_caption)
        self.source = ModernComboBox()
        self.source.addItems(["Systemd journal", "Log file", "Demo stream"])
        source_row.addWidget(self.source)
        self.source_options = QStackedWidget()
        journal = QWidget()
        jrow = QHBoxLayout(journal)
        jrow.setContentsMargins(0, 0, 0, 0)
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("All services, or a unit such as ssh.service")
        self.user_journal = ModernCheckBox("User journal")
        jrow.addWidget(self.unit)
        jrow.addWidget(self.user_journal)
        self.source_options.addWidget(journal)
        file_widget = QWidget()
        frow = QHBoxLayout(file_widget)
        frow.setContentsMargins(0, 0, 0, 0)
        self.path = QLineEdit("/var/log/syslog")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_log)
        self.from_start = ModernCheckBox("Read existing lines")
        frow.addWidget(self.path)
        frow.addWidget(browse)
        frow.addWidget(self.from_start)
        self.source_options.addWidget(file_widget)
        demo_caption = QLabel("Synthetic events · normal activity, failures, and recovery")
        demo_caption.setObjectName("subtitle")
        demo_caption.setWordWrap(True)
        self.source_options.addWidget(demo_caption)
        source_row.addWidget(self.source_options, 1)
        self.source.currentIndexChanged.connect(self.source_options.setCurrentIndex)
        layout.addWidget(source_panel)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.metric_labels = {}
        self.metric_cards = {}
        for key, label, note, glyph, color in [
            ("events", "Events analyzed", "Live stream throughput", "pulse", "#b1a2ff"),
            ("alerts", "Anomalies detected", "Signals worth investigating", "alerts", "#ff9cac"),
            ("saved", "Alerts saved", "Persisted to your JSONL file", "save", "#76dfc3"),
            ("delivered", "HTTP delivered", "Accepted by your endpoint", "send", "#83bfff"),
        ]:
            card = MetricCard(label, note, glyph, color)
            cards.addWidget(card, 1)
            self.metric_labels[key] = card.value
            self.metric_cards[key] = card
        layout.addLayout(cards)
        baseline_panel = QWidget()
        baseline_panel.setObjectName("baselinePanel")
        baseline_layout = QVBoxLayout(baseline_panel)
        baseline_layout.setContentsMargins(15, 11, 15, 11)
        baseline_layout.setSpacing(10)
        self.state = QLabel("Ready · choose a source and start monitoring")
        self.state.setObjectName("subtitle")
        baseline_layout.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        baseline_layout.addWidget(self.progress)
        layout.addWidget(baseline_panel)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.currentChanged.connect(self.navigate)
        layout.addWidget(self.tabs, 1)
        logs = QWidget()
        log_layout = QVBoxLayout(logs)
        log_layout.setContentsMargins(16, 17, 16, 15)
        log_layout.setSpacing(14)
        log_heading = QHBoxLayout()
        label = QLabel("Event stream")
        label.setObjectName("sectionTitle")
        log_heading.addWidget(label, 1)
        self.visible_count = QLabel("0 visible events")
        self.visible_count.setObjectName("subtitle")
        log_heading.addWidget(self.visible_count)
        log_layout.addLayout(log_heading)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter messages or services…")
        self.search_action = self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.level = ModernComboBox()
        self.level.addItems(["All levels", "Critical", "Error", "Warning", "Info", "Debug"])
        self.follow = ModernCheckBox("Follow latest")
        self.follow.setChecked(True)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.level)
        filters.addWidget(self.follow)
        log_layout.addLayout(filters)
        self.log_model = RecordModel()
        self.proxy = LogFilter()
        self.proxy.setSourceModel(self.log_model)
        self.log_table = table(self.proxy)
        self.log_content = QStackedWidget()
        self.log_content.addWidget(self.log_table)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        self.empty_icon = QLabel()
        self.empty_icon.setPixmap(icon("pulse", "#a998ff", 48).pixmap(48, 48))
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_icon)
        self.empty_title = QLabel("Your next insight starts here")
        self.empty_title.setObjectName("sectionTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_note = QLabel("Choose a log source and start monitoring to see events in real time.")
        self.empty_note.setObjectName("subtitle")
        self.empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_note.setWordWrap(True)
        empty_layout.addWidget(self.empty_note)
        empty_layout.addStretch()
        self.log_content.addWidget(empty)
        self.log_content.setCurrentIndex(1)
        log_layout.addWidget(self.log_content, 1)
        self.search.textChanged.connect(self.filter_logs)
        self.level.currentTextChanged.connect(self.filter_logs)
        self.tabs.addTab(logs, "Live logs")

        alerts_widget = QWidget()
        alerts_layout = QVBoxLayout(alerts_widget)
        alerts_layout.setContentsMargins(16, 17, 16, 15)
        alerts_layout.setSpacing(14)
        toolbar = QHBoxLayout()
        alerts_title = QLabel("Anomaly inbox")
        alerts_title.setObjectName("sectionTitle")
        toolbar.addWidget(alerts_title, 1)
        export = QPushButton("Export visible alerts…")
        export.clicked.connect(self.export_alerts)
        toolbar.addWidget(export)
        alerts_layout.addLayout(toolbar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.alert_model = RecordModel(alerts=True)
        self.alert_table = table(self.alert_model)
        self.alert_table.setColumnWidth(0, 150)
        self.alert_table.setColumnWidth(2, 60)
        self.alert_table.setColumnWidth(3, 200)
        self.alert_table.selectionModel().selectionChanged.connect(self.show_alert)
        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setFont(QFont("monospace", 11))
        self.json_view.setPlaceholderText("Structured alerts appear here.")
        self.json_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.json_highlighter = JsonHighlighter(self.json_view.document())
        details = QWidget()
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(14, 0, 0, 0)
        detail_layout.setSpacing(12)
        detail_header = QHBoxLayout()
        self.detail_title = QLabel("Alert details")
        self.detail_title.setObjectName("sectionTitle")
        detail_header.addWidget(self.detail_title, 1)
        self.copy_button = QPushButton("Copy JSON")
        self.copy_button.setIcon(icon("copy", "#b3bdd4", 16))
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_alert)
        detail_header.addWidget(self.copy_button)
        detail_layout.addLayout(detail_header)
        self.detail_summary = QLabel("Select an alert to explore the event and its detection reasons.")
        self.detail_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_summary.setObjectName("subtitle")
        self.detail_summary.setWordWrap(True)
        self.detail_summary.setMaximumHeight(70)
        detail_layout.addWidget(self.detail_summary)
        detail_layout.addWidget(self.json_view, 1)
        splitter.addWidget(self.alert_table)
        splitter.addWidget(details)
        splitter.setSizes([590, 530])
        splitter.setChildrenCollapsible(False)
        alerts_layout.addWidget(splitter)
        self.tabs.addTab(alerts_widget, "Alerts · 0")

        settings_page = QWidget()
        settings_page_layout = QVBoxLayout(settings_page)
        settings_page_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        appearance = QGroupBox("Appearance")
        appearance_form = QFormLayout(appearance)
        self.theme_choice = ModernComboBox()
        for title, value in [("Follow system", "system"), ("Light", "light"), ("Dark", "dark")]:
            self.theme_choice.addItem(title, value)
        saved_theme = self.preferences.value("appearance/theme", "system")
        self.theme_choice.setCurrentIndex(max(0, self.theme_choice.findData(saved_theme)))
        appearance_form.addRow("Color theme", self.theme_choice)
        self.appearance_status = QLabel()
        self.appearance_status.setObjectName("subtitle")
        self.appearance_status.setWordWrap(True)
        appearance_form.addRow(self.appearance_status)
        settings_page_layout.addWidget(appearance)
        # Detector/output settings lock during a session; appearance stays editable.
        self.settings = QWidget()
        setting_layout = QVBoxLayout(self.settings)
        setting_layout.setContentsMargins(0, 0, 0, 0)
        setting_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.settings.setMinimumHeight(620)
        detection = QGroupBox("Adaptive detector")
        form = QFormLayout(detection)
        self.warmup = ModernSpinBox()
        self.warmup.setRange(10, 100000)
        self.warmup.setValue(100)
        self.threshold = ModernSpinBox()
        self.threshold.setRange(1, 100)
        self.threshold.setValue(60)
        self.cooldown = ModernSpinBox()
        self.cooldown.setRange(0, 3600)
        self.cooldown.setValue(60)
        self.cooldown.setSuffix(" s")
        form.addRow("Events before novel-template detection", self.warmup)
        form.addRow("Minimum alert score (higher = fewer alerts)", self.threshold)
        form.addRow("Cooldown per message template / spike type", self.cooldown)
        description = QLabel("Known failures trigger immediately. Volume and error-rate checks learn at least six 10-second windows.\nScores indicate heuristic severity, not probability. Starting a session resets its baseline.")
        description.setWordWrap(True)
        form.addRow(description)
        setting_layout.addWidget(detection)
        delivery = QGroupBox("JSON output and HTTP delivery")
        form = QFormLayout(delivery)
        default_output = Path.home() / ".local" / "state" / "logwatch" / "alerts.jsonl"
        self.output = QLineEdit(str(default_output))
        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText("Optional · https://your-server.example/alerts")
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Optional bearer token · held only in memory")
        form.addRow("Local JSON Lines file", self.output)
        form.addRow("POST endpoint", self.endpoint)
        form.addRow("Bearer token", self.token)
        info = QLabel("One JSON object per alert. Local files rotate at 10 MiB with three backups.\nHTTP requests use three attempts and an Idempotency-Key. Closing or stopping cancels pending HTTP delivery.\nAlerts contain raw log text; send them only to an endpoint you trust.")
        info.setWordWrap(True)
        form.addRow(info)
        setting_layout.addWidget(delivery)
        setting_layout.addStretch()
        settings_page_layout.addWidget(self.settings)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        settings_scroll.setWidget(settings_page)
        self.tabs.addTab(settings_scroll, "Settings")

        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(500)
        self.diagnostics.setPlaceholderText("Source changes and delivery errors appear here.")
        self.tabs.addTab(self.diagnostics, "Activity")
        self.footer = QLabel("Bounded history: 3,000 log entries / 500 alerts · full alert history in JSONL")
        self.footer.setObjectName("subtitle")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)
        self.theme_choice.currentIndexChanged.connect(self.choose_theme)
        self.system_theme.changed.connect(self.system_theme_changed)
        self.apply_theme()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        if demo:
            self.source.setCurrentIndex(2)
            QTimer.singleShot(0, self.start_monitoring)

    def navigate(self, index):
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(["Live log explorer", "Anomaly intelligence", "Monitor settings", "Session activity"][index])

    def choose_theme(self):
        self.preferences.setValue("appearance/theme", self.theme_choice.currentData())
        self.preferences.sync()
        if self.preferences.status() != QSettings.Status.NoError:
            self.notify("Could not save appearance preference; the selected theme remains active for this session.")
        self.apply_theme()

    def system_theme_changed(self, theme):
        if self.theme_choice.currentData() == "system":
            self.apply_theme()

    def apply_theme(self):
        choice = self.theme_choice.currentData()
        self.active_theme = self.system_theme.current_theme if choice == "system" else choice
        colors = COLORS[self.active_theme]
        self.setPalette(window_palette(self.active_theme))
        self.setStyleSheet(stylesheet(self.active_theme))
        for key, card in self.metric_cards.items():
            card.set_color(colors[key])
        for model in (self.log_model, self.alert_model):
            model.theme = self.active_theme
            if model.records:
                model.dataChanged.emit(model.index(0, 0), model.index(model.rowCount() - 1, model.columnCount() - 1), [Qt.ItemDataRole.ForegroundRole])
        for button, glyph in zip(self.nav_buttons, ["logs", "alerts", "settings", "activity"]):
            button.setIcon(icon(glyph, colors["control"]))
        self.stop.setIcon(icon("stop", colors["control"], 16))
        self.copy_button.setIcon(icon("copy", colors["control"], 16))
        self.search_action.setIcon(icon("search", colors["muted"]))
        self.empty_icon.setPixmap(icon("pulse", colors["events"], 48).pixmap(48, 48))
        self.json_highlighter.set_theme(self.active_theme)
        self.appearance_status.setText(
            f"Following desktop appearance · {self.active_theme.title()} active. Updates automatically when your desktop reports a theme change."
            if choice == "system" else f"{self.active_theme.title()} is active. This app preference overrides the desktop appearance.")
        self.update()

    def set_badge(self, text, state="idle"):
        if self.status_badge.text() != text or self.status_badge.property("state") != state:
            self.status_badge.setText(text)
            self.status_badge.setProperty("state", state)
            self.status_badge.style().unpolish(self.status_badge)
            self.status_badge.style().polish(self.status_badge)

    def update_log_view(self):
        count = self.proxy.rowCount()
        self.visible_count.setText(f"{count:,} visible events")
        self.log_content.setCurrentIndex(0 if count else 1)
        if self.log_model.records:
            self.empty_title.setText("No matching events")
            self.empty_note.setText("Adjust your search or level filter to explore the event stream.")
        elif self.monitor:
            self.empty_title.setText("Listening for activity")
            self.empty_note.setText("New log events will appear here as your source produces them.")
        else:
            self.empty_title.setText("Your next insight starts here")
            self.empty_note.setText("Choose a log source and start monitoring to see events in real time.")

    def notify(self, message):
        try:
            self.notices.put_nowait(message)
        except queue.Full:
            pass

    def browse_log(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a log file", "/var/log")
        if path:
            self.path.setText(path)

    def filter_logs(self):
        self.proxy.update_filter(self.search.text(), self.level.currentText())
        self.update_log_view()

    def start_monitoring(self):
        if self.monitor:
            return
        kind = ["journal", "file", "demo"][self.source.currentIndex()]
        source = SourceConfig(kind, self.path.text().strip(), self.from_start.isChecked(),
                              self.unit.text().strip(), self.user_journal.isChecked())
        try:
            if kind == "file":
                path = Path(source.path).expanduser()
                if not path.is_file():
                    raise ValueError("Select an existing regular log file")
                with path.open("rb"):
                    pass
            if not self.output.text().strip():
                raise ValueError("Choose an alert output file")
            output_path = Path(self.output.text().strip()).expanduser().resolve()
            if kind == "file":
                log_path = Path(source.path).expanduser().resolve()
                for target in [output_path, *(Path(str(output_path) + f".{i}") for i in range(1, 4))]:
                    if target == log_path or (target.exists() and target.samefile(log_path)):
                        raise ValueError("The monitored log must differ from the alert output and its backups")
            config = DetectorConfig(warmup_events=self.warmup.value(), threshold=self.threshold.value(),
                                    cooldown_seconds=self.cooldown.value())
            sender = AlertSender(DeliveryConfig(str(output_path), self.endpoint.text().strip(), self.token.text()), self.notify)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot start monitoring", str(exc))
            return
        self.sender = sender
        self.monitor = Monitor(source, config, sender)
        self.log_model.clear()
        self.alert_model.clear()
        self.json_view.clear()
        self.detail_title.setText("Alert details")
        self.detail_summary.setText("Select an alert to explore the event and its detection reasons.")
        self.copy_button.setEnabled(False)
        self.nav_buttons[1].setText("Alerts")
        self.previous_counters = {key: 0 for key in self.metric_cards}
        self.last_chart_at = time.monotonic()
        for key, card in self.metric_cards.items():
            card.value.setText("0")
            card.chart.reset()
            card.chart.add(0)
        self.cleanup = None
        self.progress.setRange(0, config.warmup_events)
        self.progress.setValue(0)
        self.source.setEnabled(False)
        self.source_options.setEnabled(False)
        self.settings.setEnabled(False)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.sender.start()
        self.monitor.start()
        self.set_badge("●  LIVE", "live")
        self.update_log_view()
        self.state.setText("Monitoring · learning normal message templates")
        self.notify(f"Started {kind} monitoring; JSON output: {output_path}")

    def stop_monitoring(self):
        if self.monitor:
            self.monitor.stop_event.set()
            self.stop.setEnabled(False)
            self.set_badge("●  STOPPING", "stopping")
            self.state.setText("Stopping monitoring and HTTP delivery…")

    @staticmethod
    def drain(target, count=500):
        items = []
        for _ in range(count):
            try:
                items.append(target.get_nowait())
            except queue.Empty:
                break
        return items

    def poll(self):
        if self.monitor:
            logs = self.drain(self.monitor.ui_events)
            self.log_model.append(logs)
            self.update_log_view()
            if logs and self.follow.isChecked():
                self.log_table.scrollToBottom()
            alerts = self.drain(self.monitor.alert_events)
            self.alert_model.append(alerts)
            if alerts and not self.alert_table.selectionModel().hasSelection():
                self.alert_table.selectRow(0)
            metrics = self.monitor.snapshot()
            delivery = self.sender.snapshot()
            for key in self.metric_labels:
                self.metric_labels[key].setText(f"{(metrics | delivery).get(key, 0):,}")
            current_time = time.monotonic()
            interval = current_time - self.last_chart_at
            if interval >= 1:
                counters = metrics | delivery
                for key, card in self.metric_cards.items():
                    card.chart.add((counters[key] - self.previous_counters.get(key, 0)) / interval)
                self.previous_counters = {key: counters[key] for key in self.metric_cards}
                self.last_chart_at = current_time
            self.nav_buttons[1].setText(f"Alerts  ·  {metrics['alerts']}")
            self.tabs.setTabText(1, f"Alerts · {metrics['alerts']}")
            self.progress.setValue(min(metrics["events"], metrics["warmup_events"]))
            if self.monitor.is_alive() and not self.monitor.stop_event.is_set():
                baseline = "Template baseline active" if metrics["ready"] else f"Learning templates ({metrics['events']}/{metrics['warmup_events']})"
                self.state.setText(f"● Monitoring · {baseline} · {metrics['baseline_windows']} volume baseline windows")
            self.footer.setText(f"{metrics['suppressed']} duplicate alerts suppressed · {metrics['ui_dropped']} display entries skipped · "
                                f"Save failures {delivery['save_failed']} · HTTP pending {delivery['pending']} / failed {delivery['failed']} / not queued {delivery['dropped']}")
            for message in self.drain(self.monitor.messages):
                self.notify(message)
            if not self.monitor.is_alive():
                if not self.cleanup:
                    self.stop.setEnabled(False)
                    self.set_badge("●  STOPPING", "stopping")
                    self.state.setText("Stopping · saved alerts remain in JSONL")
                    self.cleanup = threading.Thread(target=self.sender.close, daemon=True)
                    self.cleanup.start()
                elif not self.cleanup.is_alive() and self.monitor.ui_events.empty() and self.monitor.alert_events.empty():
                    self.monitor = self.sender = self.cleanup = None
                    self.source.setEnabled(True)
                    self.source_options.setEnabled(True)
                    self.settings.setEnabled(True)
                    self.start.setEnabled(True)
                    self.state.setText("Stopped · review Activity for source or delivery errors")
                    self.set_badge("●  STOPPED")
                    self.update_log_view()
                    if self.closing:
                        self.close()
        for message in self.drain(self.notices):
            self.diagnostics.appendPlainText(f"{utc_now()}  {message}")
            self.statusBar().showMessage(message, 15000)

    def show_alert(self):
        rows = self.alert_table.selectionModel().selectedRows()
        if rows:
            alert = self.alert_model.records[rows[0].row()]
            self.json_view.setPlainText(json.dumps(alert, indent=2, ensure_ascii=False))
            self.detail_title.setText(f"{alert['severity'].title()} signal · {alert['score']}/100")
            self.detail_summary.setText(f"{alert['event']['service']}  /  {alert['event']['message'][:240]}")
            self.copy_button.setEnabled(True)
        else:
            self.json_view.clear()
            self.copy_button.setEnabled(False)
            self.detail_title.setText("Alert details")
            self.detail_summary.setText("Select an alert to explore the event and its detection reasons.")

    def copy_alert(self):
        if self.json_view.toPlainText():
            QApplication.clipboard().setText(self.json_view.toPlainText())
            self.statusBar().showMessage("Alert JSON copied to clipboard", 3000)

    def export_alerts(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export displayed alert history", "alerts.jsonl", "JSON Lines (*.jsonl)")
        if path:
            try:
                if self.monitor:
                    output = Path(self.sender.config.output).resolve()
                    target = Path(path).resolve()
                    if target in [output, *(Path(str(output) + f".{i}") for i in range(1, 4))]:
                        raise ValueError("Export to a different file than the active alert output and its backups")
                    if self.monitor.source.kind == "file" and target == Path(self.monitor.source.path).expanduser().resolve():
                        raise ValueError("Export to a different file than the monitored log")
                with open(path, "w", encoding="utf-8") as stream:
                    for record in self.alert_model.records:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                self.notify(f"Exported {len(self.alert_model.records)} displayed alerts to {path}")
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Export failed", str(exc))

    def closeEvent(self, event):
        if self.monitor:
            self.closing = True
            self.stop_monitoring()
            event.ignore()
        else:
            event.accept()


def run_gui(demo=False):
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("LogWatch")
    app.setFont(QFont("DejaVu Sans", 10))
    window = MainWindow(demo=demo)
    window.show()
    return app.exec()
