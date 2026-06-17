from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

try:  # Matplotlib is an optional analysis dependency.
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover - exercised only on systems without matplotlib.
    FigureCanvas = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]

from gridpack_workbench.analysis.distributions import distribution_variables_from_master, generate_distribution_exports
from gridpack_workbench.analysis.master import UTILIZATION_COLUMNS, ensure_branch_master_exports
from gridpack_workbench.analysis.dataset import RunAnalysisDataset, build_run_analysis
from gridpack_workbench.analysis.summary import generate_decision_support_report
from gridpack_workbench.core.project import Project
from gridpack_workbench.gui.analysis_view_models import (
    CONTINGENCY_TABLE_COLUMNS,
    DISTRIBUTION_OUTPUT_COLUMNS,
    THERMAL_TABLE_COLUMNS,
    VOLTAGE_TABLE_COLUMNS,
    filter_performance_rows,
    numeric_value,
    render_analysis_overview_html,
    should_select_distribution_variable,
    top_numeric_rows,
)
from gridpack_workbench.gui.table_utils import populate_table
from gridpack_workbench.gui.theme import set_button_role


class AnalysisTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.last_report: Path | None = None
        self.current_dataset: RunAnalysisDataset | None = None
        self.current_master: dict[str, object] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.project_label = QLabel("No project loaded.")
        self.project_label.setObjectName("contextLabel")
        layout.addWidget(self.project_label)

        run_row = QHBoxLayout()
        self.run_combo = QComboBox()
        refresh = QPushButton("Refresh Runs")
        set_button_role(refresh, "secondary")
        refresh.clicked.connect(lambda: self.refresh_runs())
        analyze = QPushButton("Generate DSS Analysis")
        set_button_role(analyze, "primary")
        analyze.clicked.connect(self.generate_report)
        open_report = QPushButton("Open HTML Report")
        set_button_role(open_report, "secondary")
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
        self.distribution_tab = self._build_distributions_tab()
        self.tabs.addTab(self.distribution_tab, "Distributions")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, stretch=1)

        self._show_empty_state()

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
                self._refresh_distribution_variables()
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
            self.current_master = summary.get("master", {}) if isinstance(summary.get("master"), dict) else {}
            self._refresh_filters()
            self._refresh_distribution_variables()
            self._render_dataset()
            master_cleaned = self.current_master.get("master_cleaned_csv", "")
            QMessageBox.information(
                self,
                "Analysis generated",
                "Decision support analysis generated:\n"
                f"{self.current_dataset.manifest_path}\n\n"
                f"Master dataset:\n{master_cleaned}",
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
            self.thermal_canvas = QLabel(
                "Install the analysis optional dependencies to enable embedded Matplotlib charts."
            )
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

    def _build_distributions_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        control_row = QHBoxLayout()
        self.distribution_metric = QComboBox()
        for column in UTILIZATION_COLUMNS:
            self.distribution_metric.addItem(column, column)
        generate = QPushButton("Generate Selected Distributions")
        set_button_role(generate, "primary")
        generate.clicked.connect(self.generate_distributions)
        control_row.addWidget(QLabel("Utilization metric"))
        control_row.addWidget(self.distribution_metric)
        control_row.addWidget(generate)
        control_row.addStretch()
        layout.addLayout(control_row)

        layout.addWidget(QLabel("Independent variables"))
        self.distribution_variables = QListWidget()
        self.distribution_variables.setSelectionMode(QAbstractItemView.MultiSelection)
        layout.addWidget(self.distribution_variables, stretch=1)

        self.distribution_outputs = QTableWidget(0, 4)
        self.distribution_outputs.setHorizontalHeaderLabels(["Variable", "Table CSV", "Graph PNG", "Code Path"])
        self.distribution_outputs.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("Generated outputs"))
        layout.addWidget(self.distribution_outputs, stretch=1)
        return widget

    def _show_empty_state(self) -> None:
        self.overview.setHtml(
            """
            <h2>Decision Support Analysis</h2>
            <p>Select a run and click <b>Generate DSS Analysis</b> to parse GridPACK outputs,
            compute decision-support metrics, generate normalized tables, and create an HTML report.</p>
            """
        )
        populate_table(self.thermal_table, [], [])
        populate_table(self.voltage_table, [], [])
        populate_table(self.contingency_table, [], [])
        populate_table(self.distribution_outputs, [], [])

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

    def _refresh_distribution_variables(self) -> None:
        self.distribution_variables.clear()
        run_dir = self.selected_run_dir()
        if not run_dir:
            return
        try:
            master = ensure_branch_master_exports(run_dir, self.current_dataset)
            self.current_master = master.as_dict()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot prepare master dataset", str(exc))
            return

        variables = distribution_variables_from_master(run_dir)
        for variable in variables:
            item = QListWidgetItem(variable)
            if should_select_distribution_variable(variable):
                item.setSelected(True)
            self.distribution_variables.addItem(item)

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.distribution_tab:
            self._refresh_distribution_variables()

    def generate_distributions(self) -> None:
        run_dir = self.selected_run_dir()
        if not run_dir:
            QMessageBox.warning(self, "No run selected", "Select a run first.")
            return
        if self.distribution_variables.count() == 0:
            self._refresh_distribution_variables()
        variables = [item.text() for item in self.distribution_variables.selectedItems()]
        if not variables:
            QMessageBox.warning(self, "No variables selected", "Select at least one independent variable.")
            return
        try:
            results = generate_distribution_exports(
                run_dir,
                variables,
                utilization_metric=self.distribution_metric.currentData(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Distribution generation failed", str(exc))
            return

        rows = [
            {
                "variable": result.independent_variable,
                "table_csv": str(result.table_csv),
                "graph_png": str(result.graph_png),
                "code_path": str(result.code_path),
            }
            for result in results
        ]
        populate_table(self.distribution_outputs, rows, DISTRIBUTION_OUTPUT_COLUMNS)
        QMessageBox.information(self, "Distributions generated", f"Generated {len(results)} graph/table pairs.")

    def _render_dataset(self) -> None:
        self._render_overview()
        self._render_thermal()
        self._render_voltage()
        self._render_contingencies()

    def _render_overview(self) -> None:
        if not self.current_dataset:
            return
        self.overview.setHtml(
            render_analysis_overview_html(
                self.current_dataset.run_dir,
                self.current_dataset.manifest_path,
                self.current_dataset.metrics,
                self.current_master,
            )
        )

    def _render_thermal(self) -> None:
        rows = top_numeric_rows(
            self._filtered_perf_rows(),
            "max_utilization_pct",
            self.top_n.value(),
            reverse=True,
            missing_value=0.0,
        )
        populate_table(self.thermal_table, rows, THERMAL_TABLE_COLUMNS)
        if FigureCanvas and Figure and self.thermal_figure and rows:
            self.thermal_figure.clear()
            axis = self.thermal_figure.add_subplot(111)
            labels = [str(row.get("row_index", "")) for row in rows[:15]]
            values = [numeric_value(row.get("max_utilization_pct"), 0.0) for row in rows[:15]]
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
        rows = top_numeric_rows(
            self._table_rows("vmag_mm"),
            "min_value",
            self.top_n.value(),
            reverse=False,
            missing_value=999.0,
        )
        populate_table(self.voltage_table, rows, VOLTAGE_TABLE_COLUMNS)

    def _render_contingencies(self) -> None:
        if not self.current_dataset:
            return
        contingency = self.current_dataset.metrics.get("contingencies", {})
        rows = contingency.get("worst_by_performance_index", []) if isinstance(contingency, dict) else []
        contingency_count = contingency.get("contingency_count", 0) if isinstance(contingency, dict) else 0
        self.contingency_summary.setHtml(f"<p><b>Contingencies:</b> {contingency_count}</p>")
        populate_table(self.contingency_table, rows[: self.top_n.value()], CONTINGENCY_TABLE_COLUMNS)

    def _table_rows(self, table_name: str) -> list[dict[str, object]]:
        if not self.current_dataset:
            return []
        table = self.current_dataset.tables.get(table_name)
        return list(table.rows) if table else []

    def _filtered_perf_rows(self) -> list[dict[str, object]]:
        area = self.area_filter.currentData() if self.area_filter.count() else ""
        voltage_class = self.voltage_filter.currentData() if self.voltage_filter.count() else ""
        return filter_performance_rows(self._table_rows("perf_mm"), area, voltage_class)
