from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from gridlens.analysis.parsers import list_output_files
from gridlens.analysis.summary import export_run_zip
from gridlens.core.project import Project
from gridlens.gui.results_view_models import (
    OUTPUT_TABLE_COLUMNS,
    output_file_rows,
    read_run_status,
    run_list_label,
)
from gridlens.gui.table_utils import populate_table
from gridlens.gui.theme import configure_table, set_button_role, set_context_label


class ResultsTab(QWidget):
    run_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.project_label = QLabel("No project loaded.")
        set_context_label(self.project_label)
        layout.addWidget(self.project_label)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        left_panel = QWidget()
        right_panel = QWidget()
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)

        self.run_list = QListWidget()
        self.run_list.setAlternatingRowColors(True)
        self.run_list.setTextElideMode(Qt.ElideMiddle)
        self.run_list.setToolTip("Completed project runs.")
        self.run_list.currentItemChanged.connect(self.on_run_selected)
        runs_label = QLabel("Runs")
        runs_label.setObjectName("sectionTitle")
        left.addWidget(runs_label)
        left.addWidget(self.run_list)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        refresh = QPushButton("Refresh")
        set_button_role(refresh, "secondary")
        refresh.setToolTip("Refresh the run list.")
        refresh.clicked.connect(lambda: self.refresh_runs())
        open_run = QPushButton("Open Run")
        set_button_role(open_run, "secondary")
        open_run.setToolTip("Open the selected run folder.")
        open_run.clicked.connect(self.open_selected_run)
        export_zip = QPushButton("Export ZIP")
        set_button_role(export_zip, "primary")
        export_zip.setToolTip("Export the selected run as a ZIP package.")
        export_zip.clicked.connect(self.export_selected_run)
        button_row.addWidget(refresh)
        button_row.addWidget(open_run)
        button_row.addWidget(export_zip)
        left.addLayout(button_row)

        self.output_table = QTableWidget(0, len(OUTPUT_TABLE_COLUMNS))
        self.output_table.setHorizontalHeaderLabels(OUTPUT_TABLE_COLUMNS)
        configure_table(self.output_table)
        self.output_table.horizontalHeader().setStretchLastSection(True)
        self.output_table.setToolTip("Files produced by the selected run.")
        output_label = QLabel("Output files")
        output_label.setObjectName("sectionTitle")
        right.addWidget(output_label)
        right.addWidget(self.output_table)

        split.addWidget(left_panel)
        split.addWidget(right_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, stretch=1)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.project_label.setText(f"Project: {project.name} ({project.root_dir})")
        self.refresh_runs()

    def refresh_runs(self, select_run: Path | None = None) -> None:
        self.run_list.clear()
        if not self.project:
            return

        for run_dir in self.project.list_runs():
            label = run_list_label(run_dir, read_run_status(run_dir))
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(run_dir))
            item.setToolTip(str(run_dir))
            self.run_list.addItem(item)
            if select_run and run_dir.resolve() == Path(select_run).resolve():
                self.run_list.setCurrentItem(item)

        if self.run_list.count() and not self.run_list.currentItem():
            self.run_list.setCurrentRow(0)

    def selected_run_dir(self) -> Path | None:
        item = self.run_list.currentItem()
        if not item:
            return None
        return Path(item.data(Qt.UserRole))

    def on_run_selected(self, current=None, previous=None) -> None:
        run_dir = self.selected_run_dir()
        self.output_table.setRowCount(0)
        if not run_dir:
            return
        rows = output_file_rows(list_output_files(run_dir))
        populate_table(self.output_table, rows, OUTPUT_TABLE_COLUMNS)
        self.run_selected.emit(run_dir)

    def open_selected_run(self) -> None:
        run_dir = self.selected_run_dir()
        if run_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(run_dir)))

    def export_selected_run(self) -> None:
        run_dir = self.selected_run_dir()
        if not run_dir:
            return
        try:
            zip_path = export_run_zip(run_dir)
            QMessageBox.information(self, "Export complete", f"Exported run package:\n{zip_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
