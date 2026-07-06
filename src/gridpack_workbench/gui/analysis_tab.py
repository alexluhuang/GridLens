from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from pathlib import Path
import textwrap
import traceback
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

os.environ.setdefault("MPLCONFIGDIR", "/tmp/gridpack-workbench-matplotlib")

try:  # Matplotlib is an optional analysis dependency.
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover - exercised only on systems without matplotlib.
    FigureCanvas = None  # type: ignore[assignment]
    NavigationToolbar = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]

from gridpack_workbench.analysis.csv_flat import (
    CSV_FLAT_ALLOW_CPU_DASK_ENV,
    CSV_FLAT_RESULTS_TABLE,
    cpu_dask_fallback_warning,
)
from gridpack_workbench.analysis.dataset import RunAnalysisDataset
from gridpack_workbench.analysis.interactive import (
    AnalysisBuildResult,
    build_interactive_analysis_result as _build_analysis_result,
)
from gridpack_workbench.analysis.utilization import UtilizationBranchOptions
from gridpack_workbench.core.project import Project
from gridpack_workbench.gui.analysis_view_models import (
    numeric_value,
    summarize_control_area_utilization,
    summarize_voltage_group_utilization,
)
from gridpack_workbench.gui.theme import set_button_role


CONTROL_AREA_FULL_WIDTH_ROWS = 36
CONTROL_AREA_MIN_HEIGHT = 360
CONTROL_AREA_TOP_BOTTOM_PADDING = 150
CONTROL_AREA_ROW_PIXELS = 26
CONTROL_AREA_LABEL_LIMIT = 46


def _csv_flat_runtime_status(dataset: RunAnalysisDataset | None) -> str:
    if not dataset:
        return ""
    table = dataset.tables.get(CSV_FLAT_RESULTS_TABLE)
    if not table:
        return ""
    for note in table.notes:
        if note.startswith("RAPIDS dask-cudf GPU backend was used") or note.startswith("RAPIDS cuDF GPU backend was used"):
            return "RAPIDS GPU backend used."
        if note.startswith("CPU Dask backend was used"):
            return "CPU Dask backend used; RAPIDS was not active."
        if "Python streaming" in note or "streamed from the full file" in note:
            return "Python streaming fallback used for csv-flat aggregation."
    return ""


def _build_analysis_result_in_process(run_dir: Path, branch_options: UtilizationBranchOptions) -> AnalysisBuildResult:
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        return executor.submit(_build_analysis_result, run_dir, branch_options).result()


class AnalysisWorker(QThread):
    finished_analysis = Signal(object)
    failed_analysis = Signal(str)

    def __init__(self, run_dir: Path, branch_options: UtilizationBranchOptions) -> None:
        super().__init__()
        self.run_dir = run_dir
        self.branch_options = branch_options

    def run(self) -> None:
        try:
            self.finished_analysis.emit(_build_analysis_result_in_process(self.run_dir, self.branch_options))
        except Exception:
            self.failed_analysis.emit(traceback.format_exc())


class AnalysisTab(QWidget):
    def __init__(self, *, transformer_analysis: bool = False) -> None:
        super().__init__()
        self.transformer_analysis = transformer_analysis
        self.project: Project | None = None
        self.current_dataset: RunAnalysisDataset | None = None
        self.group_branch_rows: list[dict[str, object]] = []
        self.max_line_rows: list[dict[str, object]] = []
        self.control_area_rows: list[dict[str, object]] = []
        self.voltage_group_rows: list[dict[str, object]] = []
        self.line_rows: list[dict[str, object]] = []
        self.selected_control_areas: set[str] = set()
        self.selected_voltage_groups: set[str] = set()
        self.control_area_click_items: list[tuple[object, dict[str, object]]] = []
        self.voltage_group_click_items: list[tuple[object, dict[str, object]]] = []
        self.analysis_worker: AnalysisWorker | None = None
        self._wide_layout: bool | None = None
        self._dense_control_area_layout: bool | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.project_label = QLabel("No project loaded.")
        self.project_label.setObjectName("contextLabel")
        layout.addWidget(self.project_label)

        run_row = QHBoxLayout()
        self.run_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh Runs")
        set_button_role(self.refresh_button, "secondary")
        self.refresh_button.clicked.connect(lambda: self.refresh_runs())
        self.analyze_button = QPushButton("Generate Graphs")
        set_button_role(self.analyze_button, "primary")
        self.analyze_button.clicked.connect(self.generate_graphs)
        run_row.addWidget(QLabel("Run"))
        run_row.addWidget(self.run_combo, stretch=1)
        run_row.addWidget(self.refresh_button)
        run_row.addWidget(self.analyze_button)
        layout.addLayout(run_row)

        self.status_label = QLabel(f"Select a completed run and generate the three {self._analysis_noun()} graphs.")
        self.status_label.setObjectName("mutedLabel")
        layout.addWidget(self.status_label)

        if FigureCanvas and Figure and NavigationToolbar:
            self._build_chart_area(layout)
        else:
            missing = QLabel(
                "Install the analysis optional dependencies to enable interactive embedded charts."
            )
            missing.setObjectName("contextLabel")
            layout.addWidget(missing, stretch=1)

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
                break

    def selected_run_dir(self) -> Path | None:
        value = self.run_combo.currentData()
        return Path(value) if value else None

    def generate_graphs(self) -> None:
        if self.analysis_worker and self.analysis_worker.isRunning():
            self.status_label.setText("Analysis is already running...")
            return
        run_dir = self.selected_run_dir()
        if not run_dir:
            QMessageBox.warning(self, "No run selected", "Select a completed run first.")
            return
        cpu_dask_warning = cpu_dask_fallback_warning(run_dir)
        if cpu_dask_warning:
            QMessageBox.warning(self, "CPU Dask fallback", cpu_dask_warning)
            os.environ[CSV_FLAT_ALLOW_CPU_DASK_ENV] = "1"
        self.status_label.setText("Parsing GridPACK outputs and RAW metadata in the background...")
        self._set_analysis_controls_enabled(False)
        self.analysis_worker = AnalysisWorker(run_dir, self._utilization_branch_options())
        self.analysis_worker.finished_analysis.connect(self._on_analysis_ready)
        self.analysis_worker.failed_analysis.connect(self._on_analysis_failed)
        self.analysis_worker.finished.connect(self._on_analysis_worker_finished)
        self.analysis_worker.start()

    def generate_report(self) -> None:
        """Backward-compatible slot name for older signal connections."""
        self.generate_graphs()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if hasattr(self, "chart_grid"):
            self._arrange_charts()

    def _on_analysis_ready(self, result: AnalysisBuildResult) -> None:
        self.current_dataset = result.dataset
        self.max_line_rows = result.max_line_rows
        self.group_branch_rows = result.group_branch_rows
        self.control_area_rows = result.control_area_rows
        self.voltage_group_rows = result.voltage_group_rows
        self.line_rows = result.line_rows
        self.selected_control_areas.clear()
        self.selected_voltage_groups.clear()
        if hasattr(self, "chart_grid"):
            self._arrange_charts()
        self._render_charts()
        self._update_generated_status()

    def _on_analysis_failed(self, error_text: str) -> None:
        QMessageBox.critical(self, "Analysis failed", error_text)
        self.status_label.setText("Analysis failed.")

    def _on_analysis_worker_finished(self) -> None:
        worker = self.analysis_worker
        self.analysis_worker = None
        self._set_analysis_controls_enabled(True)
        if worker:
            worker.deleteLater()

    def _set_analysis_controls_enabled(self, enabled: bool) -> None:
        self.run_combo.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)
        self.analyze_button.setEnabled(enabled)

    def _build_chart_area(self, parent_layout: QVBoxLayout) -> None:
        self.control_area_sort = self._sort_combo(
            [
                ("Highest mean max", "value_desc"),
                ("Lowest mean max", "value_asc"),
                ("Area name", "label"),
            ],
            self._render_control_area_chart,
        )
        self.voltage_group_sort = self._sort_combo(
            [
                (self._category_order_sort_label(), "voltage_order"),
                ("Highest mean max", "value_desc"),
                ("Lowest mean max", "value_asc"),
            ],
            self._render_voltage_group_chart,
        )
        self.line_sort = self._sort_combo(
            [
                ("Lowest to highest", "value_asc"),
                ("Highest to lowest", "value_desc"),
                ("Line name", "label"),
            ],
            self._render_line_chart,
        )

        self.control_area_panel, self.control_area_figure, self.control_area_canvas = self._chart_panel(
            f"Mean Max {self._entity_title()} Utilization by Control Area (100 kV and Above)",
            self.control_area_sort,
        )
        self.voltage_group_panel, self.voltage_group_figure, self.voltage_group_canvas = self._chart_panel(
            self._category_panel_title(),
            self.voltage_group_sort,
        )
        self.line_panel, self.line_figure, self.line_canvas = self._chart_panel(
            f"Maximum Observed {self._entity_title()} Utilization",
            self.line_sort,
        )

        self.control_area_hover = _HoverBinding(self.control_area_canvas)
        self.voltage_group_hover = _HoverBinding(self.voltage_group_canvas)
        self.line_hover = _HoverBinding(self.line_canvas)
        self.control_area_canvas.mpl_connect("button_press_event", self._on_control_area_click)
        self.voltage_group_canvas.mpl_connect("button_press_event", self._on_voltage_group_click)
        self.chart_widgets = [self.control_area_panel, self.voltage_group_panel, self.line_panel]

        self.chart_scroll = QScrollArea()
        self.chart_scroll.setWidgetResizable(True)
        self.chart_container = QWidget()
        self.chart_grid = QGridLayout(self.chart_container)
        self.chart_grid.setContentsMargins(0, 0, 0, 0)
        self.chart_grid.setSpacing(12)
        self.chart_scroll.setWidget(self.chart_container)
        parent_layout.addWidget(self.chart_scroll, stretch=1)
        self._arrange_charts()

    def _sort_combo(
        self,
        options: list[tuple[str, str]],
        callback: Callable[[], None],
    ) -> QComboBox:
        combo = QComboBox()
        for label, value in options:
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(callback)
        return combo

    def _chart_panel(self, title: str, sort_combo: QComboBox):
        panel = QGroupBox(title)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Sort"))
        controls.addWidget(sort_combo)
        controls.addStretch()
        layout.addLayout(controls)

        figure = Figure(figsize=(7.0, 3.2))
        canvas = FigureCanvas(figure)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        toolbar = NavigationToolbar(canvas, panel)
        layout.addWidget(toolbar)
        layout.addWidget(canvas, stretch=1)
        return panel, figure, canvas

    def _arrange_charts(self) -> None:
        wide = self.chart_scroll.viewport().width() >= 1120 if hasattr(self, "chart_scroll") else self.width() >= 1120
        dense_control_area = len(self.control_area_rows) >= CONTROL_AREA_FULL_WIDTH_ROWS
        if (
            self._wide_layout == wide
            and self._dense_control_area_layout == dense_control_area
            and self.chart_grid.count() > 0
        ):
            return
        self._wide_layout = wide
        self._dense_control_area_layout = dense_control_area
        while self.chart_grid.count():
            self.chart_grid.takeAt(0)

        if wide and dense_control_area:
            self.chart_grid.addWidget(self.control_area_panel, 0, 0, 1, 2)
            self.chart_grid.addWidget(self.voltage_group_panel, 1, 0, 1, 2)
            self.chart_grid.addWidget(self.line_panel, 2, 0, 1, 2)
            self.chart_grid.setColumnStretch(0, 1)
            self.chart_grid.setColumnStretch(1, 1)
        elif wide:
            self.chart_grid.addWidget(self.control_area_panel, 0, 0)
            self.chart_grid.addWidget(self.voltage_group_panel, 0, 1)
            self.chart_grid.addWidget(self.line_panel, 1, 0, 1, 2)
            self.chart_grid.setColumnStretch(0, 1)
            self.chart_grid.setColumnStretch(1, 1)
        else:
            for row, widget in enumerate(self.chart_widgets):
                self.chart_grid.addWidget(widget, row, 0)
            self.chart_grid.setColumnStretch(0, 1)
            self.chart_grid.setColumnStretch(1, 0)

    def _show_empty_state(self) -> None:
        if not (FigureCanvas and Figure and hasattr(self, "control_area_figure")):
            return
        self._draw_empty_chart(
            self.control_area_figure,
            self.control_area_canvas,
            f"Mean Max {self._entity_title()} Utilization by Control Area",
            f"Generate graphs to view control-area {self._entity_noun()} utilization.",
        )
        self._draw_empty_chart(
            self.voltage_group_figure,
            self.voltage_group_canvas,
            self._category_panel_title(),
            f"Generate graphs to view N-1 {self._category_noun()} utilization.",
        )
        self._draw_empty_chart(
            self.line_figure,
            self.line_canvas,
            f"Maximum Observed {self._entity_title()} Utilization",
            f"Generate graphs to view sorted maximum {self._entity_noun()} utilization.",
        )

    def _render_charts(self) -> None:
        if not (FigureCanvas and Figure and hasattr(self, "control_area_figure")):
            return
        self._render_control_area_chart()
        self._render_voltage_group_chart()
        self._render_line_chart()

    def _on_utilization_scope_changed(self) -> None:
        if not self.current_dataset:
            return
        self._rebuild_utilization_rows()
        self._refresh_filtered_rows()
        if hasattr(self, "chart_grid"):
            self._arrange_charts()
        self._render_charts()
        self._update_generated_status()

    def _rebuild_utilization_rows(self) -> None:
        if not self.current_dataset:
            self.group_branch_rows = []
            self.max_line_rows = []
            return
        branch_options = self._utilization_branch_options()
        self.max_line_rows = max_line_utilization_rows(self.current_dataset.tables, branch_options)
        self.group_branch_rows = list(self.max_line_rows)

    def _utilization_branch_options(self) -> UtilizationBranchOptions:
        if self.transformer_analysis:
            return UtilizationBranchOptions(
                include_nontransformer_branches=False,
                include_two_winding_transformers=True,
                include_three_winding_transformers=True,
                include_transformer_equivalents=True,
            )
        return UtilizationBranchOptions()

    def _update_generated_status(self) -> None:
        runtime_status = _csv_flat_runtime_status(self.current_dataset)
        runtime_suffix = f" {runtime_status}" if runtime_status else ""
        self.status_label.setText(
            "Generated "
            f"{len(self.control_area_rows)} control-area groups, "
            f"{len(self.voltage_group_rows)} {self._category_plural()}, and "
            f"{len(self.line_rows)} {self._entity_plural()} "
            f"({self._utilization_scope_label()})."
            f"{runtime_suffix}"
        )

    def _refresh_filtered_rows(self) -> None:
        self.control_area_rows = summarize_control_area_utilization(self.group_branch_rows)
        selected_area_rows = [
            row for row in self.group_branch_rows
            if self._row_matches_selected_areas(row)
        ]
        self.voltage_group_rows = summarize_voltage_group_utilization(selected_area_rows)
        visible_voltage_groups = {str(row.get("voltage_group")) for row in self.voltage_group_rows}
        self.selected_voltage_groups.intersection_update(visible_voltage_groups)
        self.line_rows = [
            row for row in self.max_line_rows
            if self._row_matches_selected_areas(row) and self._row_matches_selected_voltage_groups(row)
        ]

    def _row_matches_selected_areas(self, row: dict[str, object]) -> bool:
        if not self.selected_control_areas:
            return True
        return bool(self.selected_control_areas.intersection(self._row_control_area_set(row)))

    def _row_matches_selected_voltage_groups(self, row: dict[str, object]) -> bool:
        if not self.selected_voltage_groups:
            return True
        return str(row.get("voltage_group") or "unknown") in self.selected_voltage_groups

    def _row_control_area_set(self, row: dict[str, object]) -> set[str]:
        areas = row.get("control_areas")
        if isinstance(areas, str):
            return {areas} if areas else set()
        if isinstance(areas, (list, tuple, set)):
            return {str(area) for area in areas if str(area)}
        fallback = row.get("control_area")
        return {str(fallback)} if fallback else set()

    def _on_control_area_click(self, event) -> None:
        if event.button != 1:
            return
        for bar, row in self.control_area_click_items:
            contains, _ = bar.contains(event)
            if contains:
                area = str(row.get("control_area") or "")
                if area in self.selected_control_areas:
                    self.selected_control_areas.remove(area)
                elif area:
                    self.selected_control_areas.add(area)
                self._refresh_filtered_rows()
                self._render_charts()
                return

    def _on_voltage_group_click(self, event) -> None:
        if event.button != 1:
            return
        for bar, row in self.voltage_group_click_items:
            contains, _ = bar.contains(event)
            if contains:
                group = str(row.get("voltage_group") or "")
                if group in self.selected_voltage_groups:
                    self.selected_voltage_groups.remove(group)
                elif group:
                    self.selected_voltage_groups.add(group)
                self._refresh_filtered_rows()
                self._render_voltage_group_chart()
                self._render_line_chart()
                return

    def _render_control_area_chart(self) -> None:
        rows = self._sorted_group_rows(
            self.control_area_rows,
            self.control_area_sort.currentData(),
            "control_area",
        )
        self.control_area_panel.setTitle(self._control_area_title())
        figure = self.control_area_figure
        canvas = self.control_area_canvas
        figure.clear()
        axis = figure.add_subplot(111)
        if not rows:
            self.control_area_click_items = []
            self._draw_empty_axis(axis, f"No >=100 kV {self._entity_noun()} utilization data was available.")
            canvas.draw_idle()
            return

        row_count = len(rows)
        canvas_height = self._control_area_canvas_height(row_count)
        tick_font_size = self._control_area_tick_font_size(row_count)
        value_font_size = max(7, tick_font_size - 1)
        labels = [
            self._control_area_axis_label(row.get("control_area", "unknown"), row_count)
            for row in rows
        ]
        values = [numeric_value(row.get("average_utilization_pct")) for row in rows]
        y_positions = list(range(row_count))
        colors = [
            self._selection_color(str(row.get("control_area") or ""), self.selected_control_areas, "#2f6f9f")
            for row in rows
        ]
        bars = axis.barh(y_positions, values, height=0.72, color=colors)
        axis.set_yticks(y_positions)
        axis.set_yticklabels(labels)
        axis.invert_yaxis()
        max_value = max(values) if values else 0
        axis.set_xlim(0, max(35, max_value * 1.22))
        axis.axvline(30, color="#d83b3b", linestyle="--", linewidth=1, label="30% threshold")
        axis.set_xlabel(f"Mean max {self._entity_noun()} utilization (%)")
        axis.set_ylabel("Control area")
        axis.set_title(self._control_area_title())
        axis.margins(y=0.01)
        self._style_axis(axis)
        axis.tick_params(axis="y", labelsize=tick_font_size, pad=3)
        axis.legend(loc="lower right", fontsize=8)
        for bar, row, value in zip(bars, rows, values):
            self._style_selected_bar(bar, str(row.get("control_area") or "") in self.selected_control_areas)
            axis.text(
                value + max(max_value * 0.015, 0.5),
                bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}%",
                va="center",
                fontsize=value_font_size,
                clip_on=False,
            )
        canvas.setMinimumHeight(canvas_height)
        self.control_area_panel.setMinimumHeight(canvas_height + 96)
        self.control_area_panel.updateGeometry()
        self.chart_container.adjustSize()
        self.control_area_click_items = list(zip(bars, rows))
        self.control_area_hover.bind_bars(axis, bars, rows, self._control_area_hover_text, horizontal=True)
        canvas.draw_idle()

    def _render_voltage_group_chart(self) -> None:
        rows = self._sorted_group_rows(
            self.voltage_group_rows,
            self.voltage_group_sort.currentData(),
            "voltage_group",
        )
        self.voltage_group_panel.setTitle(self._voltage_group_title())
        figure = self.voltage_group_figure
        canvas = self.voltage_group_canvas
        figure.clear()
        axis = figure.add_subplot(111)
        if not rows:
            self.voltage_group_click_items = []
            self._draw_empty_axis(axis, f"No N-1 {self._category_noun()} utilization data matched the selected areas.")
            canvas.draw_idle()
            return

        labels = [str(row.get("voltage_group", "unknown")) for row in rows]
        values = [numeric_value(row.get("average_utilization_pct")) for row in rows]
        colors = [
            self._selection_color(str(row.get("voltage_group") or ""), self.selected_voltage_groups, "#82a9c9")
            for row in rows
        ]
        bars = axis.bar(labels, values, color=colors)
        max_value = max(values) if values else 0
        axis.set_ylim(0, max(50, max_value * 1.22))
        axis.set_xlabel(self._voltage_group_x_label())
        axis.set_ylabel(self._voltage_group_y_label())
        axis.set_title(self._voltage_group_title())
        self._style_axis(axis)
        for bar, row, value in zip(bars, rows, values):
            self._style_selected_bar(bar, str(row.get("voltage_group") or "") in self.selected_voltage_groups)
            axis.text(bar.get_x() + bar.get_width() / 2, value + max(max_value * 0.025, 0.5), f"{value:.1f}", ha="center", va="bottom", fontsize=8, fontweight="bold")
        canvas.setMinimumHeight(330)
        self.voltage_group_click_items = list(zip(bars, rows))
        self.voltage_group_hover.bind_bars(axis, bars, rows, self._voltage_group_hover_text, horizontal=False)
        canvas.draw_idle()

    def _render_line_chart(self) -> None:
        rows = self._sorted_line_rows(self.line_rows, self.line_sort.currentData())
        self.line_panel.setTitle(self._line_title())
        figure = self.line_figure
        canvas = self.line_canvas
        figure.clear()
        axis = figure.add_subplot(111)
        if not rows:
            self._draw_empty_axis(axis, f"No {self._entity_noun()} maximum-utilization data matched the selected filters.")
            canvas.draw_idle()
            return

        x_values = list(range(1, len(rows) + 1))
        values = [numeric_value(row.get("max_utilization_pct")) for row in rows]
        max_value = max(values) if values else 0
        axis.axhspan(0, 100, color="#dff2dd", alpha=0.75, label="Capability")
        axis.fill_between(x_values, values, color="#92d0c8", alpha=0.55, label="Utilization")
        axis.plot(x_values, values, color="#1f6fb2", linewidth=1.5)
        axis.axhline(100, color="#70a36a", linewidth=1)
        if len(rows) == 1:
            axis.set_xlim(0.5, 1.5)
        else:
            axis.set_xlim(1, len(rows))
        axis.set_ylim(0, max(110, max_value * 1.08))
        axis.set_xlabel(self._line_x_label())
        axis.set_ylabel("Max utilization across all contingencies (%)")
        axis.set_title(self._line_title())
        self._style_axis(axis)
        axis.legend(loc="upper left", fontsize=8)
        canvas.setMinimumHeight(390)
        self.line_hover.bind_curve(axis, x_values, values, rows, self._line_hover_text)
        canvas.draw_idle()

    def _sorted_group_rows(
        self,
        rows: list[dict[str, object]],
        mode: object,
        label_column: str,
    ) -> list[dict[str, object]]:
        sorted_rows = list(rows)
        if mode == "value_asc":
            sorted_rows.sort(key=lambda row: numeric_value(row.get("average_utilization_pct")))
        elif mode == "label":
            sorted_rows.sort(key=lambda row: str(row.get(label_column, "")))
        elif mode == "value_desc":
            sorted_rows.sort(key=lambda row: numeric_value(row.get("average_utilization_pct")), reverse=True)
        return sorted_rows

    def _sorted_line_rows(self, rows: list[dict[str, object]], mode: object) -> list[dict[str, object]]:
        sorted_rows = list(rows)
        if mode == "value_desc":
            sorted_rows.sort(key=lambda row: numeric_value(row.get("max_utilization_pct")), reverse=True)
        elif mode == "label":
            sorted_rows.sort(key=lambda row: str(row.get("line_label", "")))
        else:
            sorted_rows.sort(key=lambda row: numeric_value(row.get("max_utilization_pct")))
        return sorted_rows

    def _draw_empty_chart(self, figure, canvas, title: str, message: str) -> None:
        figure.clear()
        axis = figure.add_subplot(111)
        axis.set_title(title)
        self._draw_empty_axis(axis, message)
        canvas.draw_idle()

    def _draw_empty_axis(self, axis, message: str) -> None:
        axis.text(0.5, 0.5, message, ha="center", va="center", transform=axis.transAxes, color="#5b667a")
        axis.set_axis_off()

    def _style_axis(self, axis) -> None:
        axis.grid(True, axis="y", color="#d8dde7", linewidth=0.8, alpha=0.8)
        axis.grid(True, axis="x", color="#e9edf4", linewidth=0.6, alpha=0.7)
        axis.set_axisbelow(True)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color("#9aa5b5")
        axis.spines["bottom"].set_color("#9aa5b5")
        axis.tick_params(axis="both", labelsize=8)

    def _control_area_canvas_height(self, row_count: int) -> int:
        return max(CONTROL_AREA_MIN_HEIGHT, CONTROL_AREA_TOP_BOTTOM_PADDING + row_count * CONTROL_AREA_ROW_PIXELS)

    def _control_area_tick_font_size(self, row_count: int) -> int:
        if row_count >= 120:
            return 7
        if row_count >= 80:
            return 8
        return 9

    def _control_area_axis_label(self, label: object, row_count: int) -> str:
        clean = " ".join(str(label or "unknown").split())
        limit = CONTROL_AREA_LABEL_LIMIT if row_count < 80 else CONTROL_AREA_LABEL_LIMIT - 6
        return textwrap.shorten(clean, width=limit, placeholder="...")

    def _selection_color(self, value: str, selected: set[str], default: str) -> str:
        if not selected:
            return default
        return "#d97706" if value in selected else "#b8c5d2"

    def _style_selected_bar(self, bar, selected: bool) -> None:
        if selected:
            bar.set_edgecolor("#7c2d12")
            bar.set_linewidth(1.4)
        else:
            bar.set_edgecolor("none")
            bar.set_linewidth(0)

    def _control_area_title(self) -> str:
        if not self.selected_control_areas:
            return f"Mean Max {self._entity_title()} Utilization by Control Area"
        return (
            f"Mean Max {self._entity_title()} Utilization by Control Area "
            f"({self._selection_phrase(self.selected_control_areas, 'areas')} selected)"
        )

    def _voltage_group_title(self) -> str:
        return f"Mean Max {self._entity_title()} Loading by {self._category_title()} ({self._area_scope_label()})"

    def _voltage_group_x_label(self) -> str:
        if self.selected_control_areas:
            return f"{self._category_plural().capitalize()} for selected control areas"
        return self._category_plural().capitalize()

    def _voltage_group_y_label(self) -> str:
        return "Mean max loading in selected areas (%)" if self.selected_control_areas else "Mean max loading (%)"

    def _line_title(self) -> str:
        return f"Maximum Observed {self._entity_title()} Utilization ({self._voltage_scope_label()}, {self._area_scope_label()})"

    def _line_x_label(self) -> str:
        if self.selected_voltage_groups:
            return f"{self._entity_plural().capitalize()} in selected {self._category_plural()}, sorted lowest to highest"
        return f"{self._entity_plural().capitalize()} in visible {self._category_plural()}, sorted lowest to highest"

    def _utilization_scope_label(self) -> str:
        if self.transformer_analysis:
            return "transformers only"
        return "non-transformer branches only"

    def _area_scope_label(self) -> str:
        if not self.selected_control_areas:
            return "all control areas"
        return self._selection_phrase(self.selected_control_areas, "areas")

    def _voltage_scope_label(self) -> str:
        if not self.selected_voltage_groups:
            return f"all visible {self._category_plural()}"
        return self._selection_phrase(self.selected_voltage_groups, self._category_plural())

    def _analysis_noun(self) -> str:
        return "transformer analysis" if self.transformer_analysis else "branch analysis"

    def _entity_noun(self) -> str:
        return "transformer" if self.transformer_analysis else "branch"

    def _entity_plural(self) -> str:
        return "transformers" if self.transformer_analysis else "branches"

    def _entity_title(self) -> str:
        return "Transformer" if self.transformer_analysis else "Branch"

    def _category_noun(self) -> str:
        return "step-direction" if self.transformer_analysis else "voltage-group"

    def _category_plural(self) -> str:
        return "step directions" if self.transformer_analysis else "voltage groups"

    def _category_title(self) -> str:
        return "Step Direction" if self.transformer_analysis else "Voltage Group"

    def _category_panel_title(self) -> str:
        return f"Mean Max Utilization by {self._category_title()} Under N-1 Contingencies"

    def _category_order_sort_label(self) -> str:
        return "Step direction" if self.transformer_analysis else "Voltage order"

    def _selection_phrase(self, values: set[str], plural_noun: str) -> str:
        ordered = sorted(values)
        if len(ordered) <= 2:
            return " + ".join(ordered)
        return f"{len(ordered)} {plural_noun}"

    def _control_area_hover_text(self, row: dict[str, object]) -> str:
        return (
            f"{row.get('control_area', 'unknown')}\n"
            f"Group mean max: {numeric_value(row.get('average_utilization_pct')):.1f}%\n"
            f"{self._entity_plural().capitalize()}: {row.get('line_count', 0)}\n"
            f"{self._entity_title()} max range: {numeric_value(row.get('min_utilization_pct')):.1f}% - "
            f"{numeric_value(row.get('max_utilization_pct')):.1f}%"
        )

    def _voltage_group_hover_text(self, row: dict[str, object]) -> str:
        return (
            f"{row.get('voltage_group', 'unknown')}\n"
            f"Group mean max: {numeric_value(row.get('average_utilization_pct')):.1f}%\n"
            f"{self._entity_plural().capitalize()}: {row.get('line_count', 0)}\n"
            f"{self._entity_title()} max range: {numeric_value(row.get('min_utilization_pct')):.1f}% - "
            f"{numeric_value(row.get('max_utilization_pct')):.1f}%"
        )

    def _line_hover_text(self, row: dict[str, object]) -> str:
        voltage = f"{row.get('from_base_kv', '')} / {row.get('to_base_kv', '')} kV"
        contingency = row.get("max_contingency") or "n/a"
        source = row.get("utilization_source") or "pflow_mm"
        return (
            f"{row.get('line_label', '')}\n"
            f"Worst observed ({source}): {numeric_value(row.get('max_utilization_pct')):.1f}%\n"
            f"Contingency: {contingency}\n"
            f"{self._category_title()}: {row.get('voltage_group', 'unknown')}\n"
            f"Control area: {row.get('control_area', 'unknown')}\n"
            f"Voltage: {voltage}"
        )


class _HoverBinding:
    def __init__(self, canvas) -> None:
        self.canvas = canvas
        self.axis = None
        self.annotation = None
        self.mode = ""
        self.bar_items = []
        self.curve_x: list[int] = []
        self.curve_y: list[float] = []
        self.curve_rows: list[dict[str, object]] = []
        self.text_for_row: Callable[[dict[str, object]], str] | None = None
        self.horizontal = False
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

    def bind_bars(self, axis, bars, rows, text_for_row, *, horizontal: bool) -> None:
        self.axis = axis
        self.mode = "bars"
        self.bar_items = list(zip(bars, rows))
        self.curve_x = []
        self.curve_y = []
        self.curve_rows = []
        self.text_for_row = text_for_row
        self.horizontal = horizontal
        self.annotation = self._annotation(axis)

    def bind_curve(self, axis, x_values, y_values, rows, text_for_row) -> None:
        self.axis = axis
        self.mode = "curve"
        self.bar_items = []
        self.curve_x = list(x_values)
        self.curve_y = list(y_values)
        self.curve_rows = list(rows)
        self.text_for_row = text_for_row
        self.annotation = self._annotation(axis)

    def _annotation(self, axis):
        annotation = axis.annotate(
            "",
            xy=(0, 0),
            xytext=(12, 12),
            textcoords="offset points",
            bbox={"boxstyle": "round,pad=0.35", "fc": "#ffffff", "ec": "#7a8798", "alpha": 0.96},
            arrowprops={"arrowstyle": "->", "color": "#7a8798", "linewidth": 0.8},
        )
        annotation.set_visible(False)
        annotation.set_zorder(20)
        return annotation

    def _on_motion(self, event) -> None:
        if self.axis is None or self.annotation is None or self.text_for_row is None:
            return
        if event.inaxes != self.axis:
            self._hide()
            return
        if self.mode == "bars":
            for bar, row in self.bar_items:
                contains, _ = bar.contains(event)
                if contains:
                    if self.horizontal:
                        xy = (bar.get_width(), bar.get_y() + bar.get_height() / 2)
                    else:
                        xy = (bar.get_x() + bar.get_width() / 2, bar.get_height())
                    self._show(xy, self.text_for_row(row), event)
                    return
            self._hide()
            return
        if self.mode == "curve" and event.xdata is not None and self.curve_x:
            nearest_index = min(range(len(self.curve_x)), key=lambda index: abs(self.curve_x[index] - event.xdata))
            xy = (self.curve_x[nearest_index], self.curve_y[nearest_index])
            self._show(xy, self.text_for_row(self.curve_rows[nearest_index]), event)

    def _show(self, xy, text: str, event) -> None:
        self.annotation.xy = xy
        self._place_annotation(event)
        self.annotation.set_text(text)
        self.annotation.set_visible(True)
        self.canvas.draw_idle()

    def _place_annotation(self, event) -> None:
        width = max(self.canvas.width(), 1)
        height = max(self.canvas.height(), 1)
        x_offset = -14 if event.x > width * 0.70 else 14
        y_offset = -14 if event.y > height * 0.70 else 14
        self.annotation.set_position((x_offset, y_offset))
        self.annotation.set_ha("right" if x_offset < 0 else "left")
        self.annotation.set_va("top" if y_offset < 0 else "bottom")

    def _hide(self) -> None:
        if self.annotation and self.annotation.get_visible():
            self.annotation.set_visible(False)
            self.canvas.draw_idle()
