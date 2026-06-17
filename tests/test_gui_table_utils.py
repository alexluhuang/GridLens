from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidget

from gridpack_workbench.gui.table_utils import make_read_only_item, populate_table


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_make_read_only_item_formats_missing_values() -> None:
    _app()

    item = make_read_only_item(None)

    assert item.text() == ""
    assert not item.flags() & Qt.ItemIsEditable


def test_populate_table_replaces_rows_with_read_only_items() -> None:
    _app()
    table = QTableWidget()

    populate_table(table, [{"name": "branch-1", "rate": 120}], ["name", "rate"])

    assert table.rowCount() == 1
    assert table.columnCount() == 2
    assert table.horizontalHeaderItem(0).text() == "name"
    assert table.item(0, 0).text() == "branch-1"
    assert table.item(0, 1).text() == "120"
    assert not table.item(0, 0).flags() & Qt.ItemIsEditable
