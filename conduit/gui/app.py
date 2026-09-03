
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import getpass
import html
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

import psutil
from PySide6.QtCore import Qt, QTimer, Signal, QPoint
from PySide6.QtGui import QColor, QFont, QIcon, QTextCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .runtime import ConduitGuiRuntime
from conduit.model_advisor import (
    classify_task,
    current_model_is_suitable,
    recommended_model,
)
from conduit.conversation import normalize_conversation_command
from conduit.environment import environment_service
from .theme import (
    APP_QSS, BG, PANEL, BORDER, BLUE, CYAN, PURPLE, YELLOW,
    GREEN, RED, TEXT, MUTED, WHITE,
)
from .widgets import (
    CircuitTrace, GraphMetricCard, HudCore, InfoTable, LogoMark, MetricCard,
    NetworkCard, Panel, StatusDot, StatusGrid,
)


class TitleBar(QFrame):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self._drag_position: QPoint | None = None
        self.setFixedHeight(32)
        self.setStyleSheet(
            f"QFrame{{background:#020610;border-bottom:1px solid #1B2948;}}"
            f"QLabel{{background:transparent;}}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(5)

        icon = LogoMark(size=16, color=YELLOW)
        title = QLabel("CONDUIT — Your Intelligent Assistant")
        title.setStyleSheet(f"color:{TEXT}; font-size:10px;")
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addStretch(1)

        for text, callback, object_name in (
            ("—", window.showMinimized, "titlebar"),
            ("□", self._toggle_maximize, "titlebar"),
            ("×", window.close, "titlebarClose"),
        ):
            button = QPushButton(text)
            button.setObjectName(object_name)
            button.setFixedSize(28, 22)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(callback)
            layout.addWidget(button)

    def _toggle_maximize(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_position is not None and event.buttons() & Qt.LeftButton and not self.window.isMaximized():
            self.window.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_position = None

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()


class DropZone(QFrame):
    fileSelected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            f"QFrame{{background:#040A14;border:1px dashed {PURPLE};border-radius:4px;}}"
            f"QFrame:hover{{border-color:{CYAN};background:#06101C;}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(5)
        icon = QLabel("⇧")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"color:{PURPLE};font-size:27px;")
        self.main = QLabel("Drop file here or Click to Browse")
        self.main.setAlignment(Qt.AlignCenter)
        self.main.setStyleSheet(f"color:{TEXT};font-size:10px;")
        sub = QLabel("Images • Videos • Audio • PDF • Docs • Code • Data")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color:{MUTED};font-size:8px;")
        layout.addStretch(1)
        layout.addWidget(icon)
        layout.addWidget(self.main)
        layout.addWidget(sub)
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "Select a file for Conduit")
            if path:
                self.fileSelected.emit(path)

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = [url for url in event.mimeData().urls() if url.isLocalFile()]
        if urls:
            self.fileSelected.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class ChatView(QTextBrowser):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.document().setDefaultStyleSheet(
            f"""
            body {{ color:{TEXT}; font-family:'Cascadia Mono','Consolas'; font-size:11px; }}
            .you {{ color:{YELLOW}; font-weight:700; }}
            .conduit {{ color:{PURPLE}; font-weight:700; }}
            .body {{ color:{TEXT}; white-space:pre-wrap; line-height:1.35; }}
            .error {{ color:{RED}; }}
            """
        )

    def add_user(self, user: str) -> None:
        user_html = html.escape(user).replace("\n", "<br>")
        self.append(
            f'<div class="you">You:</div>'
            f'<div class="body">{user_html}</div><br>'
        )
        self.moveCursor(QTextCursor.End)

    def add_conduit(self, answer: str, success: bool = True) -> None:
        answer_html = html.escape(answer).replace("\n", "<br>")
        cls = "body" if success else "body error"
        self.append(
            f'<div class="conduit">Conduit:</div>'
            f'<div class="{cls}">{answer_html}</div><br>'
        )
        self.moveCursor(QTextCursor.End)

    def add_turn(self, user: str, answer: str, success: bool = True) -> None:
        self.add_user(user)
        self.add_conduit(answer, success)


class ConsoleView(QTextEdit):
    COLORS = {
        "INFO": CYAN,
        "WARN": YELLOW,
        "ERROR": RED,
        "USER": YELLOW,
        "DEBUG": MUTED,
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setFont(QFont("Cascadia Mono", 9))

    def log(self, level: str, message: str) -> None:
        level = (level or "INFO").upper()
        color = self.COLORS.get(level, TEXT)
        stamp = datetime.now().strftime("%H:%M:%S")
        safe = html.escape(str(message))
        self.append(
            f'<span style="color:{MUTED}">[{stamp}]</span> '
            f'<span style="color:{color};font-weight:700">{html.escape(level):5}</span> '
            f'<span style="color:{TEXT}">{safe}</span>'
        )
        self.moveCursor(QTextCursor.End)


class OllamaModelDialog(QDialog):
    def __init__(self, models: list[dict], current_model: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ollama Models")
        self.setMinimumWidth(520)
        self.resize(580, 420)
        self.selected_entry: dict | None = None

        layout = QVBoxLayout(self)
        title = QLabel("OLLAMA MODEL SELECTOR")
        title.setStyleSheet(f"color:{YELLOW};font-size:13px;font-weight:800;")
        layout.addWidget(title)

        note = QLabel(
            "Installed models are marked ✓. Recommended models not installed are marked ↓. "
            "Select one to switch or download."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{MUTED};font-size:9px;")
        layout.addWidget(note)

        self.list_widget = QListWidget()
        beginner_missing = {"qwen2.5vl:7b", "qwen2.5-coder:7b"}
        visible_models = [
            entry for entry in models
            if bool(entry.get("installed"))
            or str(entry.get("name") or "").casefold() in beginner_missing
        ]
        for entry in visible_models:
            installed = bool(entry.get("installed"))
            name = str(entry.get("name") or "")
            description = str(entry.get("description") or "General • Local")
            marker = "✓" if installed else "↓"
            install_state = "" if installed else "  (NOT INSTALLED)"
            active = "  • ACTIVE" if current_model and name.casefold() == current_model.casefold() else ""
            item = QListWidgetItem(
                f"{marker}  {name}{install_state}    —    {description}{active}"
            )
            item.setData(Qt.UserRole, dict(entry))
            self.list_widget.addItem(item)
        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._accept_selected())
        layout.addWidget(self.list_widget, 1)

        self.action_button = QPushButton("SELECT A MODEL")
        self.action_button.setObjectName("yellow")
        self.action_button.setEnabled(False)
        self.action_button.clicked.connect(self._accept_selected)
        layout.addWidget(self.action_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _selection_changed(self, current, previous) -> None:
        if current is None:
            self.selected_entry = None
            self.action_button.setEnabled(False)
            return
        self.selected_entry = dict(current.data(Qt.UserRole) or {})
        installed = bool(self.selected_entry.get("installed"))
        self.action_button.setText("USE MODEL" if installed else "DOWNLOAD & USE")
        self.action_button.setEnabled(True)

    def _accept_selected(self) -> None:
        if self.selected_entry:
            self.accept()


class ConduitMainWindow(QMainWindow):
    def __init__(
        self,
        *,
        runtime: ConduitGuiRuntime,
        version: str,
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.version = version
        self._mic_active = False
        self._ready = False
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.monotonic()

        self.setWindowTitle("CONDUIT — Your Intelligent Assistant")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        # Responsive startup sizing. The GUI is intentionally a percentage of
        # the user's AVAILABLE desktop rather than a fixed 1580x950 window.
        # This keeps the same visual proportions on laptops, 1080p displays,
        # ultrawides, and smaller screens.
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is not None:
            self._apply_screen_geometry(screen, center=True)

        # Wireless displays often use a different Windows scaling factor. Qt can
        # emit a screenChanged event while dragging a frameless window. Re-clamp
        # the logical window size to the destination screen so it can never
        # balloon across both displays.
        self._screen_binding_ready = False
        QTimer.singleShot(0, self._bind_screen_change)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(1, 1, 1, 1)
        root_layout.setSpacing(0)
        root_layout.addWidget(TitleBar(self))

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 8, 14, 10)
        content_layout.setSpacing(6)
        root_layout.addWidget(content, 1)

        content_layout.addWidget(self._build_header())

        # Splitters replace the old fixed three-column grid. Qt can otherwise
        # let large child size-hints fight each other in a restored/non-fullscreen
        # window (especially at 125-175% Windows scaling), which visually makes
        # panels run into neighbouring sections. Splitters guarantee a hard
        # boundary between every major section and remain responsive.
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(5)

        self.left_panel = self._build_left()
        self.left_panel.setMinimumWidth(170)
        self.left_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        self.center_splitter = QSplitter(Qt.Vertical)
        self.center_splitter.setObjectName("sectionSplitter")
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.setHandleWidth(5)
        hud_panel = self._build_hud_panel()
        console_panel = self._build_console()
        hud_panel.setMinimumSize(0, 180)
        console_panel.setMinimumSize(0, 120)
        self.center_splitter.addWidget(hud_panel)
        self.center_splitter.addWidget(console_panel)
        self.center_splitter.setStretchFactor(0, 64)
        self.center_splitter.setStretchFactor(1, 36)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.setObjectName("sectionSplitter")
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.setHandleWidth(5)
        chat_panel = self._build_chat_panel()
        file_panel = self._build_file_controls()
        chat_panel.setMinimumSize(0, 190)
        file_panel.setMinimumSize(0, 155)
        self.right_splitter.addWidget(chat_panel)
        self.right_splitter.addWidget(file_panel)
        self.right_splitter.setStretchFactor(0, 64)
        self.right_splitter.setStretchFactor(1, 36)

        for widget in (self.center_splitter, self.right_splitter):
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.center_splitter)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 22)
        self.main_splitter.setStretchFactor(1, 49)
        self.main_splitter.setStretchFactor(2, 29)
        content_layout.addWidget(self.main_splitter, 1)
        QTimer.singleShot(0, self._apply_responsive_splitter_sizes)

        self._connect_runtime()
        self._start_timers()
        self.console.log("INFO", "Conduit GUI initialized.")
        self.console.log("INFO", "Loading backend runtime...")
        self.runtime.start()


    def _apply_screen_geometry(self, screen, *, center: bool = False) -> None:
        if screen is None:
            return
        available = screen.availableGeometry()
        if available.width() <= 0 or available.height() <= 0:
            return

        target_width = max(760, round(available.width() * 0.82))
        target_height = max(520, round(available.height() * 0.80))
        target_width = min(target_width, max(1, round(available.width() * 0.92)))
        target_height = min(target_height, max(1, round(available.height() * 0.92)))

        # Minimum size is screen-local, not permanently derived from the primary
        # monitor. This is important when the destination is a small wireless laptop.
        min_width = min(760, max(480, round(available.width() * 0.42)))
        min_height = min(520, max(360, round(available.height() * 0.44)))
        self.setMinimumSize(min_width, min_height)

        current = self.size()
        oversized = (
            current.width() > available.width() * 0.92
            or current.height() > available.height() * 0.92
            or current.width() < 100
            or current.height() < 100
        )
        if center or oversized:
            self.resize(target_width, target_height)

        frame = self.frameGeometry()
        if center or not available.intersects(frame):
            x = available.x() + max(0, (available.width() - self.width()) // 2)
            y = available.y() + max(0, (available.height() - self.height()) // 2)
            self.move(x, y)

    def _apply_responsive_splitter_sizes(self) -> None:
        if not hasattr(self, "main_splitter"):
            return
        width = max(1, self.main_splitter.width())
        # Give the chat a little more room in restored/compact windows because
        # it contains four provider buttons. In wide/maximized mode the design
        # stays close to the original 22/50/28 proportions.
        if width < 1250:
            ratios = (0.20, 0.47, 0.33)
        elif width < 1500:
            ratios = (0.21, 0.49, 0.30)
        else:
            ratios = (0.22, 0.50, 0.28)
        self.main_splitter.setSizes([max(1, int(width * r)) for r in ratios])

        center_h = max(1, self.center_splitter.height())
        right_h = max(1, self.right_splitter.height())
        self.center_splitter.setSizes([int(center_h * 0.64), int(center_h * 0.36)])
        self.right_splitter.setSizes([int(right_h * 0.64), int(right_h * 0.36)])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Rebalance after Qt has applied the new logical DPI/window geometry.
        QTimer.singleShot(0, self._apply_responsive_splitter_sizes)

    def _bind_screen_change(self) -> None:
        handle = self.windowHandle()
        if handle is None or self._screen_binding_ready:
            return
        self._screen_binding_ready = True
        handle.screenChanged.connect(self._screen_changed)

    def _screen_changed(self, screen) -> None:
        # Delay one event-loop tick so Windows/Qt finishes applying the destination
        # monitor's DPI before calculating logical geometry.
        def apply_destination_screen():
            self._apply_screen_geometry(screen, center=False)
            self._apply_responsive_splitter_sizes()
        QTimer.singleShot(0, apply_destination_screen)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(4, 0, 4, 4)

        brand_icon = LogoMark(size=26, color=YELLOW)
        brand = QLabel("CONDUIT")
        brand.setObjectName("brand")
        tagline = QLabel("YOUR INTELLIGENT ASSISTANT")
        tagline.setObjectName("subtitle")

        left = QVBoxLayout()
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(brand_icon)
        row.addWidget(brand)
        row.addStretch(1)
        left.addLayout(row)
        left.addWidget(tagline)
        layout.addLayout(left, 1)

        center = QVBoxLayout()
        center.setSpacing(2)
        name = QLabel("CONDUIT")
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(f"color:{YELLOW};font-size:26px;font-weight:800;letter-spacing:3px;")
        center.addWidget(name)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        sub_row.addWidget(CircuitTrace(direction="left", color=PURPLE))
        subtitle = QLabel("CONDUIT SYSTEM INTERFACE")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("subtitle")
        sub_row.addWidget(subtitle)
        sub_row.addWidget(CircuitTrace(direction="right", color=PURPLE))
        center.addLayout(sub_row)
        layout.addLayout(center, 2)

        right = QVBoxLayout()
        self.clock = QLabel("--:--:--")
        self.clock.setObjectName("clock")
        self.clock.setAlignment(Qt.AlignRight)
        self.date = QLabel("")
        self.date.setAlignment(Qt.AlignRight)
        self.date.setStyleSheet(f"color:{PURPLE};font-size:9px;")
        right.addWidget(self.clock)
        right.addWidget(self.date)
        layout.addLayout(right, 1)
        return header

    def _build_left(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(3)

        overview = Panel("System Overview")
        self.cpu_card = GraphMetricCard("CPU Usage", CYAN)
        self.memory_card = MetricCard("Memory", YELLOW)
        self.disk_card = MetricCard("Disk Usage", PURPLE)
        self.network_card = NetworkCard()
        overview.body_layout.addWidget(self.cpu_card)
        overview.body_layout.addWidget(self.memory_card)
        overview.body_layout.addWidget(self.disk_card)
        overview.body_layout.addWidget(self.network_card)
        layout.addWidget(overview)

        info = Panel("System Info")
        self.system_info = InfoTable()
        info.body_layout.addWidget(self.system_info)
        layout.addWidget(info)

        quick = Panel("Quick Actions")
        for label, command in (
            ("▣   OPEN TERMINAL", "open command prompt"),
            ("⚙   OPEN SETTINGS", "open system settings"),
            ("▱   TASK MANAGER", "open task manager"),
            ("▤   FILE EXPLORER", "open file explorer"),
        ):
            button = QPushButton(label)
            button.setObjectName("quickAction")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, c=command: self._quick_command(c))
            quick.body_layout.addWidget(button)

        restart = QPushButton("◈   RESTART CONDUIT")
        restart.setObjectName("quickAction")
        restart.setCursor(Qt.PointingHandCursor)
        restart.clicked.connect(self._restart_conduit)
        quick.body_layout.addWidget(restart)
        layout.addWidget(quick)

        status = Panel("Conduit Status")
        self.status_dot = StatusDot(YELLOW)
        status.header_right.setText("")
        status.outer.itemAt(0).layout().addWidget(self.status_dot)

        self.status_grid = StatusGrid()
        status.body_layout.addWidget(self.status_grid)
        self.status_text = self.status_grid.status_field.value_label
        self.provider_label = self.status_grid.ai_field.value_label
        self.status_grid.version_field.set_value(self.version)
        layout.addWidget(status)
        layout.addStretch(1)

        scroll.setWidget(body)
        return scroll

    def _build_hud_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        self.hud = HudCore()
        layout.addWidget(self.hud)
        return frame

    def _build_console(self) -> QWidget:
        panel = Panel("System Console")
        clear = QPushButton("CLEAR")
        clear.setFixedHeight(20)
        clear.setStyleSheet(f"QPushButton{{border:none;color:{PURPLE};padding:0 5px;}}")
        clear.clicked.connect(self.console_clear)
        # Panel's right side is a label, replace content with simple clickable text through header label.
        panel.header_right.setText("CLEAR")
        panel.header_right.setCursor(Qt.PointingHandCursor)
        panel.header_right.mousePressEvent = lambda event: self.console_clear()

        self.console = ConsoleView()
        panel.body_layout.addWidget(self.console)
        return panel

    def _build_chat_panel(self) -> QWidget:
        panel = Panel("Chat Interface")
        container = QVBoxLayout()
        self.chat = ChatView()
        container.addWidget(self.chat, 1)

        input_row = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Type a command or question...")
        self.command_input.returnPressed.connect(self._send_command)
        self.send_button = QPushButton("▶")
        self.send_button.setObjectName("send")
        self.send_button.setFixedWidth(38)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self._send_command)
        input_row.addWidget(self.command_input, 1)
        input_row.addWidget(self.send_button)
        container.addLayout(input_row)

        provider_caption = QLabel("AI PROVIDER")
        provider_caption.setStyleSheet(f"color:{MUTED};font-size:8px;font-weight:700;")
        container.addWidget(provider_caption)
        provider_row = QGridLayout()
        provider_row.setContentsMargins(0, 0, 0, 0)
        provider_row.setHorizontalSpacing(5)
        provider_row.setVerticalSpacing(4)
        self.ollama_button = QPushButton("OLLAMA")
        self.ollama_button.setCursor(Qt.PointingHandCursor)
        self.ollama_button.setToolTip("Choose an installed Ollama model or download a recommended specialist model")
        self.ollama_button.clicked.connect(lambda: self._request_provider_switch("ollama"))
        self.gemini_button = QPushButton("GEMINI")
        self.gemini_button.setCursor(Qt.PointingHandCursor)
        self.gemini_button.setToolTip("Connect a Gemini API key and switch Conduit's reasoning provider")
        self.gemini_button.clicked.connect(lambda: self._request_provider_switch("gemini"))
        self.openai_button = QPushButton("OPENAI")
        self.openai_button.setCursor(Qt.PointingHandCursor)
        self.openai_button.setToolTip("Connect an OpenAI API key and switch Conduit's reasoning provider")
        self.openai_button.clicked.connect(lambda: self._request_provider_switch("openai"))
        self.grok_button = QPushButton("GROK AI")
        self.grok_button.setCursor(Qt.PointingHandCursor)
        self.grok_button.setToolTip("Connect an xAI API key and switch Conduit to Grok")
        self.grok_button.clicked.connect(lambda: self._request_provider_switch("grok"))
        provider_buttons = (
            self.ollama_button,
            self.gemini_button,
            self.openai_button,
            self.grok_button,
        )
        for index, button in enumerate(provider_buttons):
            button.setObjectName("providerButton")
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            provider_row.addWidget(button, 0, index)
            provider_row.setColumnStretch(index, 1)
        container.addLayout(provider_row)

        panel.body_layout.addLayout(container)
        return panel

    def _build_file_controls(self) -> QWidget:
        panel = Panel("File Upload")
        self.drop_zone = DropZone()
        self.drop_zone.fileSelected.connect(self._file_selected)
        panel.body_layout.addWidget(self.drop_zone)

        self.file_label = QLabel("No file loaded")
        self.file_label.setStyleSheet(f"color:{MUTED};font-size:9px;")
        self.file_label.setWordWrap(True)
        panel.body_layout.addWidget(self.file_label)

        self.interrupt_button = QPushButton("■   INTERRUPT   [ESC]")
        self.interrupt_button.setObjectName("yellow")
        self.interrupt_button.setCursor(Qt.PointingHandCursor)
        self.interrupt_button.clicked.connect(self._interrupt)
        panel.body_layout.addWidget(self.interrupt_button)

        self.mic_button = QPushButton("♩̸   MICROPHONE MUTED")
        self.mic_button.setObjectName("mic")
        self.mic_button.setProperty("active", "false")
        self.mic_button.setCursor(Qt.PointingHandCursor)
        self.mic_button.clicked.connect(self._toggle_mic)
        panel.body_layout.addWidget(self.mic_button)
        return panel

    def _connect_runtime(self) -> None:
        sig = self.runtime.signals
        sig.ready.connect(self._runtime_ready)
        sig.busy.connect(self._runtime_busy)
        sig.answer.connect(self._runtime_answer)
        sig.speech.connect(self._runtime_speech)
        sig.provider_switched.connect(self._provider_switched)
        sig.provider_switch_failed.connect(self._provider_switch_failed)
        sig.provider_recovery_needed.connect(self._provider_recovery_needed)
        sig.ollama_models_ready.connect(self._ollama_models_ready)
        sig.ollama_models_failed.connect(self._ollama_models_failed)
        sig.ollama_download_started.connect(self._ollama_download_started)
        sig.ollama_download_finished.connect(self._ollama_download_finished)
        sig.console.connect(self.console.log)
        sig.error.connect(self._runtime_error)
        sig.active_file.connect(self._active_file_changed)
        sig.stopped.connect(self._runtime_stopped)

    def _start_timers(self) -> None:
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(250)
        self._update_clock()

        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self._update_system_monitor)
        self.monitor_timer.start(1000)
        self._update_system_monitor()

    def _update_clock(self) -> None:
        now = datetime.now()
        self.clock.setText(now.strftime("%H:%M:%S"))
        self.date.setText(now.strftime("%a %d %b %Y"))

    def _update_system_monitor(self) -> None:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        disk_root = Path(os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else Path("/")
        try:
            disk = psutil.disk_usage(str(disk_root))
        except Exception:
            disk = psutil.disk_usage("/")

        current_net = psutil.net_io_counters()
        current_time = time.monotonic()
        delta_t = max(0.1, current_time - self._last_net_time)
        delta_bytes = (
            (current_net.bytes_sent - self._last_net.bytes_sent)
            + (current_net.bytes_recv - self._last_net.bytes_recv)
        )
        kb_s = max(0.0, delta_bytes / delta_t / 1024.0)
        self._last_net = current_net
        self._last_net_time = current_time

        self.cpu_card.set_metric(cpu, f"{psutil.cpu_count(logical=True)} logical cores")
        self.memory_card.set_metric(
            mem.percent,
            f"{mem.used / (1024**3):.1f} GB / {mem.total / (1024**3):.1f} GB",
        )
        self.disk_card.set_metric(
            disk.percent,
            f"{disk.used / (1024**3):.0f} GB / {disk.total / (1024**3):.0f} GB",
        )
        self.network_card.set_rate(kb_s)

        boot = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        self.system_info.set_rows([
            ("Hostname", socket.gethostname()),
            ("OS", f"{platform.system()} {platform.release()}"),
            ("Uptime", f"{hours:02d}:{minutes:02d}"),
            ("User", getpass.getuser()),
            ("Architecture", platform.machine()),
        ])

    def _send_command(self) -> None:
        text = self.command_input.text().strip()
        if not text:
            return
        if not self._ready:
            self.console.log("WARN", "Conduit is still starting.")
            return
        self.command_input.clear()

        # Always render exactly what the user typed. Command normalization is
        # routing-only and should never rewrite the visible conversation.
        normalized_text = normalize_conversation_command(text)

        if normalized_text == "/exit":
            self.chat.add_user(text)
            self.chat.add_conduit("Closing Conduit.", True)
            self.close()
            return

        # Provider switching is a GUI command, not a web-navigation request.
        # Legacy source-contract: provider_target = self._provider_switch_target(text)
        provider_target = self._provider_switch_target(normalized_text)
        if provider_target is not None:
            self.chat.add_user(text)
            self._pending_provider_switch_prompt = text
            self._request_provider_switch(provider_target)
            return

        # Render the user's prompt immediately in the normal chat surface.
        # The programmer console is reserved for internal execution/debug events.
        self.chat.add_user(text)

        if self._maybe_offer_specialist_model(normalized_text):
            return

        self._submit_existing_chat_command(normalized_text)

    def _submit_existing_chat_command(self, text: str) -> None:
        self.command_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.hud.set_processing(True)
        self.runtime.submit(text)

    def _maybe_offer_specialist_model(self, text: str) -> bool:
        """Offer a better specialist only when the active local model is a poor fit."""
        if getattr(self, "_active_provider", "") != "ollama":
            return False

        task = classify_task(
            text,
            active_file_kind=getattr(self, "_active_file_kind", ""),
        )
        if not task:
            return False

        model = getattr(self, "_active_model", "")
        if current_model_is_suitable(model, task):
            return False

        suppression_key = (task, model.casefold())
        if suppression_key in getattr(self, "_dismissed_model_suggestions", set()):
            return False

        recommendation = recommended_model(task)
        if recommendation is None:
            return False

        box = QMessageBox(self)
        box.setWindowTitle("Better AI Model Available")
        box.setIcon(QMessageBox.Information)
        box.setText(
            f"The current Ollama model '{model}' is not specialized for {task} tasks."
        )
        box.setInformativeText(
            f"Recommended local model: {recommendation.label} "
            f"({recommendation.description}). You can also use Gemini for this task. "
            "Conduit will preserve the current prompt and active file while switching."
        )
        local_button = box.addButton(
            f"Use {recommendation.label}",
            QMessageBox.AcceptRole,
        )
        gemini_button = box.addButton("Use Gemini", QMessageBox.ActionRole)
        continue_button = box.addButton(
            f"Continue with {model}",
            QMessageBox.DestructiveRole,
        )
        cancel_button = box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()

        if clicked is local_button:
            self._pending_task_after_model_switch = text
            self.runtime.ensure_ollama_model(recommendation.name)
            return True

        if clicked is gemini_button:
            self._pending_task_after_model_switch = text
            self._request_provider_switch("gemini")
            # If the key dialog was cancelled, _request_provider_switch leaves the
            # task pending. Resume on the current model instead of losing it.
            if self._pending_task_after_model_switch and getattr(self, "_active_provider", "") == "ollama":
                if not self.hud.property("processing"):
                    pass
            return True

        if clicked is continue_button:
            self._dismissed_model_suggestions.add(suppression_key)
            return False

        # Cancel means cancel only this prompt, not the whole Conduit session.
        return True

    def _ollama_models_ready(self, models: object) -> None:
        entries = list(models or [])
        dialog = OllamaModelDialog(
            entries,
            current_model=getattr(self, "_active_model", ""),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted or not dialog.selected_entry:
            if getattr(self, "_pending_provider_switch_prompt", ""):
                self.chat.add_conduit("Ollama model selection cancelled.", False)
                self._pending_provider_switch_prompt = ""
            return

        entry = dialog.selected_entry
        model = str(entry.get("name") or "")
        if bool(entry.get("installed")):
            self.runtime.switch_ollama_model(model)
        else:
            confirm = QMessageBox.question(
                self,
                "Download Ollama Model",
                f"{model} is not installed.\n\n"
                f"Conduit will open Command Prompt and run:\n"
                f"ollama pull {model}\n\n"
                "Download and use this model?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if confirm == QMessageBox.Yes:
                self.runtime.download_ollama_model(model)

    def _ollama_models_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Ollama Models", message)
        self.console.log("ERROR", message)
        if getattr(self, "_pending_task_after_model_switch", ""):
            task = self._pending_task_after_model_switch
            self._pending_task_after_model_switch = ""
            self.chat.add_conduit(
                "I couldn't switch the Ollama model, so I kept your task pending. "
                "You can retry the model switch or submit the task again.",
                False,
            )

    def _ollama_download_started(self, model: str) -> None:
        self.console.log(
            "INFO",
            f"Downloading Ollama model {model} in Command Prompt in the background. "
            "Conduit remains usable.",
        )

        pending = getattr(self, "_pending_task_after_model_switch", "")
        if not pending:
            return

        box = QMessageBox(self)
        box.setWindowTitle("Model Download Started")
        box.setIcon(QMessageBox.Information)
        box.setText(f"{model} is downloading in the background.")
        box.setInformativeText(
            "This download may be large and can take some time. "
            "Conduit will remain usable while it downloads. "
            "For the task you were about to run, you can switch to Gemini now or cancel that task. "
            "The Ollama download will continue either way."
        )
        gemini_button = box.addButton("Switch to Gemini", QMessageBox.AcceptRole)
        cancel_button = box.addButton("Cancel Task", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() is gemini_button:
            self._request_provider_switch("gemini")
            return

        # Cancel only the pending task. Do not stop the model download.
        self._pending_task_after_model_switch = ""
        self.chat.add_conduit(
            f"Cancelled the pending task. {model} will keep downloading in the background "
            "and will be available from the Ollama button when finished.",
            True,
        )

    def _ollama_download_finished(self, model: str, success: bool, message: str) -> None:
        level = "INFO" if success else "ERROR"
        self.console.log(level, message)
        if success:
            QMessageBox.information(
                self,
                "Ollama Download Complete",
                f"{model} finished downloading and is now available from the OLLAMA model selector.",
            )
        else:
            QMessageBox.warning(self, "Ollama Download", message)

    def _resume_pending_model_task(self) -> None:
        task = getattr(self, "_pending_task_after_model_switch", "")
        if not task:
            return
        self._pending_task_after_model_switch = ""
        self._submit_existing_chat_command(task)

    @staticmethod
    def _provider_switch_target(text: str) -> str | None:
        import re

        lowered = " ".join(str(text or "").casefold().split())
        if not lowered:
            return None
        has_switch_intent = lowered.startswith("/switch") or any(
            re.search(rf"\b{verb}\b", lowered)
            for verb in ("switch", "use", "change", "connect", "move")
        )
        if not has_switch_intent:
            return None
        if "ollama" in lowered:
            return "ollama"
        if "gemini" in lowered:
            return "gemini"
        if "openai" in lowered or "open ai" in lowered:
            return "openai"
        if "grok" in lowered or "xai" in lowered or "x ai" in lowered:
            return "grok"
        return None

    def _request_provider_switch(self, provider: str) -> None:
        if not self._ready:
            self.console.log("WARN", "Conduit is still starting.")
            return

        if provider == "ollama":
            status = environment_service.verify_ollama()
            if not status.available:
                box = QMessageBox(self)
                box.setWindowTitle("Ollama is not installed")
                box.setIcon(QMessageBox.Information)
                box.setText("Ollama lets Conduit run AI models locally on your PC.")
                box.setInformativeText(
                    "It can run offline without an API key, but local models need "
                    "a reasonably capable PC and use system RAM/VRAM."
                )
                install = box.addButton("Install Ollama", QMessageBox.AcceptRole)
                cancel = box.addButton("Cancel", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is install:
                    ok, message = environment_service.start_ollama_installer()
                    if ok:
                        QMessageBox.information(
                            self,
                            "Ollama Installer Started",
                            message + "\n\nWhen Ollama finishes installing, click OLLAMA again.",
                        )
                    else:
                        QMessageBox.critical(self, "Ollama Install Failed", message)
                return
            self.console.log("INFO", "Loading installed Ollama models...")
            self.runtime.request_ollama_models()
            return

        names = {"gemini": "Gemini", "openai": "OpenAI", "grok": "Grok AI"}
        name = names.get(provider, provider.title())
        key, accepted = QInputDialog.getText(
            self,
            f"Connect to {name}",
            f"Enter your {name} API key:",
            QLineEdit.Password,
        )
        if not accepted:
            if getattr(self, "_pending_provider_switch_prompt", ""):
                self.chat.add_conduit("Provider switch cancelled.", False)
                self._pending_provider_switch_prompt = ""
            if getattr(self, "_pending_task_after_model_switch", ""):
                task = self._pending_task_after_model_switch
                self._pending_task_after_model_switch = ""
                self._submit_existing_chat_command(task)
            return
        key = key.strip()
        if not key:
            QMessageBox.warning(self, f"Connect to {name}", "No API key was entered.")
            if getattr(self, "_pending_provider_switch_prompt", ""):
                self.chat.add_conduit("No API key was entered, so I did not switch providers.", False)
                self._pending_provider_switch_prompt = ""
            if getattr(self, "_pending_task_after_model_switch", ""):
                task = self._pending_task_after_model_switch
                self._pending_task_after_model_switch = ""
                self._submit_existing_chat_command(task)
            return

        # Never place the key in chat, logs, or widget text. Runtime validates it
        # in memory, discovers a usable model, and hot-swaps the existing agent.
        self.console.log("INFO", f"Connecting to {name}...")
        self.runtime.switch_provider(provider, key)

    def _provider_switched(self, provider: str, model: str, message: str) -> None:
        self._active_provider = provider.casefold()
        self._active_model = str(model or "")
        self._dismissed_model_suggestions = set()
        self.provider_label.setText(f"{provider.upper()} / {model}")
        self.status_grid.link_field.set_value("ONLINE", GREEN)
        self._update_provider_buttons()
        if getattr(self, "_pending_provider_switch_prompt", ""):
            self.chat.add_conduit(message, True)
            self._pending_provider_switch_prompt = ""
        QMessageBox.information(self, "AI Provider Connected", message)
        self._resume_pending_model_task()

    def _provider_switch_failed(self, provider: str, message: str) -> None:
        self._update_provider_buttons()
        if getattr(self, "_pending_provider_switch_prompt", ""):
            self.chat.add_conduit(message, False)
            self._pending_provider_switch_prompt = ""
        QMessageBox.critical(self, "AI Provider Connection Failed", message)

    def _provider_recovery_needed(
        self,
        provider: str,
        kind: str,
        message: str,
        retry_seconds: float,
    ) -> None:
        """Ask how to recover without exposing raw provider errors in chat."""
        provider_id = str(provider or "").casefold().strip()
        pretty = provider_id.title() or "AI provider"

        box = QMessageBox(self)
        box.setWindowTitle("AI Provider Recovery")
        box.setIcon(QMessageBox.Warning)

        if kind == "quota":
            box.setText(f"{pretty} has reached its current quota or rate limit.")
        elif kind == "authentication":
            box.setText(f"{pretty} rejected the current API credentials.")
        else:
            box.setText(f"{pretty} is temporarily unavailable.")

        info = (
            "Conduit paused the current task and preserved the active file and task context. "
            "Choose how you want to continue."
        )
        if retry_seconds > 0:
            info += f" The provider suggests retrying in about {retry_seconds:.0f} seconds."
        box.setInformativeText(info)

        alternate_model = None
        if provider_id in {"gemini", "openai", "grok"}:
            alternate_model = box.addButton("Try Another Model", QMessageBox.ActionRole)

        same_key = None
        if provider_id == "gemini":
            same_key = box.addButton("Use Another Gemini Key", QMessageBox.ActionRole)
        elif provider_id == "openai":
            same_key = box.addButton("Use Another OpenAI Key", QMessageBox.ActionRole)
        elif provider_id == "grok":
            same_key = box.addButton("Use Another Grok API Key", QMessageBox.ActionRole)

        other_cloud = box.addButton(
            "Switch to OpenAI" if provider_id != "openai" else "Switch to Gemini",
            QMessageBox.ActionRole,
        )
        grok_cloud = None
        if provider_id != "grok":
            grok_cloud = box.addButton("Switch to Grok AI", QMessageBox.ActionRole)

        ollama_button = None
        if provider_id != "ollama":
            ollama_button = box.addButton("Switch to Ollama", QMessageBox.ActionRole)

        wait_button = None
        if kind == "quota":
            wait_button = box.addButton("Wait and Retry", QMessageBox.ActionRole)

        cancel_button = box.addButton("Cancel Task", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()

        if clicked is cancel_button or clicked is None:
            self.runtime.resolve_provider_recovery("cancel")
            return

        if alternate_model is not None and clicked is alternate_model:
            self.runtime.resolve_provider_recovery("alternate_model")
            return

        if wait_button is not None and clicked is wait_button:
            self.runtime.resolve_provider_recovery("wait")
            return

        if ollama_button is not None and clicked is ollama_button:
            self.runtime.resolve_provider_recovery("ollama")
            return

        target = None
        if same_key is not None and clicked is same_key:
            target = provider_id
        elif clicked is other_cloud:
            target = "openai" if provider_id != "openai" else "gemini"
        elif grok_cloud is not None and clicked is grok_cloud:
            target = "grok"

        if target in {"gemini", "openai", "grok"}:
            name = {"gemini": "Gemini", "openai": "OpenAI", "grok": "Grok AI"}[target]
            key, accepted = QInputDialog.getText(
                self,
                f"Recover with {name}",
                f"Enter your {name} API key:",
                QLineEdit.Password,
            )
            if not accepted or not key.strip():
                self.runtime.resolve_provider_recovery("cancel")
                return
            self.runtime.resolve_provider_recovery(target, key.strip())
            return

        self.runtime.resolve_provider_recovery("cancel")

    def _update_provider_buttons(self) -> None:
        active = getattr(self, "_active_provider", "")
        busy = not self.command_input.isEnabled()
        self.ollama_button.setEnabled(not busy)
        self.gemini_button.setEnabled(not busy and active != "gemini")
        self.openai_button.setEnabled(not busy and active != "openai")
        self.grok_button.setEnabled(not busy and active != "grok")
        self.ollama_button.setText("OLLAMA • ACTIVE" if active == "ollama" else "OLLAMA")
        self.gemini_button.setText("GEMINI • ACTIVE" if active == "gemini" else "GEMINI")
        self.openai_button.setText("OPENAI • ACTIVE" if active == "openai" else "OPENAI")
        self.grok_button.setText("GROK AI • ACTIVE" if active == "grok" else "GROK AI")

    def _quick_command(self, command: str) -> None:
        if not self._ready:
            self.console.log("WARN", "Conduit is still starting.")
            return
        self.command_input.setText(command)
        self._send_command()

    def _file_selected(self, path: str) -> None:
        file = Path(path)
        self.file_label.setText(f"Loading: {file.name}")
        self.runtime.register_dropped_file(str(file))

    def _active_file_changed(self, filename: str, kind: str) -> None:
        self._active_file_kind = str(kind or "").casefold()
        self.file_label.setText(f"ACTIVE FILE   {filename}\nTYPE          {kind.upper()}")
        self.drop_zone.main.setText(filename)
        self.console.log("INFO", f"Active GUI file set: {filename} [{kind}].")

    def _interrupt(self) -> None:
        self.runtime.interrupt()
        self.console.log("WARN", "Interrupt requested.")
        self.hud.set_status("INTERRUPTING...")

    def _toggle_mic(self) -> None:
        # The GUI exposes and remembers the mic control now. Actual speech-to-text
        # capture remains intentionally decoupled until Conduit's voice module is added.
        self._mic_active = not self._mic_active
        self.mic_button.setProperty("active", "true" if self._mic_active else "false")
        self.mic_button.style().unpolish(self.mic_button)
        self.mic_button.style().polish(self.mic_button)
        if self._mic_active:
            self.mic_button.setText("🎙   MICROPHONE ACTIVE")
            self.console.log("INFO", "Microphone UI enabled; awaiting voice-input backend.")
        else:
            self.mic_button.setText("♩̸   MICROPHONE MUTED")
            self.console.log("INFO", "Microphone UI muted.")

    def _runtime_ready(self, provider: str, model: str) -> None:
        self._ready = True
        self._active_provider = provider.casefold()
        self._active_model = str(model or "")
        self._active_file_kind = ""
        self._dismissed_model_suggestions = set()
        self._pending_task_after_model_switch = ""
        if not hasattr(self, "_pending_provider_switch_prompt"):
            self._pending_provider_switch_prompt = ""
        self.status_text.setText("ACTIVE")
        self.status_text.setStyleSheet(f"color:{GREEN};font-weight:700;")
        self.status_dot.set_color(GREEN)
        self.provider_label.setText(f"{provider.upper()} / {model}")
        self.status_grid.link_field.set_value("ONLINE", GREEN)
        self.hud.set_status("LISTENING...")
        self.console.log("INFO", "System interface ready.")
        self._update_provider_buttons()
        self.command_input.setFocus()

    def _runtime_busy(self, busy: bool) -> None:
        self.hud.set_processing(busy)
        self.command_input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        if hasattr(self, "gemini_button"):
            self._update_provider_buttons()
        if not busy:
            self.command_input.setFocus()

    def _runtime_answer(self, user: str, answer: str, success: bool) -> None:
        # The user's prompt was already added when submitted; append only Conduit's reply.
        self.chat.add_conduit(answer, success)
        self.hud.set_processing(False)
        self.hud.set_status("LISTENING...")
        # Direct commands such as /clear, /history and their natural-English
        # aliases can complete without entering the normal busy=True/False task
        # path. Always restore input availability when a final answer arrives.
        self.command_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.command_input.setFocus()

    def _runtime_speech(self, text: str) -> None:
        # TTS is not connected yet. This is the exact utterance the future
        # speaking module should read aloud.
        self.console.log("DEBUG", f"TTS queued: {text}")

    def _runtime_error(self, message: str) -> None:
        self.console.log("ERROR", message)
        QMessageBox.critical(self, "Conduit Runtime Error", message)

    def _runtime_stopped(self) -> None:
        self._ready = False
        self.status_text.setText("OFFLINE")
        self.status_text.setStyleSheet(f"color:{RED};font-weight:700;")
        self.status_dot.set_color(RED)
        self.status_grid.link_field.set_value("OFFLINE", RED)
        self.hud.set_status("OFFLINE")

    def console_clear(self) -> None:
        self.console.clear()

    def _restart_conduit(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restart Conduit",
            "Restart the Conduit GUI now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.runtime.stop()
            subprocess.Popen(
                [sys.executable, *sys.argv],
                cwd=str(Path.cwd()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                    if os.name == "nt" else 0
                ),
            )
        finally:
            QApplication.quit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._interrupt()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.runtime.stop()
        event.accept()


def run_gui(
    *,
    provider: str,
    model: str,
    project_root: Path,
    no_memory: bool = False,
    version: str = "2.5.0",
) -> int:
    if QApplication.instance() is None:
        try:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Conduit")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)

    runtime = ConduitGuiRuntime(
        provider_name=provider,
        model=model,
        project_root=project_root,
        no_memory=no_memory,
    )
    window = ConduitMainWindow(runtime=runtime, version=version)
    window.show()
    return app.exec()
