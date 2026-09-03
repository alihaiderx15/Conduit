
from __future__ import annotations

import math
import random
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .theme import BG, PANEL, BORDER, BLUE, CYAN, PURPLE, YELLOW, GREEN, RED, TEXT, MUTED


class Panel(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(8, 3, 8, 3)
        self.outer.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(5)
        marker = QLabel("›")
        marker.setStyleSheet(f"color:{PURPLE}; font-weight:900;")
        title_label = QLabel(title.upper())
        title_label.setObjectName("panelTitle")
        header.addWidget(marker)
        header.addWidget(title_label)
        header.addStretch(1)
        self.header_right = QLabel("")
        self.header_right.setStyleSheet(f"color:{PURPLE};")
        header.addWidget(self.header_right)
        self.outer.addLayout(header)

        self.body = QWidget()
        self.body.setStyleSheet("background: transparent; border: none;")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(3)
        self.outer.addWidget(self.body, 1)


class LogoMark(QWidget):
    """Small painted 'loading ring' emblem used for the brand mark and
    title-bar icon, mirroring the reference Conduit identity mark."""

    def __init__(self, size: int = 22, color: str = YELLOW, parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._angle = 0.0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._spin)
        self._timer.start(70)

    def _spin(self) -> None:
        self._angle = (self._angle + 3.2) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 2

        segments = 8
        for i in range(segments):
            a0 = self._angle + i * (360 / segments)
            fade = 90 + int(165 * (i / segments))
            color = QColor(self._color)
            color.setAlpha(fade)
            pen = QPen(color, max(1.6, r * 0.22))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            span = int((360 / segments) * 0.62 * 16)
            painter.drawArc(
                QRectF(cx - r, cy - r, r * 2, r * 2),
                int(a0 * 16),
                span,
            )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._color))
        core_r = r * 0.30
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)


class CircuitTrace(QWidget):
    """Decorative circuit-style connector line used flanking the header
    subtitle, echoing the reference mock-up's HUD detailing."""

    def __init__(self, direction: str = "right", color: str = PURPLE, parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._direction = direction
        self.setFixedHeight(14)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy = h / 2
        pen = QPen(self._color, 1.3)
        painter.setPen(pen)
        flip = self._direction == "left"
        x0, x1 = (w, 0) if flip else (0, w)
        mid = x0 + (x1 - x0) * 0.55
        step = x0 + (x1 - x0) * 0.78
        painter.drawLine(QPointF(x0, cy), QPointF(mid, cy))
        painter.drawLine(QPointF(mid, cy), QPointF(step, cy - 5))
        painter.drawLine(QPointF(step, cy - 5), QPointF(x1, cy - 5))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QPointF(mid, cy), 2.6, 2.6)
        painter.drawEllipse(QPointF(x1, cy - 5), 2.2, 2.2)


class InfoTable(QFrame):
    """Label/value rows with fine divider lines, matching the System Info
    styling from the reference mock-up."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame{background:#04101C;border:1px solid #172A4B;border-radius:3px;}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 3, 10, 3)
        self._layout.setSpacing(0)
        self._rows: list[tuple[QLabel, QLabel, QFrame]] = []

    def set_rows(self, pairs: list[tuple[str, str]]) -> None:
        # Grow the row pool as needed, then reuse widgets on refresh so this
        # stays cheap to call from the 1s system-monitor timer.
        while len(self._rows) < len(pairs):
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            label = QLabel()
            label.setStyleSheet(f"color:{MUTED}; font-size:9px; letter-spacing:1px;")
            value = QLabel()
            value.setAlignment(Qt.AlignRight)
            value.setStyleSheet(f"color:{TEXT}; font-size:9px; font-weight:600;")
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(value)
            divider = QFrame()
            divider.setFixedHeight(1)
            divider.setStyleSheet("background:#152540; border:none;")
            wrap = QVBoxLayout()
            wrap.setContentsMargins(0, 0, 0, 0)
            wrap.setSpacing(0)
            wrap.addLayout(row)
            wrap.addWidget(divider)
            container = QFrame()
            container.setLayout(wrap)
            self._layout.addWidget(container)
            self._rows.append((label, value, divider))
        for idx, (key, val) in enumerate(pairs):
            label, value, divider = self._rows[idx]
            label.setText(key.upper())
            value.setText(str(val))
            divider.setVisible(idx < len(pairs) - 1)
        for idx in range(len(pairs), len(self._rows)):
            label, value, divider = self._rows[idx]
            label.parentWidget().setVisible(False)


class MetricCard(QFrame):
    def __init__(self, name: str, accent: str = BLUE, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet(
            "QFrame#metricCard{background:#04101C;border:1px solid #172A4B;border-radius:3px;}"
            f"QFrame#metricCard:hover{{border-color:{accent};}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(3)

        top = QHBoxLayout()
        self.name = QLabel(name.upper())
        self.name.setStyleSheet(f"color:{CYAN}; font-weight:700;")
        self.value = QLabel("0%")
        self.value.setStyleSheet(f"color:{TEXT}; font-weight:700;")
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.value)
        layout.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:#020812;border:1px solid #162541;border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{accent};border-radius:2px;}}"
        )
        layout.addWidget(self.bar)

        self.detail = QLabel("")
        self.detail.setAlignment(Qt.AlignRight)
        self.detail.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        layout.addWidget(self.detail)

    def set_metric(self, value: float, detail: str = "") -> None:
        safe = max(0, min(int(round(value)), 100))
        self.bar.setValue(safe)
        self.value.setText(f"{safe}%")
        self.detail.setText(detail)


class Sparkline(QWidget):
    def __init__(self, accent: str = CYAN, parent=None) -> None:
        super().__init__(parent)
        self.values = deque([0.0] * 48, maxlen=48)
        self.accent = QColor(accent)
        self.setMinimumHeight(32)

    def add_value(self, value: float) -> None:
        self.values.append(float(value))
        self.update()

    def paintEvent(self, event) -> None:
        if len(self.values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.accent, 1.2))
        w = max(1, self.width() - 2)
        h = max(1, self.height() - 4)
        points = []
        for i, value in enumerate(self.values):
            x = 1 + (i / (len(self.values) - 1)) * w
            y = 2 + h - (max(0.0, min(value, 100.0)) / 100.0) * h
            points.append(QPointF(x, y))
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)


class GraphMetricCard(QFrame):
    """Metric card rendered as a live sparkline with axis labels, matching
    the CPU Usage treatment from the reference mock-up."""

    def __init__(self, name: str, accent: str = CYAN, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet(
            "QFrame#metricCard{background:#04101C;border:1px solid #172A4B;border-radius:3px;}"
            f"QFrame#metricCard:hover{{border-color:{accent};}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(2)

        top = QHBoxLayout()
        self.name = QLabel(name.upper())
        self.name.setStyleSheet(f"color:{CYAN}; font-weight:700;")
        self.value = QLabel("0%")
        self.value.setStyleSheet(f"color:{TEXT}; font-weight:700; font-size:13px;")
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.value)
        layout.addLayout(top)

        graph_row = QHBoxLayout()
        graph_row.setSpacing(4)
        axis = QVBoxLayout()
        axis.setSpacing(0)
        self._axis_top = QLabel("100%")
        self._axis_top.setStyleSheet(f"color:{MUTED}; font-size:7px;")
        self._axis_bottom = QLabel("0%")
        self._axis_bottom.setStyleSheet(f"color:{MUTED}; font-size:7px;")
        axis.addWidget(self._axis_top)
        axis.addStretch(1)
        axis.addWidget(self._axis_bottom)
        graph_row.addLayout(axis)

        self.spark = Sparkline(accent=accent)
        self.spark.setMinimumHeight(26)
        graph_row.addWidget(self.spark, 1)
        layout.addLayout(graph_row)

        self.detail = QLabel("")
        self.detail.setAlignment(Qt.AlignRight)
        self.detail.setStyleSheet(f"color:{MUTED}; font-size:9px;")
        layout.addWidget(self.detail)

    def set_metric(self, value: float, detail: str = "") -> None:
        safe = max(0, min(int(round(value)), 100))
        self.value.setText(f"{safe}%")
        self.detail.setText(detail)
        self.spark.add_value(safe)


class NetworkCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet(
            "QFrame#metricCard{background:#04101C;border:1px solid #172A4B;border-radius:3px;}"
            f"QFrame#metricCard:hover{{border-color:{CYAN};}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        top = QHBoxLayout()
        title = QLabel("NETWORK")
        title.setStyleSheet(f"color:{CYAN}; font-weight:700;")
        self.value = QLabel("0 KB/s")
        self.value.setStyleSheet(f"color:{CYAN}; font-weight:700;")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.value)
        layout.addLayout(top)
        self.spark = Sparkline()
        layout.addWidget(self.spark)

    def set_rate(self, kb_s: float) -> None:
        if kb_s >= 1024:
            text = f"{kb_s/1024:.1f} MB/s"
        else:
            text = f"{kb_s:.1f} KB/s"
        self.value.setText(text)
        # Compress to a useful visual 0..100 scale.
        visual = min(100.0, math.log10(max(1.0, kb_s) + 1) * 28.0)
        self.spark.add_value(visual)


class HudCore(QWidget):
    """Animated central Conduit HUD inspired by the approved reference mock-up."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.angle = 0.0
        self.processing = False
        self.status_text = "LISTENING..."
        self.wave = deque([0.15] * 54, maxlen=54)
        # Never force the whole window to a desktop-sized minimum. The HUD
        # paints itself from the current widget dimensions and scales cleanly.
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Fixed-seed starfield so the scattered accent dots stay stable
        # between repaints instead of jittering every frame.
        rng = random.Random(7)
        star_colors = [CYAN, PURPLE, YELLOW, BLUE]
        self._stars = [
            (rng.random(), rng.random(), rng.choice(star_colors), rng.uniform(0.9, 2.3), rng.uniform(60, 200))
            for _ in range(46)
        ]

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(55)

    def set_processing(self, active: bool) -> None:
        self.processing = bool(active)
        self.status_text = "PROCESSING..." if active else "LISTENING..."
        self.update()

    def set_status(self, text: str) -> None:
        self.status_text = text.upper()
        self.update()

    def _tick(self) -> None:
        self.angle = (self.angle + (1.9 if self.processing else 0.7)) % 360
        baseline = 0.72 if self.processing else 0.28
        self.wave.append(max(0.05, min(1.0, random.uniform(baseline * 0.35, baseline))))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(BG))

        w, h = self.width(), self.height()
        cx, cy = w * 0.5, h * 0.49
        radius = min(w * 0.32, h * 0.38)

        # Subtle cyber grid.
        grid_pen = QPen(QColor(10, 55, 92, 90), 1)
        painter.setPen(grid_pen)
        for x in range(18, w, 38):
            painter.drawLine(x, 12, x, h - 24)
        for y in range(18, h, 38):
            painter.drawLine(12, y, w - 12, y)

        # Scattered accent starfield behind the rings, echoing the reference
        # mock-up's ambient particle field.
        painter.setPen(Qt.NoPen)
        for fx, fy, color, size, alpha in self._stars:
            qc = QColor(color)
            qc.setAlpha(int(alpha))
            painter.setBrush(QBrush(qc))
            painter.drawEllipse(QPointF(fx * w, fy * h), size, size)

        # Corner tick marks for a HUD-panel feel.
        tick_pen = QPen(QColor(60, 140, 220, 130), 1)
        painter.setPen(tick_pen)
        tick = 14
        for ox, oy, dx, dy in ((12, 12, 1, 1), (w - 12, 12, -1, 1), (12, h - 12, 1, -1), (w - 12, h - 12, -1, -1)):
            painter.drawLine(ox, oy, ox + tick * dx, oy)
            painter.drawLine(ox, oy, ox, oy + tick * dy)

        # Horizontal + vertical signal crosshair and side nodes.
        painter.setPen(QPen(QColor(CYAN), 1))
        painter.drawLine(18, int(cy), w - 18, int(cy))
        faint_v = QPen(QColor(0, 200, 255, 55), 1)
        painter.setPen(faint_v)
        painter.drawLine(int(cx), 12, int(cx), h - 24)
        painter.setBrush(QBrush(QColor(YELLOW)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx - radius - 30, cy), 4, 4)
        painter.drawEllipse(QPointF(cx + radius + 30, cy), 4, 4)

        # Dotted outer rings for extra depth beneath the solid arcs.
        for dr, color in ((radius * 1.24, QColor(PURPLE)), (radius * 1.34, QColor(BLUE))):
            dot_pen = QPen(color, 1.1)
            dot_pen.setStyle(Qt.DotLine)
            painter.setPen(dot_pen)
            painter.setBrush(Qt.NoBrush)
            rect = QRectF(cx - dr, cy - dr, dr * 2, dr * 2)
            painter.drawEllipse(rect)

        # Concentric rings.
        ring_specs = [
            (radius * 1.13, QColor(BLUE), 1.0),
            (radius, QColor(PURPLE), 1.6),
            (radius * .86, QColor(BLUE), 1.2),
            (radius * .72, QColor(CYAN), 1.0),
            (radius * .58, QColor(BLUE), 1.2),
            (radius * .43, QColor(PURPLE), 1.0),
        ]
        for idx, (r, color, width) in enumerate(ring_specs):
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color, width))
            rect = QRectF(cx - r, cy - r, r * 2, r * 2)
            start = int((self.angle * (1 if idx % 2 == 0 else -1) + idx * 24) * 16)
            span = int((225 if idx % 2 == 0 else 145) * 16)
            painter.drawArc(rect, start, span)
            painter.drawArc(rect, start + int(190 * 16), int(75 * 16))

        # Tiny radial ticks.
        painter.setPen(QPen(QColor(30, 130, 220, 150), 1))
        for deg in range(0, 360, 12):
            a = math.radians(deg + self.angle * 0.2)
            r1 = radius * 1.04
            r2 = radius * 1.09
            painter.drawLine(
                QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                QPointF(cx + math.cos(a) * r2, cy + math.sin(a) * r2),
            )

        # Core glow.
        grad = QLinearGradient(cx - radius * .38, cy, cx + radius * .38, cy)
        grad.setColorAt(0, QColor(0, 38, 80, 230))
        grad.setColorAt(.5, QColor(3, 22, 48, 245))
        grad.setColorAt(1, QColor(20, 16, 65, 230))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(BLUE), 1.5))
        core_r = radius * .38
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

        font = QFont("Bahnschrift", max(15, int(radius * .10)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(BLUE))
        painter.drawText(
            QRectF(cx - core_r, cy - 25, core_r * 2, 50),
            Qt.AlignCenter,
            "CONDUIT",
        )

        painter.setPen(QColor(CYAN))
        small = QFont("Cascadia Mono", max(7, int(radius * .035)))
        painter.setFont(small)
        painter.drawText(QRectF(20, cy - 22, 120, 44), Qt.AlignCenter, "PROCESSING\n100%" if self.processing else "PROCESSING\nREADY")
        painter.drawText(QRectF(w - 140, cy - 22, 120, 44), Qt.AlignCenter, "SYSTEM\nONLINE")

        # Status.
        painter.setFont(QFont("Cascadia Mono", 11, QFont.Bold))
        painter.setPen(QColor(YELLOW))
        painter.drawText(QRectF(0, h - 70, w, 24), Qt.AlignCenter, self.status_text)

        # Audio-style waveform.
        values = list(self.wave)
        total_w = min(w * .52, 390)
        left = cx - total_w / 2
        bar_w = total_w / len(values)
        base_y = h - 28
        for i, value in enumerate(values):
            height = 4 + value * 25
            color = QColor(CYAN if i % 5 else BLUE)
            painter.fillRect(
                QRectF(left + i * bar_w, base_y - height, max(2.0, bar_w - 1.5), height),
                color,
            )


class StatusDot(QWidget):
    def __init__(self, color: str = GREEN, parent=None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(14, 14)

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(3, 3, 8, 8)


class StatField(QWidget):
    """One label/value stat used inside the two-column Conduit Status grid."""

    def __init__(self, label: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        cap = QLabel(label.upper())
        cap.setStyleSheet(f"color:{MUTED}; font-size:9px; letter-spacing:1px;")
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color:{TEXT}; font-size:10px; font-weight:700;")
        layout.addWidget(cap)
        layout.addWidget(self.value_label)

    def set_value(self, value: str, color: str | None = None) -> None:
        self.value_label.setText(value)
        if color:
            self.value_label.setStyleSheet(f"color:{color}; font-size:10px; font-weight:700;")


class StatusGrid(QWidget):
    """Two-column status readout matching the reference Conduit Status card."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)

        self.status_field = StatField("Status", "STARTING")
        self.ai_field = StatField("AI Assistant", "—")
        self.version_field = StatField("Version", "—")
        self.link_field = StatField("Conduit Link", "OFFLINE")

        grid.addWidget(self.status_field, 0, 0)
        grid.addWidget(self.ai_field, 0, 1)
        grid.addWidget(self.version_field, 1, 0)
        grid.addWidget(self.link_field, 1, 1)
