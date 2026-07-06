from __future__ import annotations

import builtins
import json
import sys
import types

import pytest

from gridpack_workbench.analysis import csv_flat
from gridpack_workbench.analysis import parsers
from gridpack_workbench.analysis.dataset import build_run_analysis
from gridpack_workbench.analysis.enrichment import enrich_with_bus_metadata
from gridpack_workbench.analysis.metrics import compute_metrics
from gridpack_workbench.analysis.parsers import parse_all_output_tables, summarize_success_file
from gridpack_workbench.gui.analysis_view_models import max_line_utilization_rows


def test_csv_flat_outputs_parse_into_existing_analysis_tables(tmp_path) -> None:
    run_dir = _csv_flat_run(tmp_path)

    tables = parse_all_output_tables(run_dir)
    enrich_with_bus_metadata(tables)
    metrics = compute_metrics(tables)

    summary = summarize_success_file(run_dir)
    assert summary.file_name == "training_tiny_convergence.csv"
    assert summary.success_count == 1
    assert summary.failure_count == 3

    assert tables["csv_flat_results"].source_file == "training_tiny_flat1.csv"
    assert tables["csv_flat_results"].row_count == 5
    assert tables["success"].rows[2]["violation"] == "islanded"
    assert tables["success"].rows[2]["isolated_warning"] is True

    pflow_mm = tables["pflow_mm"]
    first_branch = next(row for row in pflow_mm.rows if row["from_bus"] == 101)
    assert first_branch["base_utilization_pct"] == 10.0
    assert first_branch["mean_utilization_pct"] == 65.0
    assert first_branch["max_utilization_pct"] == 125.0
    assert first_branch["max_utilization_contingency"] == 1
    assert first_branch["max_contingency_label"] == "BR_101_102_1"

    thermal = metrics["thermal"]
    assert thermal["facility_count"] == 2
    assert thermal["facilities_over_100_pct"] == 1
    assert thermal["top_bottlenecks"][0]["max_utilization_pct"] == 125.0

    line_rows = max_line_utilization_rows(tables)
    assert [row["max_utilization_pct"] for row in line_rows] == [40.0, 125.0]
    assert line_rows[1]["control_areas"] == ["North"]
    assert line_rows[1]["voltage_group"] == "230-344 kV"


def test_parse_all_output_tables_parses_csv_flat_success_once(tmp_path, monkeypatch) -> None:
    run_dir = _csv_flat_run(tmp_path)

    def fail_if_called(run_dir):
        raise AssertionError("parse_all_output_tables should get csv_flat success from parse_csv_flat_outputs")

    monkeypatch.setattr(parsers, "parse_csv_flat_success", fail_if_called)

    tables = parse_all_output_tables(run_dir)

    assert tables["success"].source_file == "training_tiny_convergence.csv"
    assert tables["success"].row_count == 4


def test_build_run_analysis_records_csv_flat_parquet_note_without_optional_stack(tmp_path) -> None:
    run_dir = _csv_flat_run(tmp_path)

    dataset = build_run_analysis(run_dir)
    manifest = json.loads(dataset.manifest_path.read_text(encoding="utf-8"))

    assert manifest["tables"]["csv_flat_results"]["row_count"] == 5
    assert "parquet_path" in manifest["tables"]["csv_flat_results"]
    assert (run_dir / "reports" / "tables" / "pflow_mm.csv").exists()


def test_build_run_analysis_can_skip_csv_flat_parquet_for_interactive_graphs(tmp_path) -> None:
    run_dir = _csv_flat_run(tmp_path)

    dataset = build_run_analysis(run_dir, convert_csv_flat_parquet=False)
    manifest = json.loads(dataset.manifest_path.read_text(encoding="utf-8"))

    assert manifest["tables"]["csv_flat_results"]["row_count"] == 5
    assert manifest["tables"]["csv_flat_results"]["parquet_path"] == ""
    assert not (run_dir / "reports" / "parquet").exists()
    assert (run_dir / "reports" / "tables" / "pflow_mm.csv").exists()


def test_build_run_analysis_can_skip_interactive_artifacts_and_metrics(tmp_path) -> None:
    run_dir = _csv_flat_run(tmp_path)

    dataset = build_run_analysis(
        run_dir,
        convert_csv_flat_parquet=False,
        write_artifacts=False,
        compute_metric_summary=False,
    )

    assert dataset.tables["pflow_mm"].row_count == 2
    assert dataset.metrics == {}
    assert dataset.table_files == {}
    assert not dataset.manifest_path.exists()
    assert not (run_dir / "reports" / "tables").exists()


def test_csv_flat_python_backend_can_be_forced(tmp_path, monkeypatch) -> None:
    run_dir = _csv_flat_run(tmp_path)
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND", "python")

    tables = parse_all_output_tables(run_dir)

    first_branch = next(row for row in tables["pflow_mm"].rows if row["from_bus"] == 101)
    assert first_branch["max_utilization_pct"] == 125.0
    assert first_branch["max_utilization_contingency"] == 1


def test_csv_flat_accelerated_backend_uses_absolute_max_loading(tmp_path, monkeypatch) -> None:
    run_dir = _csv_flat_run(tmp_path)
    flat_path = run_dir / "work" / "training_tiny_flat1.csv"
    flat_path.write_text(
        "\n".join(
            [
                "event_idx,contingency,from_bus,to_bus,circuit_id,rate_mva,loading_percent,viol",
                "0,base_case,101,102,1,100,10,0",
                "1,POSITIVE,101,102,1,100,80,0",
                "2,NEGATIVE,101,102,1,100,-130,1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND", "dask")

    tables = parse_all_output_tables(run_dir)

    branch = next(row for row in tables["pflow_mm"].rows if row["from_bus"] == 101)
    assert branch["max_utilization_pct"] == 130.0
    assert branch["max_utilization_contingency"] == 2
    assert branch["max_contingency_label"] == "NEGATIVE"
    assert any("CPU Dask backend" in note for note in tables["csv_flat_results"].notes)


def test_csv_flat_auto_prefers_dask_cudf_when_available(monkeypatch) -> None:
    fake_dask_cudf = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "dask_cudf", fake_dask_cudf)
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND", "auto")

    backend = csv_flat._lazy_backend()

    assert backend.name == "dask_cudf"
    assert backend.module is fake_dask_cudf


def test_csv_flat_auto_uses_cudf_before_cpu_dask(monkeypatch) -> None:
    fake_cudf = types.SimpleNamespace()
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dask_cudf":
            raise ModuleNotFoundError("No module named 'dask_cudf'")
        if name == "cudf":
            return fake_cudf
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND", "auto")

    backend = csv_flat._lazy_backend()

    assert backend.name == "cudf"
    assert backend.module is fake_cudf


def test_csv_flat_forced_dask_cudf_does_not_silently_use_cpu_dask(monkeypatch) -> None:
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dask_cudf":
            raise ModuleNotFoundError("No module named 'dask_cudf'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND", "dask_cudf")

    with pytest.raises(RuntimeError, match="dask_cudf"):
        csv_flat._lazy_backend()


def test_csv_flat_forced_cudf_does_not_silently_use_cpu_dask(monkeypatch) -> None:
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "cudf":
            raise ModuleNotFoundError("No module named 'cudf'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND", "cudf")

    with pytest.raises(RuntimeError, match="cudf"):
        csv_flat._lazy_backend()


def test_csv_flat_forced_dask_cudf_parse_fails_loudly(tmp_path, monkeypatch) -> None:
    run_dir = _csv_flat_run(tmp_path)
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dask_cudf":
            raise ModuleNotFoundError("No module named 'dask_cudf'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_BACKEND", "dask_cudf")

    with pytest.raises(RuntimeError, match="GPU csv_flat aggregation was required"):
        parse_all_output_tables(run_dir)


def test_dask_runtime_auto_falls_back_to_local_scheduler(monkeypatch) -> None:
    def fail_create_client(backend):
        raise RuntimeError("distributed unavailable")

    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_CLUSTER", "auto")
    monkeypatch.setattr(csv_flat, "_create_dask_client", fail_create_client)

    with csv_flat._dask_runtime(csv_flat._LazyBackend("dask", object())) as runtime:
        assert runtime.compute_kwargs == {"scheduler": "threads"}
        assert "local scheduler" in runtime.note


def test_dask_runtime_required_fails_when_cluster_is_unavailable(monkeypatch) -> None:
    def fail_create_client(backend):
        raise RuntimeError("distributed unavailable")

    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_CLUSTER", "required")
    monkeypatch.setattr(csv_flat, "_create_dask_client", fail_create_client)

    with pytest.raises(RuntimeError, match="Dask distributed runtime was required"):
        with csv_flat._dask_runtime(csv_flat._LazyBackend("dask", object())):
            pass


def test_dask_runtime_uses_distributed_client_when_available(monkeypatch) -> None:
    closed = []

    class FakeCloseable:
        def close(self):
            closed.append(type(self).__name__)

    def fake_create_client(backend):
        return FakeCloseable(), FakeCloseable(), "Dask distributed runtime was used with a 160GB worker memory limit."

    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_CLUSTER", "auto")
    monkeypatch.setattr(csv_flat, "_create_dask_client", fake_create_client)

    with csv_flat._dask_runtime(csv_flat._LazyBackend("dask", object())) as runtime:
        assert runtime.compute_kwargs == {}
        assert "distributed runtime" in runtime.note

    assert closed == ["FakeCloseable", "FakeCloseable"]


def test_cuda_cluster_kwargs_uses_separate_device_memory_limit(monkeypatch) -> None:
    monkeypatch.delenv("GRIDPACK_WORKBENCH_CSV_FLAT_DEVICE_MEMORY_LIMIT", raising=False)

    kwargs = csv_flat._cuda_cluster_kwargs("160GB", "/tmp/workbench-dask")

    assert kwargs["memory_limit"] == "160GB"
    assert kwargs["device_memory_limit"] == "auto"
    assert kwargs["local_directory"] == "/tmp/workbench-dask"


def test_cuda_cluster_kwargs_allows_explicit_device_memory_limit(monkeypatch) -> None:
    monkeypatch.setenv("GRIDPACK_WORKBENCH_CSV_FLAT_DEVICE_MEMORY_LIMIT", "96GB")

    kwargs = csv_flat._cuda_cluster_kwargs("160GB", "/tmp/workbench-dask")

    assert kwargs["memory_limit"] == "160GB"
    assert kwargs["device_memory_limit"] == "96GB"


def _csv_flat_run(root) -> object:
    run_dir = root / "runs" / "2026-07-05_12-00-00"
    work = run_dir / "work"
    work.mkdir(parents=True)
    (work / "input.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<Configuration>
  <Contingency_analysis>
    <outputFormat>csv_flat</outputFormat>
    <minVoltage>0.9</minVoltage>
    <maxVoltage>1.1</maxVoltage>
  </Contingency_analysis>
</Configuration>
""",
        encoding="utf-8",
    )
    (work / "training_tiny_flat1.csv").write_text(
        "\n".join(
            [
                "event_idx,contingency,from_bus,to_bus,circuit_id,p_from_mw,q_from_mvar,mva_from,rate_mva,loading_percent,viol,v_from_pu,v_to_pu,ang_from_deg,ang_to_deg",
                "0,base_case,101,102,1,10,0,10,100,10,0,1.0,1.0,0,0",
                "1,BR_101_102_1,101,102,1,125,0,125,100,125,1,1.0,1.0,0,0",
                "2,BR_201_202_1,101,102,1,60,0,60,100,60,0,1.0,1.0,0,0",
                "0,base_case,201,202,1,35,0,35,100,35,0,1.0,1.0,0,0",
                "1,BR_101_102_1,201,202,1,40,0,40,100,40,0,1.0,1.0,0,0",
            ]
        ),
        encoding="utf-8",
    )
    (work / "training_tiny_convergence.csv").write_text(
        "\n".join(
            [
                "event_idx,contingency,type,converged,iterations,final_tolerance,max_p_bus,max_p_mismatch,max_q_bus,max_q_mismatch,status_code",
                "1,BR_101_102_1,branch,true,2,1e-6,101,0,102,0,OK",
                "2,BR_201_202_1,branch,false,12,1e3,201,10,202,10,DIVERGED",
                "3,BR_301_302_1,branch,true,2,1e-6,301,0,302,0,ISLANDED",
                "4,GN_101_1,generator,true,2,1e-6,101,0,102,0,SLACK_OVERLOAD",
            ]
        ),
        encoding="utf-8",
    )
    (work / "training_tiny_buses.csv").write_text(
        "\n".join(
            [
                "bus_id,bus_name,base_kv,area,zone,owner,area_name,zone_name,owner_name",
                "101,FROM A,230.00,1,1,1,North,Zone,Owner",
                "102,TO A,230.00,1,1,1,North,Zone,Owner",
                "201,FROM B,138.00,2,1,1,South,Zone,Owner",
                "202,TO B,138.00,2,1,1,South,Zone,Owner",
            ]
        ),
        encoding="utf-8",
    )
    return run_dir
