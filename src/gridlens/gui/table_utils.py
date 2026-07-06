from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


TableRow = Mapping[str, object]


def make_read_only_item(value: object) -> QTableWidgetItem:
    """Create a table item for display-only application data."""
    item = QTableWidgetItem("" if value is None else str(value))
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def populate_table(table: QTableWidget, rows: Sequence[TableRow], columns: Sequence[str]) -> None:
    """Replace a QTableWidget with read-only rows from dictionaries."""
    table.clear()
    table.setColumnCount(len(columns))
    table.setRowCount(len(rows))
    table.setHorizontalHeaderLabels(list(columns))
    table.horizontalHeader().setStretchLastSection(True)

    for row_index, row in enumerate(rows):
        for column_index, column in enumerate(columns):
            table.setItem(row_index, column_index, make_read_only_item(row.get(column, "")))
