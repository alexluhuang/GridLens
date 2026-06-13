from __future__ import annotations

import json
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gridpack_workbench.analysis.parsers import list_output_files
from gridpack_workbench.analysis.summary import export_run_zip
from gridpack_workbench.core.project import Project


class ResultsTab(QWidget):
    run_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None

        layout = QVBoxLayout(self)
        self.project_label = QLabel("No project loaded.")
        layout.addWidget(self.project_label)

        split = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()

        self.run_list = QListWidget()
        self.run_list.currentItemChanged.connect(self.on_run_selected)
        left.addWidget(QLabel("Runs"))
        left.addWidget(self.run_list)

        button_row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(lambda: self.refresh_runs())
        open_run = QPushButton("Open Run")
        open_run.clicked.connect(self.open_selected_run)
        export_zip = QPushButton("Export ZIP")
        export_zip.clicked.connect(self.export_selected_run)
        button_row.addWidget(refresh)
        button_row.addWidget(open_run)
        button_row.addWidget(export_zip)
        left.addLayout(button_row)

        self.output_table = QTableWidget(0, 4)
        self.output_table.setHorizontalHeaderLabels(["File", "Path", "Size", "Type"])
        self.output_table.horizontalHeader().setStretchLastSection(True)
        right.addWidget(QLabel("Output files"))
        right.addWidget(self.output_table)

        split.addLayout(left, stretch=1)
        split.addLayout(right, stretch=2)
        layout.addLayout(split, stretch=1)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.project_label.setText(f"Project: {project.name} ({project.root_dir})")
        self.refresh_runs()

    def refresh_runs(self, select_run: Path | None = None) -> None:
        self.run_list.clear()
        if not self.project:
            return

        for run_dir in self.project.list_runs():
            status = self._read_status(run_dir)
            label = f"{run_dir.name}    {status}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(run_dir))
            self.run_list.addItem(item)
            if select_run and run_dir.resolve() == Path(select_run).resolve():
                self.run_list.setCurrentItem(item)

        if self.run_list.count() and not self.run_list.currentItem():
            self.run_list.setCurrentRow(0)

    def _read_status(self, run_dir: Path) -> str:
        status_file = run_dir / "status.json"
        if not status_file.exists():
            return "not started"
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            return data.get("status", "unknown")
        except json.JSONDecodeError:
            return "unknown"

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
        files = list_output_files(run_dir)
        self.output_table.setRowCount(len(files))
        for row, output in enumerate(files):
            self.output_table.setItem(row, 0, QTableWidgetItem(output.file_name))
            self.output_table.setItem(row, 1, QTableWidgetItem(output.relative_path))
            self.output_table.setItem(row, 2, QTableWidgetItem(str(output.size_bytes)))
            self.output_table.setItem(row, 3, QTableWidgetItem(output.suffix))
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
