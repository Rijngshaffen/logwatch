"""Native Qt visuals; all activity charts reflect actual session counters."""
from collections import deque
import re

from PyQt6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QCheckBox, QComboBox, QLabel, QHBoxLayout, QSpinBox, QStyle, QStyleOptionButton, QStyleOptionComboBox, QStyleOptionSpinBox, QStyledItemDelegate, QVBoxLayout, QWidget
from .themes import COLORS, theme_color


PATHS = {
    "pulse": '<path d="M2 12h4l3-8 6 16 3-8h4"/>',
    "logs": '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "alerts": '<path d="m12 3 10 17H2Z"/><path d="M12 9v4M12 16h.01"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
    "activity": '<path d="M5 4v16h16M8 15l4-5 4 3 5-7"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4Z M22 2 11 13"/>',
    "play": '<path d="m8 5 11 7-11 7Z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
}


def icon(name, color="#a4adc4", size=20):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class ModernComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                          QStyle.SubControl.SC_ComboBoxArrow, self)
        x, y = rect.center().x(), rect.center().y()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme_color(self, "control" if self.isEnabled() else "disabled")), 1.5))
        painter.drawPolyline(QPolygonF([QPointF(x - 3, y - 1), QPointF(x, y + 2), QPointF(x + 3, y - 1)]))


class ModernCheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff" if self.isEnabled() else theme_color(self, "disabled_check")), 1.7))
        x, y = rect.center().x(), rect.center().y()
        painter.drawPolyline(QPolygonF([QPointF(x - 4, y), QPointF(x - 1, y + 3), QPointF(x + 4, y - 3)]))


class ModernSpinBox(QSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme_color(self, "control" if self.isEnabled() else "disabled")), 1.4))
        for control, direction in [(QStyle.SubControl.SC_SpinBoxUp, -1), (QStyle.SubControl.SC_SpinBoxDown, 1)]:
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, control, self)
            x, y = rect.center().x(), rect.center().y()
            painter.drawPolyline(QPolygonF([QPointF(x - 3, y - direction), QPointF(x, y + direction * 2), QPointF(x + 3, y - direction)]))


class Sparkline(QWidget):
    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.values = deque(maxlen=40)
        self.setFixedHeight(34)
        self.setToolTip("Change in this counter per second, during the current session")

    def add(self, value):
        self.values.append(max(0, value))
        self.update()

    def reset(self):
        self.values.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bottom = self.height() - 3
        painter.setPen(QPen(QColor(theme_color(self, "chart_grid")), 1, Qt.PenStyle.DashLine))
        painter.drawLine(0, bottom, self.width(), bottom)
        if len(self.values) < 2:
            return
        maximum = max(1, max(self.values))
        step = self.width() / (self.values.maxlen - 1)
        start = self.width() - step * (len(self.values) - 1)
        line = QPainterPath()
        for i, value in enumerate(self.values):
            x, y = start + i * step, bottom - value / maximum * (bottom - 4)
            if i == 0:
                line.moveTo(x, y)
            else:
                line.lineTo(x, y)
        fill = QPainterPath(line)
        fill.lineTo(self.width(), bottom)
        fill.lineTo(start, bottom)
        fill.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, bottom)
        top = QColor(self.color)
        top.setAlpha(65)
        transparent = QColor(self.color)
        transparent.setAlpha(0)
        gradient.setColorAt(0, top)
        gradient.setColorAt(1, transparent)
        painter.fillPath(fill, gradient)
        painter.setPen(QPen(self.color, 1.8))
        painter.drawPath(line)


class MetricCard(QWidget):
    def __init__(self, title, note, glyph, color):
        super().__init__()
        self.setObjectName("metricCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(8)
        row = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("cardHeading")
        row.addWidget(heading, 1)
        self.mark = QLabel()
        self.glyph = glyph
        self.mark.setPixmap(icon(glyph, color, 18).pixmap(QSize(18, 18)))
        row.addWidget(self.mark)
        layout.addLayout(row)
        self.value = QLabel("0")
        self.value.setObjectName("metric")
        self.value.setStyleSheet(f"color: {color};")
        layout.addWidget(self.value)
        caption = QLabel(note)
        caption.setObjectName("cardNote")
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.chart = Sparkline(color)
        layout.addWidget(self.chart)

    def set_color(self, color):
        self.value.setStyleSheet(f"color: {color};")
        self.mark.setPixmap(icon(self.glyph, color, 18).pixmap(QSize(18, 18)))
        self.chart.color = QColor(color)
        self.chart.update()


class SeverityDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Let Qt paint selection/focus first, then replace the level text with a pill.
        base = type(option)(option)
        self.initStyleOption(base, index)
        text = base.text
        base.text = ""
        style = option.widget.style()
        from PyQt6.QtWidgets import QStyle
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, base, painter, option.widget)
        colors = {"CRITICAL": ("#3b2030", "#ff8da1"), "ERROR": ("#3b2030", "#ff8da1"),
                  "HIGH": ("#3d3022", "#ffc780"), "MEDIUM": ("#3d3022", "#ffc780"),
                  "WARNING": ("#3d3022", "#ffc780"), "INFO": ("#183536", "#72dfc4"),
                  "DEBUG": ("#282d46", "#aeb9f3")}
        if getattr(option.widget.window(), "active_theme", "dark") == "light":
            colors = {"CRITICAL": ("#ffe4ea", "#a32d4c"), "ERROR": ("#ffe4ea", "#a32d4c"),
                      "HIGH": ("#fff0d6", "#89560b"), "MEDIUM": ("#fff0d6", "#89560b"),
                      "WARNING": ("#fff0d6", "#89560b"), "INFO": ("#daf4e8", "#166c52"),
                      "DEBUG": ("#e9e5ff", "#6546ae")}
        background, foreground = colors.get(text, ("#282d46", "#b5bdd4"))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = option.font
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        width = min(option.rect.width() - 12, painter.fontMetrics().horizontalAdvance(text) + 18)
        pill = QRectF(option.rect.left() + 7, option.rect.center().y() - 10, width, 21)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(pill, 6, 6)
        painter.setPen(QColor(foreground))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class JsonHighlighter(QSyntaxHighlighter):
    theme = "dark"

    def set_theme(self, theme):
        self.theme = theme
        self.rehighlight()

    def highlightBlock(self, text):
        # JSON strings may contain escaped quotes; process strings before literals.
        spans = []
        for match in re.finditer(r'"(?:[^"\\]|\\.)*"', text):
            color = COLORS[self.theme]["key" if text[match.end():].lstrip().startswith(":") else "string"]
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self.setFormat(match.start(), match.end() - match.start(), fmt)
            spans.append((match.start(), match.end()))
        for match in re.finditer(r"\b(?:true|false|null|-?\d+(?:\.\d+)?)\b", text):
            if not any(start <= match.start() < end for start, end in spans):
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(COLORS[self.theme]["literal"]))
                self.setFormat(match.start(), match.end() - match.start(), fmt)
