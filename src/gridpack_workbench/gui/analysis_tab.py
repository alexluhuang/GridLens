from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gridpack_workbench.analysis.summary import generate_run_report
from gridpack_workbench.core.project import Project


class AnalysisTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.last_report: Path | None = None

        layout = QVBoxLayout(self)
        self.project_label = QLabel("No project loaded.")
        layout.addWidget(self.project_label)

        run_row = QHBoxLayout()
        self.run_combo = QComboBox()
        refresh = QPushButton("Refresh Runs")
        refresh.clicked.connect(lambda: self.refresh_runs())
        run_row.addWidget(QLabel("Run"))
        run_row.addWidget(self.run_combo, stretch=1)
        run_row.addWidget(refresh)
        layout.addLayout(run_row)

        options_row = QHBoxLayout()
        self.include_success = QCheckBox("Success summary")
        self.include_success.setChecked(True)
        self.include_inventory = QCheckBox("Output inventory")
        self.include_inventory.setChecked(True)
        self.include_chart = QCheckBox("Chart")
        self.include_chart.setChecked(True)
        options_row.addWidget(self.include_success)
        options_row.addWidget(self.include_inventory)
        options_row.addWidget(self.include_chart)
        options_row.addStretch()
        layout.addLayout(options_row)

        action_row = QHBoxLayout()
        analyze = QPushButton("Generate Report")
        analyze.clicked.connect(self.generate_report)
        open_report = QPushButton("Open HTML Report")
        open_report.clicked.connect(self.open_report)
        action_row.addWidget(analyze)
        action_row.addWidget(open_report)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.preview = QTextBrowser()
        layout.addWidget(self.preview, stretch=1)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.project_label.setText(f"Project: {project.name} ({project.root_dir})")
        self.refresh_runs()

    def refresh_runs(self, select_run: Path | None = None) -> None:
        self.run_combo.clear()
        if not self.project:
            return
        for run_dir in self.project.list_runs():
            self.run_combo.addItem(run_dir.name, str(run_dir))
            if select_run and run_dir.resolve() == Path(select_run).resolve():
                self.run_combo.setCurrentIndex(self.run_combo.count() - 1)

    def select_run(self, run_dir: object) -> None:
        path = Path(str(run_dir)).resolve()
        for index in range(self.run_combo.count()):
            if Path(self.run_combo.itemData(index)).resolve() == path:
                self.run_combo.setCurrentIndex(index)
                break

    def selected_run_dir(self) -> Path | None:
        value = self.run_combo.currentData()
        return Path(value) if value else None

    def generate_report(self) -> None:
        run_dir = self.selected_run_dir()
        if not run_dir:
            QMessageBox.warning(self, "No run selected", "Select a completed run first.")
            return
        try:
            summary = generate_run_report(run_dir)
            self.last_report = Path(summary["html_report"])
            self.preview.setHtml(
                f"""
                <h1>Report Generated</h1>
                <p><b>Run:</b> {summary['run_dir']}</p>
                <p><b>Success:</b> {summary['success_count']} &nbsp;
                   <b>Failed:</b> {summary['failure_count']} &nbsp;
                   <b>Unknown:</b> {summary['unknown_count']}</p>
                <p><b>Output files:</b> {summary['output_file_count']}</p>
                <p><b>HTML report:</b> {summary['html_report']}</p>
                <p><b>Inventory CSV:</b> {summary['inventory_csv']}</p>
                """
            )
        except Exception as exc:
            QMessageBox.critical(self, "Analysis failed", str(exc))

    def open_report(self) -> None:
        if self.last_report and self.last_report.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_report)))
