from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:  # Matplotlib is an optional analysis dependency.
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover - exercised only on systems without matplotlib.
    FigureCanvas = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]

from gridpack_workbench.analysis.agent import NemoClawAgentService
from gridpack_workbench.analysis.dataset import RunAnalysisDataset, build_run_analysis
from gridpack_workbench.analysis.summary import generate_decision_support_report
from gridpack_workbench.core.app_settings import AppSettings
from gridpack_workbench.core.project import Project


class AnalysisTab(QWidget):
    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or AppSettings.load()
        self.project: Project | None = None
        self.last_report: Path | None = None
        self.current_dataset: RunAnalysisDataset | None = None
        self.agent_service = NemoClawAgentService(self.settings)

        layout = QVBoxLayout(self)
        self.project_label = QLabel("No project loaded.")
        layout.addWidget(self.project_label)

        run_row = QHBoxLayout()
        self.run_combo = QComboBox()
        refresh = QPushButton("Refresh Runs")
        refresh.clicked.connect(lambda: self.refresh_runs())
        analyze = QPushButton("Generate DSS Analysis")
        analyze.clicked.connect(self.generate_report)
        open_report = QPushButton("Open HTML Report")
        open_report.clicked.connect(self.open_report)
        run_row.addWidget(QLabel("Run"))
        run_row.addWidget(self.run_combo, stretch=1)
        run_row.addWidget(refresh)
        run_row.addWidget(analyze)
        run_row.addWidget(open_report)
        layout.addLayout(run_row)

        self.tabs = QTabWidget()
        self.overview = QTextBrowser()
        self.tabs.addTab(self.overview, "Overview")
        self.tabs.addTab(self._build_thermal_tab(), "Thermal Utilization")
        self.tabs.addTab(self._build_voltage_tab(), "Voltage / Reactive")
        self.tabs.addTab(self._build_contingency_tab(), "Contingencies")
        self.tabs.addTab(self._build_assistant_tab(), "Assistant")
        layout.addWidget(self.tabs, stretch=1)

        self._show_empty_state()
        self._refresh_assistant_state()

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
            self.current_dataset = build_run_analysis(run_dir)
            summary = generate_decision_support_report(run_dir, self.current_dataset)
            self.last_report = Path(summary["html_report"])
            self._refresh_filters()
            self._render_dataset()
            QMessageBox.information(
                self,
                "Analysis generated",
                f"Decision support analysis generated:\n{self.current_dataset.manifest_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Analysis failed", str(exc))

    def open_report(self) -> None:
        if self.last_report and self.last_report.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_report)))
            return
        run_dir = self.selected_run_dir()
        candidate = run_dir / "reports" / "decision_support_report.html" if run_dir else None
        if candidate and candidate.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))

    def _build_thermal_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        filter_row = QHBoxLayout()
        self.area_filter = QComboBox()
        self.voltage_filter = QComboBox()
        self.top_n = QSpinBox()
        self.top_n.setRange(5, 500)
        self.top_n.setValue(25)
        self.top_n.valueChanged.connect(self._render_thermal)
        self.area_filter.currentIndexChanged.connect(self._render_thermal)
        self.voltage_filter.currentIndexChanged.connect(self._render_thermal)
        filter_row.addWidget(QLabel("Area"))
        filter_row.addWidget(self.area_filter)
        filter_row.addWidget(QLabel("Voltage class"))
        filter_row.addWidget(self.voltage_filter)
        filter_row.addWidget(QLabel("Top N"))
        filter_row.addWidget(self.top_n)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        if FigureCanvas and Figure:
            self.thermal_figure = Figure(figsize=(7, 2.8))
            self.thermal_canvas = FigureCanvas(self.thermal_figure)
            layout.addWidget(self.thermal_canvas)
        else:
            self.thermal_figure = None
            self.thermal_canvas = QLabel("Install the analysis optional dependencies to enable embedded Matplotlib charts.")
            layout.addWidget(self.thermal_canvas)

        self.thermal_table = QTableWidget(0, 9)
        layout.addWidget(self.thermal_table, stretch=1)
        return widget

    def _build_voltage_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.voltage_summary = QTextBrowser()
        self.voltage_summary.setMaximumHeight(150)
        self.voltage_table = QTableWidget(0, 8)
        layout.addWidget(self.voltage_summary)
        layout.addWidget(self.voltage_table, stretch=1)
        return widget

    def _build_contingency_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.contingency_summary = QTextBrowser()
        self.contingency_summary.setMaximumHeight(150)
        self.contingency_table = QTableWidget(0, 6)
        layout.addWidget(self.contingency_summary)
        layout.addWidget(self.contingency_table, stretch=1)
        return widget

    def _build_assistant_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        box = QGroupBox("NemoClaw Local Agent")
        box_layout = QVBoxLayout(box)
        self.assistant_status = QLabel()
        self.assistant_status.setWordWrap(True)
        self.assistant_question = QTextEdit()
        self.assistant_question.setPlaceholderText("Ask about success rates, thermal bottlenecks, voltage, line faults, or another parsed result.")
        self.assistant_question.setMaximumHeight(110)
        ask = QPushButton("Ask Assistant")
        ask.clicked.connect(self.ask_assistant)
        self.ask_button = ask
        self.assistant_answer = QTextBrowser()
        box_layout.addWidget(self.assistant_status)
        box_layout.addWidget(QLabel("Question"))
        box_layout.addWidget(self.assistant_question)
        box_layout.addWidget(ask)
        box_layout.addWidget(self.assistant_answer, stretch=1)
        layout.addWidget(box)
        return widget

    def ask_assistant(self) -> None:
        run_dir = self.selected_run_dir()
        question = self.assistant_question.toPlainText().strip()
        if not run_dir:
            QMessageBox.warning(self, "No run selected", "Select a run first.")
            return
        if not question:
            QMessageBox.warning(self, "No question", "Enter a question about the selected run.")
            return
        try:
            answer = self.agent_service.answer(run_dir, question)
            self.assistant_answer.setHtml(answer.to_html())
        except Exception as exc:
            QMessageBox.critical(self, "Assistant failed", str(exc))

    def _show_empty_state(self) -> None:
        self.overview.setHtml(
            """
            <h2>Decision Support Analysis</h2>
            <p>Select a run and click <b>Generate DSS Analysis</b> to parse GridPACK outputs,
            compute decision-support metrics, generate normalized tables, and create an HTML report.</p>
            """
        )
        self._fill_table(self.thermal_table, [], [])
        self._fill_table(self.voltage_table, [], [])
        self._fill_table(self.contingency_table, [], [])

    def _refresh_assistant_state(self) -> None:
        configured = self.agent_service.is_configured()
        self.ask_button.setEnabled(configured)
        self.assistant_status.setText(self.agent_service.configuration_status())

    def _refresh_filters(self) -> None:
        self.area_filter.blockSignals(True)
        self.voltage_filter.blockSignals(True)
        self.area_filter.clear()
        self.voltage_filter.clear()
        self.area_filter.addItem("All", "")
        self.voltage_filter.addItem("All", "")
        rows = self._table_rows("perf_mm")
        areas = sorted({str(row.get("area", "")) for row in rows if row.get("area")})
        voltage_classes = sorted({str(row.get("voltage_class", "")) for row in rows if row.get("voltage_class")})
        for area in areas:
            self.area_filter.addItem(area, area)
        for voltage_class in voltage_classes:
            self.voltage_filter.addItem(voltage_class, voltage_class)
        self.area_filter.blockSignals(False)
        self.voltage_filter.blockSignals(False)

    def _render_dataset(self) -> None:
        self._render_overview()
        self._render_thermal()
        self._render_voltage()
        self._render_contingencies()
        self._refresh_assistant_state()

    def _render_overview(self) -> None:
        if not self.current_dataset:
            return
        metrics = self.current_dataset.metrics
        success = metrics.get("success", {}) if isinstance(metrics.get("success"), dict) else {}
        thermal = metrics.get("thermal", {}) if isinstance(metrics.get("thermal"), dict) else {}
        voltage = metrics.get("voltage", {}) if isinstance(metrics.get("voltage"), dict) else {}
        notes = metrics.get("notes", [])
        self.overview.setHtml(
            f"""
            <h2>Decision Support Overview</h2>
            <p><b>Run:</b> {html.escape(str(self.current_dataset.run_dir))}</p>
            <p><b>Manifest:</b> {html.escape(str(self.current_dataset.manifest_path))}</p>
            <table>
              <tr><th>Metric</th><th>Value</th></tr>
              <tr><td>Contingencies</td><td>{success.get('total', 0)}</td></tr>
              <tr><td>Success rate</td><td>{success.get('success_rate_pct', 0)}%</td></tr>
              <tr><td>Failures</td><td>{success.get('failure', 0)}</td></tr>
              <tr><td>Thermal facilities</td><td>{thermal.get('facility_count', 0)}</td></tr>
              <tr><td>Mean worst utilization</td><td>{thermal.get('mean_worst_utilization_pct', 'n/a')}%</td></tr>
              <tr><td>Stress Gini</td><td>{thermal.get('gini_worst_utilization', 'n/a')}</td></tr>
              <tr><td>Top 20% stress share</td><td>{thermal.get('top_20_pct_stress_share', 'n/a')}</td></tr>
              <tr><td>Low voltage violations</td><td>{voltage.get('low_voltage_violations', 0)}</td></tr>
              <tr><td>High voltage violations</td><td>{voltage.get('high_voltage_violations', 0)}</td></tr>
            </table>
            <h3>Assumptions And Data Notes</h3>
            <ul>{''.join(f'<li>{html.escape(str(note))}</li>' for note in notes)}</ul>
            """
        )

    def _render_thermal(self) -> None:
        rows = self._filtered_perf_rows()
        rows.sort(key=lambda row: float(row.get("max_utilization_pct") or 0), reverse=True)
        rows = rows[: self.top_n.value()]
        columns = [
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "voltage_class",
            "area",
            "base_utilization_pct",
            "max_utilization_pct",
            "max_contingency",
        ]
        self._fill_table(self.thermal_table, rows, columns)
        if FigureCanvas and Figure and self.thermal_figure and rows:
            self.thermal_figure.clear()
            axis = self.thermal_figure.add_subplot(111)
            labels = [str(row.get("row_index", "")) for row in rows[:15]]
            values = [float(row.get("max_utilization_pct") or 0) for row in rows[:15]]
            axis.bar(labels, values, color="#2f6f9f")
            axis.axhline(80, color="#a66a00", linestyle="--", linewidth=1)
            axis.axhline(100, color="#a33d3d", linestyle="--", linewidth=1)
            axis.set_title("Worst-Contingency Thermal Utilization")
            axis.set_ylabel("Utilization (%)")
            axis.set_xlabel("Facility row index")
            axis.tick_params(axis="x", labelrotation=45)
            self.thermal_figure.tight_layout()
            self.thermal_canvas.draw()

    def _render_voltage(self) -> None:
        if not self.current_dataset:
            return
        voltage = self.current_dataset.metrics.get("voltage", {})
        if not isinstance(voltage, dict):
            voltage = {}
        self.voltage_summary.setHtml(
            f"""
            <p><b>Voltage thresholds:</b> {voltage.get('min_voltage_threshold', 0.9)}
            to {voltage.get('max_voltage_threshold', 1.1)} p.u.</p>
            <p><b>Low violations:</b> {voltage.get('low_voltage_violations', 0)}
            &nbsp; <b>High violations:</b> {voltage.get('high_voltage_violations', 0)}</p>
            """
        )
        rows = self._table_rows("vmag_mm")
        rows.sort(key=lambda row: float(row.get("min_value") or 999))
        columns = ["row_index", "bus_id", "bus_name", "base_kv", "area", "min_value", "min_voltage_margin", "min_contingency"]
        self._fill_table(self.voltage_table, rows[: self.top_n.value()], columns)

    def _render_contingencies(self) -> None:
        if not self.current_dataset:
            return
        contingency = self.current_dataset.metrics.get("contingencies", {})
        rows = contingency.get("worst_by_performance_index", []) if isinstance(contingency, dict) else []
        self.contingency_summary.setHtml(
            f"<p><b>Contingencies:</b> {contingency.get('contingency_count', 0) if isinstance(contingency, dict) else 0}</p>"
        )
        columns = [
            "contingency_index",
            "success",
            "violation",
            "isolated_warning",
            "performance_index_sum",
            "performance_index_average",
        ]
        self._fill_table(self.contingency_table, rows[: self.top_n.value()], columns)

    def _table_rows(self, table_name: str) -> list[dict[str, object]]:
        if not self.current_dataset:
            return []
        table = self.current_dataset.tables.get(table_name)
        return list(table.rows) if table else []

    def _filtered_perf_rows(self) -> list[dict[str, object]]:
        rows = self._table_rows("perf_mm")
        area = self.area_filter.currentData() if self.area_filter.count() else ""
        voltage_class = self.voltage_filter.currentData() if self.voltage_filter.count() else ""
        if area:
            rows = [row for row in rows if str(row.get("area")) == str(area)]
        if voltage_class:
            rows = [row for row in rows if str(row.get("voltage_class")) == str(voltage_class)]
        return rows

    def _fill_table(self, table: QTableWidget, rows: list[dict[str, object]], columns: list[str]) -> None:
        table.clear()
        table.setColumnCount(len(columns))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setStretchLastSection(True)
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                item = QTableWidgetItem(str(row.get(column, "")))
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                table.setItem(row_index, column_index, item)
