
from __future__ import annotations

# Dark cyberpunk palette requested for Conduit.
BG = "#020812"
BG_2 = "#06111E"
PANEL = "#071522"
PANEL_ALT = "#091A2B"
BORDER = "#27386E"
BLUE = "#168BFF"
CYAN = "#00C8FF"
PURPLE = "#A84DFF"
PURPLE_2 = "#6F2DCE"
YELLOW = "#FFD21A"
GREEN = "#18E776"
RED = "#FF3B6B"
TEXT = "#D7E6FF"
MUTED = "#7D90AB"
WHITE = "#F5F8FF"

MONO_STACK = '"Cascadia Mono", "Consolas", "Courier New", monospace'
UI_STACK = '"Bahnschrift", "Segoe UI", Arial, sans-serif'

APP_QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Cascadia Mono", "Consolas";
    font-size: 12px;
}}
QMainWindow {{
    background: {BG};
}}
QFrame#panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 3px;
}}
QLabel#panelTitle {{
    color: {PURPLE};
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 1px;
}}
QLabel#brand {{
    color: {YELLOW};
    font-family: "Bahnschrift";
    font-size: 23px;
    font-weight: 800;
    letter-spacing: 2px;
}}
QLabel#subtitle {{
    color: {MUTED};
    font-size: 10px;
    letter-spacing: 2px;
}}
QLabel#clock {{
    color: {YELLOW};
    font-size: 17px;
    font-weight: 700;
}}
QPushButton {{
    background: #07101D;
    border: 1px solid #36517D;
    border-radius: 3px;
    padding: 8px 10px;
    color: {TEXT};
    text-align: left;
}}
QPushButton:hover {{
    border: 1px solid {CYAN};
    color: {WHITE};
    background: #14264A;
}}
QPushButton:pressed {{
    background: #050D1A;
    border-color: {CYAN};
}}
QPushButton:disabled {{
    color: {MUTED};
    border-color: #142238;
    background: #060D18;
}}
QPushButton#quickAction {{
    background: #071120;
    border: 1px solid #1C2E52;
    border-radius: 4px;
    padding: 4px 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QPushButton#quickAction:hover {{
    background: #101B3A;
    border: 1px solid {PURPLE};
    color: {WHITE};
    padding-left: 13px;
}}
QPushButton#quickAction:pressed {{
    background: #050D1A;
    border-color: {CYAN};
}}
QPushButton#send {{
    border: 1px solid {BLUE};
    color: {CYAN};
    font-weight: 900;
    border-radius: 3px;
}}
QPushButton#send:hover {{
    background: #0B2440;
    border-color: {CYAN};
    color: {WHITE};
}}
QPushButton#yellow {{
    border-color: {YELLOW};
    color: {YELLOW};
    background: #171402;
    font-weight: 700;
    text-align: center;
}}
QPushButton#yellow:hover {{
    background: #2A2200;
    border: 1px solid {YELLOW};
    color: #FFE668;
}}
QPushButton#yellow:pressed {{
    background: #171402;
}}
QPushButton#mic {{
    border-color: {RED};
    color: {RED};
    background: #170711;
    font-weight: 700;
    text-align: center;
}}
QPushButton#mic:hover {{
    background: #2A0A1B;
    border: 1px solid #FF6B93;
    color: #FF6B93;
}}
QPushButton#mic[active="true"] {{
    border-color: {GREEN};
    color: {GREEN};
    background: #06150D;
}}
QPushButton#mic[active="true"]:hover {{
    background: #0B2A18;
    border: 1px solid #6DFFB0;
    color: #6DFFB0;
}}
QPushButton#titlebar, QPushButton#titlebarClose {{
    border: 1px solid #293D66;
    background: #080B18;
    color: {PURPLE};
    padding: 0;
    border-radius: 2px;
}}
QPushButton#titlebar:hover {{
    background: #18102A;
    color: {WHITE};
}}
QPushButton#titlebarClose:hover {{
    background: #3A0F1E;
    color: #FF6B93;
}}
QPushButton#providerButton {{
    border: 1px solid #36517D;
    background: #071120;
    color: {TEXT};
    padding: 6px 3px;
    text-align: center;
    font-weight: 700;
}}
QPushButton#providerButton:hover {{
    border-color: {PURPLE};
    background: #21143F;
    color: {WHITE};
}}
QSplitter#mainSplitter::handle, QSplitter#sectionSplitter::handle {{
    background: #111D35;
    border: 1px solid #294167;
    border-radius: 2px;
}}
QSplitter#mainSplitter::handle:hover, QSplitter#sectionSplitter::handle:hover {{
    background: #2A1749;
    border-color: {PURPLE};
}}
QLineEdit {{
    background: #030B15;
    color: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 9px 10px;
    selection-background-color: {PURPLE_2};
}}
QLineEdit:hover {{
    border-color: {PURPLE_2};
}}
QLineEdit:focus {{
    border-color: {BLUE};
}}
QTextEdit, QTextBrowser, QPlainTextEdit {{
    background: #030B15;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    selection-background-color: {PURPLE_2};
}}
QScrollBar:vertical {{
    background: #050B13;
    width: 9px;
}}
QScrollBar::handle:vertical {{
    background: {PURPLE_2};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QProgressBar {{
    border: 1px solid #182946;
    border-radius: 4px;
    background: #020812;
    text-align: right;
    color: {TEXT};
    min-height: 9px;
}}
QProgressBar::chunk {{
    background: {BLUE};
    border-radius: 4px;
}}
QToolTip {{
    color: {TEXT};
    background: {PANEL_ALT};
    border: 1px solid {PURPLE};
}}
"""
