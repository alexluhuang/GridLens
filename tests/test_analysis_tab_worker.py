from __future__ import annotations

import json
from types import SimpleNamespace

from gridlens.analysis import interactive
from gridlens.analysis.dataset import ANALYSIS_DATASET_VERSION, RunAnalysisDataset
from gridlens.analysis.csv_flat import CSV_FLAT_RESULTS_TABLE
from gridlens.analysis.parser_models import PARSER_VERSION, ParsedTable
from gridlens.analysis.utilization import UtilizationBranchOptions
from gridlens.gui import analysis_tab


def test_csv_flat_runtime_status_reports_gpu_backend() -> None:
    dataset = SimpleNamespace(
        tables={
            CSV_FLAT_RESULTS_TABLE: SimpleNamespace(
                notes=["RAPIDS dask-cudf GPU backend was used for csv_flat aggregation."]
            )
        }
    )

    assert analysis_tab._csv_flat_runtime_status(dataset) == "RAPIDS GPU backend used."


def test_csv_flat_runtime_status_reports_cudf_gpu_backend() -> None:
    dataset = SimpleNamespace(
        tables={
            CSV_FLAT_RESULTS_TABLE: SimpleNamespace(
                notes=["RAPIDS cuDF GPU backend was used for csv_flat aggregation."]
            )
        }
    )

    assert analysis_tab._csv_flat_runtime_status(dataset) == "RAPIDS GPU backend used."


def test_csv_flat_runtime_status_reports_cpu_backend() -> None:
    dataset = SimpleNamespace(
        tables={
            CSV_FLAT_RESULTS_TABLE: SimpleNamespace(
                notes=[
                    "CPU Dask backend was used for csv_flat aggregation. Install RAPIDS dask-cudf/dask-cuda "
                    "and set GRIDLENS_CSV_FLAT_BACKEND=dask_cudf to require GPU execution."
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


def test_build_analysis_result_uses_interactive_dataset_flags(tmp_path, monkeypatch) -> None:
    calls: list[tuple[object, bool, bool, bool]] = []
    fake_dataset = SimpleNamespace(tables={"pflow_mm": object()})

    def fake_build_run_analysis(
        run_dir,
        *,
        convert_csv_flat_parquet: bool = True,
        write_artifacts: bool = True,
        compute_metric_summary: bool = True,
        progress=None,
    ):
        calls.append((run_dir, convert_csv_flat_parquet, write_artifacts, compute_metric_summary))
        return fake_dataset

    monkeypatch.setattr(interactive, "build_run_analysis", fake_build_run_analysis)
    monkeypatch.setattr(
        interactive,
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
        interactive,
        "summarize_control_area_utilization",
        lambda rows: [{"control_area": "North", "average_utilization_pct": 42.0}],
    )
    monkeypatch.setattr(
        interactive,
        "summarize_voltage_group_utilization",
        lambda rows: [{"voltage_group": "230-344 kV", "average_utilization_pct": 42.0}],
    )

    result = interactive.build_interactive_analysis_result(tmp_path, UtilizationBranchOptions())

    assert calls == [(tmp_path, False, False, False)]
    assert result.dataset is fake_dataset
    assert result.line_rows[0]["max_utilization_pct"] == 42.0


def test_build_analysis_result_uses_fresh_cached_interactive_tables(tmp_path, monkeypatch) -> None:
    run_dir = _cached_interactive_run(tmp_path)

    def fail_build_run_analysis(*args, **kwargs):
        raise AssertionError("fresh interactive cache should avoid parsing run outputs")

    monkeypatch.setattr(interactive, "build_run_analysis", fail_build_run_analysis)

    result = interactive.build_interactive_analysis_result(run_dir, UtilizationBranchOptions())

    assert len(result.line_rows) == 1
    assert result.line_rows[0]["max_utilization_pct"] == 42.0
    assert result.control_area_rows[0]["control_area"] == "North"
    assert result.dataset.tables[CSV_FLAT_RESULTS_TABLE].notes == [
        "RAPIDS cuDF GPU backend was used for csv_flat aggregation."
    ]


def test_build_analysis_result_ignores_stale_cached_interactive_tables(tmp_path, monkeypatch) -> None:
    run_dir = _cached_interactive_run(tmp_path)
    source = run_dir / "work" / "flat.csv"
    source.write_text(source.read_text(encoding="utf-8") + "\nnewer", encoding="utf-8")
    fake_dataset = SimpleNamespace(tables={"pflow_mm": object()})
    calls = []

    def fake_build_run_analysis(*args, **kwargs):
        calls.append((args, kwargs))
        return fake_dataset

    monkeypatch.setattr(interactive, "build_run_analysis", fake_build_run_analysis)
    monkeypatch.setattr(
        interactive,
        "max_line_utilization_rows",
        lambda tables, branch_options: [{"max_utilization_pct": 7.0, "utilization_pct": 7.0, "control_areas": ["North"]}],
    )
    monkeypatch.setattr(interactive, "summarize_control_area_utilization", lambda rows: [])
    monkeypatch.setattr(interactive, "summarize_voltage_group_utilization", lambda rows: [])

    result = interactive.build_interactive_analysis_result(run_dir, UtilizationBranchOptions())

    assert calls
    assert result.dataset is fake_dataset
    assert result.line_rows[0]["max_utilization_pct"] == 7.0


def test_build_analysis_result_writes_interactive_cache_after_cold_parse(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "2026-07-05_14-48-34"
    work = run_dir / "work"
    work.mkdir(parents=True)
    (work / "flat.csv").write_text("source\n", encoding="utf-8")
    (work / "raw.raw").write_text("source\n", encoding="utf-8")
    fake_dataset = _interactive_dataset(run_dir)
    calls = []

    def fake_build_run_analysis(*args, **kwargs):
        calls.append((args, kwargs))
        return fake_dataset

    monkeypatch.setattr(interactive, "build_run_analysis", fake_build_run_analysis)

    first = interactive.build_interactive_analysis_result(run_dir, UtilizationBranchOptions())
    assert calls
    assert first.line_rows[0]["max_utilization_pct"] == 42.0
    manifest_path = run_dir / "reports" / "interactive_analysis_manifest.json"
    assert manifest_path.exists()
    table_dir = run_dir / "reports" / "interactive_tables"
    assert sorted(path.name for path in table_dir.iterdir()) == [
        "area_metadata.csv",
        "branch_metadata.csv",
        "pflow_mm.csv",
    ]
    assert not list(table_dir.glob("*.json"))
    assert not (run_dir / "reports" / "tables").exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["tables"][CSV_FLAT_RESULTS_TABLE]["csv_path"] == ""

    def fail_build_run_analysis(*args, **kwargs):
        raise AssertionError("warm interactive cache should avoid parsing run outputs")

    monkeypatch.setattr(interactive, "build_run_analysis", fail_build_run_analysis)
    second = interactive.build_interactive_analysis_result(run_dir, UtilizationBranchOptions())

    assert second.line_rows[0]["max_utilization_pct"] == 42.0


def test_build_analysis_result_writes_local_interactive_cache_without_csv_flat_status(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "2026-07-05_14-48-34"
    work = run_dir / "work"
    work.mkdir(parents=True)
    (work / "flat.csv").write_text("source\n", encoding="utf-8")
    (work / "raw.raw").write_text("source\n", encoding="utf-8")
    fake_dataset = _interactive_dataset(run_dir)
    fake_dataset.tables.pop(CSV_FLAT_RESULTS_TABLE)
    calls = []

    def fake_build_run_analysis(*args, **kwargs):
        calls.append((args, kwargs))
        return fake_dataset

    monkeypatch.setattr(interactive, "build_run_analysis", fake_build_run_analysis)

    first = interactive.build_interactive_analysis_result(run_dir, UtilizationBranchOptions())
    assert calls
    assert first.line_rows[0]["max_utilization_pct"] == 42.0
    table_dir = run_dir / "reports" / "interactive_tables"
    assert sorted(path.name for path in table_dir.iterdir()) == [
        "area_metadata.csv",
        "branch_metadata.csv",
        "pflow_mm.csv",
    ]
    manifest = json.loads((run_dir / "reports" / "interactive_analysis_manifest.json").read_text(encoding="utf-8"))
    assert CSV_FLAT_RESULTS_TABLE not in manifest["tables"]

    def fail_build_run_analysis(*args, **kwargs):
        raise AssertionError("warm local interactive cache should avoid parsing run outputs")

    monkeypatch.setattr(interactive, "build_run_analysis", fail_build_run_analysis)
    second = interactive.build_interactive_analysis_result(run_dir, UtilizationBranchOptions())

    assert second.line_rows[0]["max_utilization_pct"] == 42.0


def test_analysis_worker_builds_result_in_process(tmp_path, monkeypatch) -> None:
    calls: list[tuple[object, UtilizationBranchOptions]] = []
    fake_dataset = SimpleNamespace(tables={"pflow_mm": object()})

    def fake_build_analysis_result_in_process(run_dir, branch_options, progress_callback=None):
        calls.append((run_dir, branch_options))
        if progress_callback is not None:
            progress_callback(analysis_tab.AnalysisProgress(phase="parse", detail="Parsing..."))
        row = {
            "control_areas": ["North"],
            "utilization_pct": 42.0,
            "max_utilization_pct": 42.0,
            "voltage_group": "230-344 kV",
        }
        return analysis_tab.AnalysisBuildResult(
            dataset=fake_dataset,
            max_line_rows=[row],
            group_branch_rows=[],
            control_area_rows=[{"control_area": "North", "average_utilization_pct": 42.0}],
            voltage_group_rows=[{"voltage_group": "230-344 kV", "average_utilization_pct": 42.0}],
            line_rows=[row],
        )

    monkeypatch.setattr(analysis_tab, "_build_analysis_result_in_process", fake_build_analysis_result_in_process)
    results = []
    failures = []
    updates = []
    options = UtilizationBranchOptions()
    worker = analysis_tab.AnalysisWorker(tmp_path, options)
    worker.finished_analysis.connect(results.append)
    worker.failed_analysis.connect(failures.append)
    worker.progress_analysis.connect(updates.append)

    worker.run()

    assert failures == []
    assert calls == [(tmp_path, options)]
    assert len(results) == 1
    assert results[0].dataset is fake_dataset
    assert results[0].line_rows[0]["max_utilization_pct"] == 42.0
    assert [update.detail for update in updates] == ["Parsing..."]


def _interactive_dataset(run_dir) -> RunAnalysisDataset:
    tables = {
        "pflow_mm": ParsedTable(
            "pflow_mm",
            "flat.csv",
            [
                "from_bus",
                "to_bus",
                "line_id",
                "section",
                "max_utilization_pct",
                "max_utilization_contingency",
            ],
            [
                {
                    "from_bus": 101,
                    "to_bus": 102,
                    "line_id": "1",
                    "section": "",
                    "max_utilization_pct": 42.0,
                    "max_utilization_contingency": 3,
                }
            ],
        ),
        "branch_metadata": ParsedTable(
            "branch_metadata",
            "flat.csv",
            [
                "from_bus",
                "to_bus",
                "line_id",
                "section",
                "raw_branch_type",
                "from_bus_name",
                "to_bus_name",
                "from_base_kv",
                "to_base_kv",
                "from_area_name",
                "to_area_name",
                "control_area",
                "voltage_class",
                "ratec",
            ],
            [
                {
                    "from_bus": 101,
                    "to_bus": 102,
                    "line_id": "1",
                    "section": "",
                    "raw_branch_type": "nontransformer_branch",
                    "from_bus_name": "FROM",
                    "to_bus_name": "TO",
                    "from_base_kv": 230.0,
                    "to_base_kv": 230.0,
                    "from_area_name": "North",
                    "to_area_name": "North",
                    "control_area": "North",
                    "voltage_class": "230-344 kV",
                    "ratec": 100,
                }
            ],
        ),
        "area_metadata": ParsedTable(
            "area_metadata",
            "raw.raw",
            ["area", "area_name"],
            [{"area": 1, "area_name": "North"}],
        ),
        CSV_FLAT_RESULTS_TABLE: ParsedTable(
            CSV_FLAT_RESULTS_TABLE,
            "flat.csv",
            ["from_bus", "to_bus", "line_id"],
            [{"from_bus": 101, "to_bus": 102, "line_id": "1"}],
            ["RAPIDS cuDF GPU backend was used for csv_flat aggregation."],
        ),
    }
    return RunAnalysisDataset(
        run_dir=run_dir,
        report_dir=run_dir / "reports",
        table_dir=run_dir / "reports" / "tables",
        manifest_path=run_dir / "reports" / "analysis_manifest.json",
        tables=tables,
        metrics={},
        table_files={},
        generated_at="2026-07-05T22:35:20+00:00",
    )


def _cached_interactive_run(root) -> object:
    run_dir = root / "runs" / "2026-07-05_14-48-34"
    work = run_dir / "work"
    table_dir = run_dir / "reports" / "tables"
    work.mkdir(parents=True)
    table_dir.mkdir(parents=True)
    (work / "flat.csv").write_text("source\n", encoding="utf-8")
    (work / "raw.raw").write_text("source\n", encoding="utf-8")

    table_specs = {
        "pflow_mm": {
            "source_file": "flat.csv",
            "notes": [],
            "rows": [
                {
                    "from_bus": "101",
                    "to_bus": "102",
                    "line_id": "1",
                    "section": "",
                    "max_utilization_pct": "42.0",
                    "max_utilization_contingency": "3",
                }
            ],
        },
        "branch_metadata": {
            "source_file": "flat.csv",
            "notes": [],
            "rows": [
                {
                    "from_bus": "101",
                    "to_bus": "102",
                    "line_id": "1",
                    "section": "",
                    "raw_branch_type": "nontransformer_branch",
                    "from_bus_name": "FROM",
                    "to_bus_name": "TO",
                    "from_base_kv": "230.0",
                    "to_base_kv": "230.0",
                    "from_area_name": "North",
                    "to_area_name": "North",
                    "control_area": "North",
                    "voltage_class": "230-344 kV",
                    "ratec": "100",
                }
            ],
        },
        "area_metadata": {
            "source_file": "raw.raw",
            "notes": [],
            "rows": [{"area": "1", "area_name": "North"}],
        },
        CSV_FLAT_RESULTS_TABLE: {
            "source_file": "flat.csv",
            "notes": ["RAPIDS cuDF GPU backend was used for csv_flat aggregation."],
            "rows": [{"from_bus": "101", "to_bus": "102", "line_id": "1"}],
        },
    }
    manifest_tables = {}
    for table_name, spec in table_specs.items():
        csv_path = table_dir / f"{table_name}.csv"
        columns = list(spec["rows"][0].keys())
        _write_cached_table(csv_path, columns, spec["rows"])
        manifest_tables[table_name] = {
            "name": table_name,
            "source_file": spec["source_file"],
            "columns": columns,
            "row_count": len(spec["rows"]),
            "notes": spec["notes"],
            "parser_version": PARSER_VERSION,
            "csv_path": str(csv_path),
            "json_path": "",
            "parquet_path": "",
        }
    (run_dir / "reports" / "analysis_manifest.json").write_text(
        json.dumps(
            {
                "dataset_version": ANALYSIS_DATASET_VERSION,
                "parser_version": PARSER_VERSION,
                "generated_at": "2026-07-05T22:35:20+00:00",
                "run_dir": str(run_dir),
                "report_dir": str(run_dir / "reports"),
                "table_dir": str(table_dir),
                "metrics": {},
                "tables": manifest_tables,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _write_cached_table(path, columns, rows) -> None:
    path.write_text(
        ",".join(columns)
        + "\n"
        + "\n".join(",".join(str(row.get(column, "")) for column in columns) for row in rows)
        + "\n",
        encoding="utf-8",
    )
