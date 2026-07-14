from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QPalette, QColor
from PySide6.QtWidgets import QApplication, QAbstractItemView, QFormLayout, QLabel, QPushButton, QTableWidget


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(_preferred_font())

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f6f7f8"))
    palette.setColor(QPalette.WindowText, QColor("#111111"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f2f3f4"))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#111111"))
    palette.setColor(QPalette.Text, QColor("#111111"))
    palette.setColor(QPalette.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ButtonText, QColor("#111111"))
    palette.setColor(QPalette.Highlight, QColor("#0039a6"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLE)


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("buttonRole", role)
    button.setCursor(Qt.PointingHandCursor)
    button.style().unpolish(button)
    button.style().polish(button)


def configure_form_layout(form: QFormLayout) -> None:
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)


def set_context_label(label: QLabel) -> None:
    label.setObjectName("contextLabel")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)


def set_muted_label(label: QLabel) -> None:
    label.setObjectName("mutedLabel")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)


def configure_table(table: QTableWidget) -> None:
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideMiddle)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(30)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.horizontalHeader().setMinimumSectionSize(96)


def _preferred_font() -> QFont:
    available = set(QFontDatabase.families())
    for family in ("Helvetica Neue", "Helvetica", "Arial", "Inter", "Segoe UI", "SF Pro Text", "Ubuntu", "Noto Sans", "DejaVu Sans"):
        if family in available:
            font = QFont(family)
            font.setPointSizeF(10.5)
            return font
    font = QFont("Sans Serif")
    font.setPointSizeF(10.5)
    return font


APP_STYLE = """
QWidget {
    background: #f6f7f8;
    color: #111111;
    selection-background-color: #0039a6;
    selection-color: #ffffff;
}

QMainWindow {
    background: #f6f7f8;
}

#appShell {
    background: #f6f7f8;
}

#appHeader {
    background: #111111;
    border: 0;
    border-radius: 4px;
}

#headerLogo {
    background: transparent;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
}

#appTitle {
    color: #ffffff;
    font-size: 23px;
    font-weight: 800;
    letter-spacing: 0px;
}

#appSubtitle {
    color: #d9d9d9;
    font-size: 10.5pt;
}

#headerContextLabel {
    background: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    color: #111111;
    font-weight: 700;
    padding: 7px 10px;
}

#contextLabel {
    background: #111111;
    border: 0;
    border-left: 8px solid #fccc0a;
    border-radius: 4px;
    color: #ffffff;
    padding: 9px 11px;
}

#mutedLabel {
    color: #4c4c4c;
}

#sectionTitle {
    color: #111111;
    font-weight: 800;
    font-size: 10.5pt;
}

#chartTitle {
    color: #111111;
    font-weight: 800;
    font-size: 11pt;
}

QTabWidget::pane {
    border: 1px solid #b9b9b9;
    border-radius: 4px;
    background: #ffffff;
    top: -1px;
}

QTabWidget#mainTabs::pane {
    background: #ffffff;
}

QTabBar::tab {
    background: #ffffff;
    color: #111111;
    border: 1px solid #b9b9b9;
    border-radius: 4px;
    padding: 9px 13px;
    margin: 4px 4px 5px 0;
    min-height: 22px;
    font-weight: 700;
}

QTabBar::tab:selected {
    background: #111111;
    color: #ffffff;
    border-color: #111111;
}

QTabBar::tab:hover:!selected {
    background: #f2f2f2;
    color: #111111;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #b9b9b9;
    border-radius: 4px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 800;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #111111;
    background: #ffffff;
}

QGroupBox#sectionToggle {
    background: transparent;
    border: 0;
    border-radius: 0;
    margin-top: 10px;
    padding: 26px 0 0 0;
}

QGroupBox#sectionToggle::title {
    background: #111111;
    border-radius: 4px;
    color: #ffffff;
    left: 0;
    padding: 5px 9px;
}

QGroupBox::indicator {
    width: 14px;
    height: 14px;
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
    border: 1px solid #8d8d8d;
    border-radius: 4px;
    padding: 7px;
    color: #111111;
}

QTextEdit,
QTextBrowser,
QListWidget,
QTableWidget {
    selection-background-color: #d9e7ff;
    selection-color: #111111;
}

QLineEdit:focus,
QTextEdit:focus,
QTextBrowser:focus,
QComboBox:focus,
QSpinBox:focus,
QListWidget:focus,
QTableWidget:focus {
    border: 2px solid #0039a6;
}

QComboBox::drop-down {
    border: 0;
    border-left: 1px solid #d6d6d6;
    width: 28px;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #8d8d8d;
    border-radius: 4px;
    padding: 5px;
    outline: 0;
    selection-background-color: #d9e7ff;
    selection-color: #111111;
}

QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 6px 8px;
    border-radius: 6px;
}

QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: #d9e7ff;
    color: #111111;
}

QSpinBox::up-button,
QSpinBox::down-button {
    border: 0;
    width: 24px;
}

QPushButton {
    background: #ffffff;
    border: 1px solid #7b7b7b;
    border-radius: 4px;
    padding: 8px 13px;
    color: #111111;
    font-weight: 800;
    min-height: 22px;
}

QPushButton:hover {
    background: #f2f2f2;
    border-color: #111111;
}

QPushButton:pressed {
    background: #e5e5e5;
}

QPushButton:disabled {
    background: #eeeeee;
    border-color: #c8c8c8;
    color: #777777;
}

QPushButton[buttonRole="secondary"] {
    background: #ffffff;
    border-color: #111111;
    color: #111111;
}

QPushButton[buttonRole="primary"] {
    background: #00933c;
    border-color: #00933c;
    color: #ffffff;
}

QPushButton[buttonRole="primary"]:hover {
    background: #007f34;
    border-color: #007f34;
}

QPushButton[buttonRole="destructive"] {
    background: #ee352e;
    border-color: #ee352e;
    color: #ffffff;
}

QPushButton[buttonRole="destructive"]:hover {
    background: #c92d28;
    border-color: #c92d28;
}

QPushButton[buttonRole="primary"]:disabled,
QPushButton[buttonRole="secondary"]:disabled,
QPushButton[buttonRole="destructive"]:disabled {
    background: #eeeeee;
    border-color: #c8c8c8;
    color: #777777;
}

QCheckBox {
    spacing: 8px;
    background: transparent;
}

QHeaderView::section {
    background: #111111;
    border: 0;
    border-bottom: 1px solid #111111;
    padding: 8px;
    color: #ffffff;
    font-weight: 800;
}

QTableWidget {
    gridline-color: #d8d8d8;
    alternate-background-color: #f4f4f4;
}

QTableWidget::item {
    padding: 6px;
}

QListWidget::item {
    border-radius: 4px;
    padding: 8px 9px;
    margin: 1px 0;
}

QListWidget::item:selected {
    background: #d9e7ff;
    color: #111111;
}

QScrollBar:vertical {
    background: transparent;
    width: 14px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #9f9f9f;
    border-radius: 4px;
    min-height: 28px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QStatusBar {
    background: #ffffff;
    border-top: 1px solid #b9b9b9;
    color: #4c4c4c;
}

QToolTip {
    background: #ffffff;
    border: 1px solid #111111;
    border-radius: 4px;
    color: #111111;
    padding: 6px;
}

QTextEdit#logPane {
    font-family: "DejaVu Sans Mono", "Consolas", monospace;
    font-size: 9.5pt;
}

QTextBrowser#documentPane {
    border: 0;
    padding: 12px;
}

QLabel#progressStatus {
    color: #111111;
    font-weight: 600;
}

QProgressBar {
    background: #e9eaec;
    border: 1px solid #c4c6ca;
    border-radius: 4px;
    height: 18px;
    text-align: center;
    color: #111111;
    font-size: 9pt;
}

QProgressBar::chunk {
    background: #0039a6;
    border-radius: 3px;
}
"""
