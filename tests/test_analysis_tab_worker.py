from __future__ import annotations

from types import SimpleNamespace

from gridpack_workbench.analysis.csv_flat import CSV_FLAT_RESULTS_TABLE
from gridpack_workbench.analysis.utilization import UtilizationBranchOptions
from gridpack_workbench.gui import analysis_tab


def test_line_chart_display_points_preserves_small_sets() -> None:
    rows = [{"line": index} for index in range(4)]

    points = analysis_tab._line_chart_display_points(rows)

    assert points == [(1, rows[0]), (2, rows[1]), (3, rows[2]), (4, rows[3])]


def test_line_chart_display_points_samples_large_sets() -> None:
    rows = [{"line": index} for index in range(analysis_tab.LINE_CHART_MAX_POINTS + 1)]

    points = analysis_tab._line_chart_display_points(rows)

    assert len(points) == analysis_tab.LINE_CHART_MAX_POINTS
    assert points[0] == (1, rows[0])
    assert points[-1] == (len(rows), rows[-1])
    assert [point[0] for point in points] == sorted({point[0] for point in points})


def test_csv_flat_runtime_status_reports_gpu_backend() -> None:
    dataset = SimpleNamespace(
        tables={
            CSV_FLAT_RESULTS_TABLE: SimpleNamespace(
                notes=["RAPIDS dask-cudf GPU backend was used for csv_flat aggregation."]
            )
        }
    )

    assert analysis_tab._csv_flat_runtime_status(dataset) == "RAPIDS dask-cudf GPU backend used."


def test_csv_flat_runtime_status_reports_cpu_backend() -> None:
    dataset = SimpleNamespace(
        tables={
            CSV_FLAT_RESULTS_TABLE: SimpleNamespace(
                notes=[
                    "CPU Dask backend was used for csv_flat aggregation. Install RAPIDS dask-cudf/dask-cuda "
                    "and set GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND=dask_cudf to require GPU execution."
                ]
            )
        }
    )

    assert analysis_tab._csv_flat_runtime_status(dataset) == "CPU Dask backend used; RAPIDS was not active."


def test_csv_flat_runtime_status_reports_streaming_fallback() -> None:
    dataset = SimpleNamespace(
        tables={
            CSV_FLAT_RESULTS_TABLE: SimpleNamespace(
                notes=["branch-level summaries are streamed from the full file."]
            )
        }
    )

    assert analysis_tab._csv_flat_runtime_status(dataset) == "Python streaming fallback used for csv-flat aggregation."


def test_analysis_worker_builds_interactive_dataset_without_parquet(tmp_path, monkeypatch) -> None:
    calls: list[tuple[object, bool]] = []
    fake_dataset = SimpleNamespace(tables={"pflow_mm": object()})

    def fake_build_run_analysis(run_dir, *, convert_csv_flat_parquet: bool = True):
        calls.append((run_dir, convert_csv_flat_parquet))
        return fake_dataset

    monkeypatch.setattr(analysis_tab, "build_run_analysis", fake_build_run_analysis)
    monkeypatch.setattr(
        analysis_tab,
        "max_line_utilization_rows",
        lambda tables, branch_options: [
            {
                "control_areas": ["North"],
                "utilization_pct": 42.0,
                "max_utilization_pct": 42.0,
                "voltage_group": "230-344 kV",
            }
        ],
    )
    monkeypatch.setattr(
        analysis_tab,
        "summarize_control_area_utilization",
        lambda rows: [{"control_area": "North", "average_utilization_pct": 42.0}],
    )
    monkeypatch.setattr(
        analysis_tab,
        "summarize_voltage_group_utilization",
        lambda rows: [{"voltage_group": "230-344 kV", "average_utilization_pct": 42.0}],
    )
    results = []
    failures = []
    worker = analysis_tab.AnalysisWorker(tmp_path, UtilizationBranchOptions())
    worker.finished_analysis.connect(results.append)
    worker.failed_analysis.connect(failures.append)

    worker.run()

    assert failures == []
    assert calls == [(tmp_path, False)]
    assert len(results) == 1
    assert results[0].dataset is fake_dataset
    assert results[0].line_rows[0]["max_utilization_pct"] == 42.0
