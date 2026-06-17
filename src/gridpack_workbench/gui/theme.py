from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QPalette, QColor
from PySide6.QtWidgets import QApplication, QPushButton


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(_preferred_font())

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f5f7fb"))
    palette.setColor(QPalette.WindowText, QColor("#182233"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f7f9fc"))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#182233"))
    palette.setColor(QPalette.Text, QColor("#182233"))
    palette.setColor(QPalette.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ButtonText, QColor("#182233"))
    palette.setColor(QPalette.Highlight, QColor("#2563eb"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLE)


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("buttonRole", role)
    button.style().unpolish(button)
    button.style().polish(button)


def _preferred_font() -> QFont:
    available = set(QFontDatabase.families())
    for family in ("Inter", "Segoe UI", "SF Pro Text", "Ubuntu", "Noto Sans", "DejaVu Sans"):
        if family in available:
            return QFont(family, 10)
    return QFont("Sans Serif", 10)


APP_STYLE = """
QWidget {
    background: #f5f7fb;
    color: #182233;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}

QMainWindow {
    background: #f5f7fb;
}

#appShell {
    background: #f5f7fb;
}

#appHeader {
    background: rgba(255, 255, 255, 230);
    border: 1px solid #d9e0ea;
    border-radius: 8px;
}

#appTitle {
    color: #111827;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0px;
}

#appSubtitle,
#contextLabel,
#mutedLabel {
    color: #5b667a;
}

#contextLabel {
    background: #eef4ff;
    border: 1px solid #cfe0ff;
    border-radius: 8px;
    padding: 7px 10px;
}

QTabWidget::pane {
    border: 1px solid #d9e0ea;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}

QTabWidget#mainTabs::pane {
    background: #ffffff;
}

QTabBar::tab {
    background: transparent;
    color: #4d586a;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 14px;
    margin: 4px 3px 5px 0;
    min-height: 20px;
}

QTabBar::tab:selected {
    background: #ffffff;
    color: #111827;
    border: 1px solid #d9e0ea;
}

QTabBar::tab:hover:!selected {
    background: #eef2f8;
    color: #182233;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #d9e0ea;
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #344154;
    background: #ffffff;
}

QLabel {
    background: transparent;
}

QLineEdit,
QTextEdit,
QTextBrowser,
QComboBox,
QSpinBox,
QListWidget,
QTableWidget {
    background: #ffffff;
    border: 1px solid #cfd7e4;
    border-radius: 8px;
    padding: 6px;
    color: #182233;
}

QTextEdit,
QTextBrowser,
QListWidget,
QTableWidget {
    selection-background-color: #dbeafe;
    selection-color: #111827;
}

QLineEdit:focus,
QTextEdit:focus,
QTextBrowser:focus,
QComboBox:focus,
QSpinBox:focus,
QListWidget:focus,
QTableWidget:focus {
    border: 1px solid #2563eb;
}

QComboBox::drop-down,
QSpinBox::up-button,
QSpinBox::down-button {
    border: 0;
    width: 24px;
}

QPushButton {
    background: #ffffff;
    border: 1px solid #c9d3e2;
    border-radius: 8px;
    padding: 7px 13px;
    color: #182233;
    font-weight: 600;
}

QPushButton:hover {
    background: #f2f6fc;
    border-color: #aab8cc;
}

QPushButton:pressed {
    background: #e8eef7;
}

QPushButton:disabled {
    background: #eef1f5;
    border-color: #d8dee8;
    color: #8a94a6;
}

QPushButton[buttonRole="primary"] {
    background: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
}

QPushButton[buttonRole="primary"]:hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}

QPushButton[buttonRole="destructive"] {
    background: #fff5f5;
    border-color: #f2b8b5;
    color: #9f1d1d;
}

QCheckBox {
    spacing: 8px;
    background: transparent;
}

QHeaderView::section {
    background: #f2f5f9;
    border: 0;
    border-bottom: 1px solid #d9e0ea;
    padding: 7px;
    color: #344154;
    font-weight: 600;
}

QTableWidget {
    gridline-color: #e5eaf2;
    alternate-background-color: #f8fafc;
}

QTableWidget::item {
    padding: 5px;
}

QListWidget::item {
    border-radius: 6px;
    padding: 7px 8px;
    margin: 1px 0;
}

QListWidget::item:selected {
    background: #dbeafe;
    color: #111827;
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #c5cfdd;
    border-radius: 6px;
    min-height: 28px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QStatusBar {
    background: #ffffff;
    border-top: 1px solid #d9e0ea;
    color: #5b667a;
}
"""
