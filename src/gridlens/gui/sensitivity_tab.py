"""The Sensitivity Analysis tab: edit a project's case, then run GridPACK.

The tab shows the loads, generators, or branches of the case the project's
XML configuration names, one record per row and one field per column, and
lets a planner change any field, add records, and remove them. Its run
button hands the edited case to the Run tab, which runs GridPACK on it with
the project's configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gridlens.core import sensitivity
from gridlens.core.project import Project, ProjectData
from gridlens.gui.theme import (
    configure_table,
    set_button_role,
    set_context_label,
    set_muted_label,
)
from gridlens.psse import layouts, parse, patch


TITLES = {"load": "Loads", "generator": "Generators", "branch": "Branches"}
ADDED = QColor("#e3f4e6")
CHANGED = QColor("#fff2cc")
REMOVED = QColor("#f4dada")
ASSUMED = QColor("#777777")
_STYLE_ROLES = (Qt.BackgroundRole, Qt.FontRole, Qt.ForegroundRole,
                Qt.ToolTipRole)


@dataclass
class Row:
    """One record in a table: its line in the case, or None for a new one.

    values holds every field's value as the table shows it, and original
    holds the values the case gave. given counts the fields the file itself
    holds; PSS/E assumes the values of the rest.
    """

    line: int | None
    values: list[str]
    original: tuple[str, ...] = ()
    given: int = 0
    removed: bool = False


class RecordTable(QAbstractTableModel):
    """The loads, generators, or branches of a case, as an editable table.

    The first columns name the buses a record connects, and the others are
    its fields. The table remembers the rows a planner edits, adds, or
    removes, so edits() lists the changes without comparing every row.
    """

    rejected = Signal(str)

    def __init__(self, case: parse.Case, kind: str) -> None:
        super().__init__()
        self.case = case
        self.kind = kind
        self.fields = layouts.fields(case.version, kind)
        self.names = len(layouts.BUS_FIELDS[kind])
        self.rows = [self._row(record) for record in case.records[kind]]
        self.shown = list(range(len(self.rows)))
        self.touched: set[int] = set()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.shown)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else self.names + len(self.fields)

    def headerData(self, section, orientation,  # noqa: N802
                   role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if section >= self.names:
            field = self.fields[section - self.names]
            text, tip = field.name, field.description
            if not field.gridpack:
                tip += ". GridPACK does not read this field."
        elif self.kind == "branch":
            text = ("From bus name", "To bus name")[section]
            tip = "The name the case gives the bus."
        else:
            text, tip = "Bus name", "The name the case gives the bus."
        return {Qt.DisplayRole: text, Qt.ToolTipRole: tip}.get(role)

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() >= self.names and not self.row(index.row()).removed:
            flags |= Qt.ItemIsEditable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        row = self.row(index.row())
        column = index.column() - self.names
        if role in (Qt.DisplayRole, Qt.EditRole):
            if column < 0:
                return self._bus_name(row, index.column())
            return row.values[column]
        if role not in _STYLE_ROLES:
            return None
        return self._style(row, column, role)

    def setData(self, index, value, role=Qt.EditRole) -> bool:  # noqa: N802
        if role != Qt.EditRole or index.column() < self.names:
            return False
        column = index.column() - self.names
        text = str(value).strip()
        problem = patch.check_value(self.fields[column], text)
        if problem:
            self.rejected.emit(problem)
            return False
        position = self.shown[index.row()]
        self.rows[position].values[column] = text
        self.touched.add(position)
        # A bus name follows its bus number, so the whole row may change.
        self._row_changed(index.row())
        return True

    def row(self, view_row: int) -> Row:
        """Return the row shown at a position of the table."""
        return self.rows[self.shown[view_row]]

    def set_filter(self, text: str) -> None:
        """Show the rows that match every word of text.

        A word matches a row when it is one of the row's bus numbers, its ID
        or circuit, or part of one of its bus names. New rows always show.
        """
        terms = text.lower().split()
        self.beginResetModel()
        self.shown = [
            position for position, row in enumerate(self.rows)
            if not terms or row.line is None or self._matches(row, terms)
        ]
        self.endResetModel()

    def add(self, buses: list[int]) -> None:
        """Add a record at buses, with an unused ID and PSS/E's defaults.

        Raises ValueError when a bus is not in the case.
        """
        taken = [row.values for row in self.rows]
        values = patch.new_values(self.case, self.kind, buses, taken)
        self.beginInsertRows(QModelIndex(), len(self.shown), len(self.shown))
        self.rows.append(Row(None, values))
        self.touched.add(len(self.rows) - 1)
        self.shown.append(len(self.rows) - 1)
        self.endInsertRows()

    def toggle_removed(self, view_rows: list[int]) -> None:
        """Remove each row shown at view_rows, or restore it if removed."""
        for view_row in view_rows:
            position = self.shown[view_row]
            self.rows[position].removed = not self.rows[position].removed
            self.touched.add(position)
            self._row_changed(view_row)

    def edits(self) -> list[patch.Edit]:
        """Return the table's changes to the case as patch edits."""
        names = [field.name for field in self.fields]
        edits = []
        for position in sorted(self.touched):
            row = self.rows[position]
            if row.line is None and not row.removed:
                values = dict(zip(names, row.values))
                edits.append(patch.Edit(self.kind, None, values))
            elif row.line is not None and row.removed:
                edits.append(patch.Edit(self.kind, row.line, removed=True))
            elif row.line is not None:
                changed = {
                    name: value
                    for name, value, old in zip(names, row.values,
                                                row.original)
                    if value != old
                }
                if changed:
                    edits.append(patch.Edit(self.kind, row.line, changed))
        return edits

    def _row(self, record: parse.Record) -> Row:
        """Return the row of a record, filling in fields the file omits."""
        if len(record.values) >= len(self.fields):
            values = list(record.values[:len(self.fields)])
        else:
            edit = patch.Edit(self.kind, record.line)
            values = patch.values_after(self.case, edit)
        return Row(record.line, values, tuple(values), len(record.values))

    def _style(self, row: Row, column: int, role):
        """Return how a cell looks: new, changed, removed, or assumed.

        column is negative for a bus name, which shows only how its row
        looks.
        """
        in_case = column >= 0 and row.line is not None
        changed = in_case and row.values[column] != row.original[column]
        assumed = in_case and column >= row.given
        if role == Qt.BackgroundRole and row.removed:
            return REMOVED
        if role == Qt.BackgroundRole and row.line is None:
            return ADDED
        if role == Qt.BackgroundRole and changed:
            return CHANGED
        if role == Qt.FontRole and row.removed:
            font = QFont()
            font.setStrikeOut(True)
            return font
        if role == Qt.ForegroundRole and assumed and not changed:
            return ASSUMED
        if role == Qt.ToolTipRole and changed:
            return f"Was {row.original[column]}"
        if role == Qt.ToolTipRole and assumed:
            return "The file leaves this field out; PSS/E assumes this value."
        return None

    def _row_changed(self, view_row: int) -> None:
        """Tell the view that every cell of a row may have changed."""
        last = self.index(view_row, self.columnCount() - 1)
        self.dataChanged.emit(self.index(view_row, 0), last)

    def _bus_name(self, row: Row, column: int) -> str:
        """Return the name of the bus in a row's bus field at column."""
        bus = self.case.buses.get(parse.bus_number(row.values[column]))
        return "" if bus is None else bus.name

    def _matches(self, row: Row, terms: list[str]) -> bool:
        """Return whether every term matches a row, as set_filter says."""
        size = len(layouts.KEYS[self.kind])
        keys = {value.lower() for value in row.values[:size]}
        names = " ".join(
            self._bus_name(row, column) for column in range(self.names))
        names = names.lower()
        return all(term in keys or term in names for term in terms)


class SensitivityTab(QWidget):
    """Edit the loads, generators, and branches of a case, then run it."""

    run_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.base_path: Path | None = None
        self.loaded: tuple[Path, int] | None = None
        self.case: parse.Case | None = None
        self.tables: dict[str, RecordTable] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.case_label = QLabel("Open a project to edit its case.")
        set_context_label(self.case_label)
        layout.addWidget(self.case_label)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.kind = QComboBox()
        for kind in layouts.KINDS:
            self.kind.addItem(TITLES[kind], kind)
        self.kind.setToolTip("The kind of record to show and edit.")
        self.kind.currentIndexChanged.connect(self.show_table)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(
            "Filter by bus number, ID, circuit, or bus name")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.apply_filter)
        self.add_button = QPushButton("Add…")
        set_button_role(self.add_button, "secondary")
        self.add_button.setToolTip(
            "Add a record at a bus, or a branch between two buses.")
        self.add_button.clicked.connect(self.add_record)
        self.remove_button = QPushButton("Remove / Restore")
        set_button_role(self.remove_button, "destructive")
        self.remove_button.setToolTip(
            "Remove the selected records, or restore removed ones.")
        self.remove_button.clicked.connect(self.remove_records)
        tools.addWidget(self.kind)
        tools.addWidget(self.filter, stretch=1)
        tools.addWidget(self.add_button)
        tools.addWidget(self.remove_button)
        layout.addLayout(tools)

        self.view = QTableView()
        configure_table(self.view)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.horizontalHeader().setMinimumSectionSize(56)
        self.view.horizontalHeader().setDefaultSectionSize(92)
        layout.addWidget(self.view, stretch=1)

        self.status = QLabel("")
        set_muted_label(self.status)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.discard_button = QPushButton("Discard Edits")
        set_button_role(self.discard_button, "secondary")
        self.discard_button.setToolTip(
            "Undo every edit and show the case as the project has it.")
        self.discard_button.clicked.connect(self.discard_edits)
        self.save_button = QPushButton("Save Edited Case…")
        set_button_role(self.save_button, "secondary")
        self.save_button.setToolTip("Write the edited case to a RAW file.")
        self.save_button.clicked.connect(self.save_case)
        self.run_button = QPushButton("Run N-1 Analysis")
        set_button_role(self.run_button, "primary")
        self.run_button.setToolTip(
            "Run GridPACK on the edited case with the project's "
            "configuration.")
        self.run_button.clicked.connect(self.run_case)
        actions.addWidget(self.discard_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.run_button)
        actions.addStretch()
        layout.addLayout(actions)
        self._enable(False)

    def set_project(self, project: Project, project_data: ProjectData) -> None:
        """Use a project's base case, reading it when the tab is shown.

        Edits are kept while the project names the same, unchanged case.
        """
        self.project = project
        try:
            self.base_path = sensitivity.base_case(project_data)
        except (OSError, ValueError) as exc:
            self.base_path = None
            self.loaded = None
            self._forget_case(str(exc))
            return
        if self.isVisible():
            self.load_case()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self.load_case()

    def load_case(self) -> None:
        """Read the base case, unless the tab last read it as it is now."""
        if self.base_path is None:
            return
        name = self.base_path.name
        try:
            key = (self.base_path, self.base_path.stat().st_mtime_ns)
        except OSError as exc:
            self._forget_case(f"{name} cannot be read: {exc}")
            return
        if key == self.loaded:
            return
        self.loaded = key
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            case = parse.read_case(self.base_path)
        except (OSError, ValueError) as exc:
            self._forget_case(f"{name} cannot be edited: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.case = case
        self.tables = {}
        self.case_label.setText(
            f"Base case: {name}, PSS/E version {case.version}, with "
            f"{len(case.buses):,} buses. Each run edits a copy; the "
            "project's case stays as it is.")
        self._enable(True)
        self.show_table()

    def table(self, kind: str) -> RecordTable:
        """Return the table of a kind of record, made when first needed."""
        if kind not in self.tables:
            table = RecordTable(self.case, kind)
            table.rejected.connect(self.status.setText)
            table.dataChanged.connect(self.update_status)
            table.rowsInserted.connect(self.update_status)
            table.modelReset.connect(self.update_status)
            self.tables[kind] = table
        return self.tables[kind]

    def show_table(self) -> None:
        """Show the chosen kind of record, filtered by the filter box."""
        if self.case is None:
            return
        table = self.table(self.kind.currentData())
        table.set_filter(self.filter.text())
        self.view.setModel(table)
        for column in range(table.names):
            self.view.setColumnWidth(column, 150)
        self.update_status()

    def apply_filter(self, text: str) -> None:
        if self.case is not None:
            self.table(self.kind.currentData()).set_filter(text)

    def add_record(self) -> None:
        """Ask for the buses of a new record, then add it to the table."""
        kind = self.kind.currentData()
        branch = kind == "branch"
        prompt = "From bus and to bus numbers:" if branch else "Bus number:"
        text, accepted = QInputDialog.getText(self, f"Add a {kind}", prompt)
        if not accepted:
            return
        try:
            buses = [int(word) for word in text.split()]
            if len(buses) != len(layouts.BUS_FIELDS[kind]):
                count = "two bus numbers" if branch else "one bus number"
                raise ValueError(f"Enter {count}.")
            self.table(kind).add(buses)
        except ValueError as exc:
            QMessageBox.warning(self, f"The {kind} cannot be added", str(exc))
            return
        self.view.scrollToBottom()
        self.view.selectRow(self.view.model().rowCount() - 1)

    def remove_records(self) -> None:
        selected = self.view.selectionModel().selectedRows()
        rows = sorted({index.row() for index in selected})
        if rows:
            self.table(self.kind.currentData()).toggle_removed(rows)
        else:
            self.status.setText("Select the rows to remove or restore.")

    def discard_edits(self) -> None:
        if not self.edits():
            return
        answer = QMessageBox.question(
            self, "Discard edits", "Undo every edit to the case?")
        if answer == QMessageBox.Yes:
            self.tables = {}
            self.show_table()

    def edits(self) -> list[patch.Edit]:
        """Return the edits of every table: loads, generators, branches."""
        edits = []
        for kind in layouts.KINDS:
            if kind in self.tables:
                edits += self.tables[kind].edits()
        return edits

    def update_status(self) -> None:
        """Say how many rows the table shows and how many edits there are."""
        model = self.view.model()
        count = model.rowCount() if model is not None else 0
        title = TITLES[self.kind.currentData()].lower()
        edits = self.edits()
        counts = f"Edits: {patch.summary(edits)}." if edits else "No edits."
        self.status.setText(f"{count:,} {title} shown. {counts}")

    def patched_case(self) -> sensitivity.PatchedCase | None:
        """Return the edited case, or None after saying why there is none."""
        edits = self.edits()
        if not edits:
            QMessageBox.information(
                self, "No edits", "Edit, add, or remove a record first.")
            return None
        try:
            text = patch.apply(self.case, edits)
        except ValueError as exc:
            QMessageBox.warning(self, "The edits need attention", str(exc))
            return None
        return sensitivity.PatchedCase(
            self.base_path.name, text, patch.describe(self.case, edits),
            patch.summary(edits))

    def save_case(self) -> None:
        case = self.patched_case()
        if case is None:
            return
        folder = self.project.exports_dir if self.project else Path.home()
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Save edited case", str(folder / case.file_name),
            "PSS/E RAW (*.raw *.RAW);;All Files (*)")
        if file_name:
            Path(file_name).parent.mkdir(parents=True, exist_ok=True)
            parse.write_case(file_name, case.text)
            self.status.setText(f"Saved the edited case: {file_name}")

    def run_case(self) -> None:
        case = self.patched_case()
        if case is None:
            return
        notes = patch.warnings(self.case, self.edits())
        if notes:
            answer = QMessageBox.question(
                self, "Run the edited case?",
                "GridPACK may not model these edits as you expect:\n\n"
                + "\n\n".join(notes) + "\n\nRun it anyway?")
            if answer != QMessageBox.Yes:
                return
        self.run_requested.emit(case)

    def _forget_case(self, message: str) -> None:
        """Clear the tab and say why it has no case to edit."""
        self.case = None
        self.tables = {}
        self.view.setModel(None)
        self.case_label.setText(message)
        self.status.setText("")
        self._enable(False)

    def _enable(self, enabled: bool) -> None:
        """Enable or disable every control that needs a case."""
        controls = (self.kind, self.filter, self.add_button,
                    self.remove_button, self.discard_button,
                    self.save_button, self.run_button)
        for control in controls:
            control.setEnabled(enabled)
