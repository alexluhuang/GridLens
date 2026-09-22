from __future__ import annotations

import json

import pytest

from gridlens.analysis.event_index import build_event_index, query_event_index
from gridlens.analysis.parsers import parse_all_output_tables


@pytest.fixture
def indexed_run(tmp_path):
    run = tmp_path / "run"
    (run / "work").mkdir(parents=True)
    (run / "work/test_flat.csv").write_text(
        "event_idx,contingency,from_bus,to_bus,circuit_id,section,rate_mva,loading_percent,viol\n"
        "0,base,1,2,1,,100,80,0\n"
        "1,outage,1,2,1,,100,125,1\n"
        "1,outage,1,2,2,,100,75,0\n"
        "2,failed,1,2,1,2,100,-140,1\n"
        "65,other,1,2,1,,100,90,0\n"
    )
    (run / "work/test_convergence.csv").write_text("event_idx,contingency,converged,status_code\n0,base,true,OK\n1,outage,true,OK\n2,failed,false,FAILED\n65,other,true,OK\n")
    return run


@pytest.mark.parametrize("layout", ["unpartitioned", "sorted", "buckets"])
def test_index_event_and_full_branch_key(indexed_run, layout):
    pytest.importorskip("pyarrow")
    manifest = build_event_index(indexed_run, layout=layout)
    assert manifest["rows"] == 5
    rows, total, paths = query_event_index(indexed_run, event_idx=1, limit=1)
    assert total == 2 and len(rows) == 1
    assert rows[0]["loading_percent"] == 125
    assert paths[0].name == "manifest.json"
    rows, total, _ = query_event_index(indexed_run, branch=(1, 2, "1", ""))
    assert total == 3
    assert [row["event_idx"] for row in rows] == [1, 65, 0]
    rows, total, _ = query_event_index(indexed_run, branch=(1, 2, "1", "2"))
    assert total == 1 and rows[0]["loading_percent"] == -140


def test_index_rejects_stale_source_and_escaping_manifest(indexed_run):
    pytest.importorskip("pyarrow")
    build_event_index(indexed_run)
    path = indexed_run / "reports/event_index/manifest.json"
    manifest = json.loads(path.read_text())
    path.write_text(json.dumps({**manifest, "generation": "../outside"}))
    with pytest.raises(ValueError):
        query_event_index(indexed_run, event_idx=1)
    path.write_text(json.dumps(manifest))
    source = indexed_run / manifest["source"]
    source.write_text(source.read_text() + "1,outage,1,2,3,,100,40,0\n")
    with pytest.raises(ValueError, match="stale"):
        query_event_index(indexed_run, event_idx=1)


def test_compact_contingency_summary_preserves_convergence_and_sections(indexed_run, monkeypatch):
    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "python")
    tables = parse_all_output_tables(indexed_run)
    rows = {row["event_idx"]: row for row in tables["contingency_summary"].rows}
    assert rows[1]["monitored_facility_count"] == 2
    assert rows[1]["max_loading_pct"] == 125
    assert rows[1]["violation_count"] == 1
    assert rows[1]["converged"] is True
    assert rows[2]["converged"] is False
    assert json.loads(rows[2]["worst_facility_key"]) == ["1", "2", "1", "2"]


def test_index_preserves_numeric_looking_circuits(indexed_run):
    pytest.importorskip("pyarrow")
    path = indexed_run / "work/test_flat.csv"
    with path.open("a") as handle:
        handle.write("1,outage,1,2,1.0,,100,50,0\n1,outage,1,2,01,,100,60,0\n")
    build_event_index(indexed_run)
    for circuit in ("1.0", "01"):
        rows, total, _ = query_event_index(indexed_run, branch=(1, 2, circuit, ""))
        assert total == 1 and rows[0]["line_id"] == circuit


def test_row_frame_and_index_agree_on_literal_branch_keys(indexed_run, monkeypatch):
    """Quoted, padded, and numeric-looking labels remain distinct across all result paths."""
    pytest.importorskip("pyarrow")
    pandas = pytest.importorskip("pandas")
    from gridlens.analysis import csv_flat

    path = indexed_run / "work/test_flat.csv"
    path.write_text(
        "event_idx,contingency,from_bus,to_bus,circuit_id,section,rate_mva,loading_percent,viol\n"
        "1,outage,1,2,1,,100,10,0\n"
        "1,outage,1,2,01,,100,20,0\n"
        "1,outage,1,2,1.0,,100,30,0\n"
        "1,outage,1,2,'2 ',,100,40,0\n"
        "1,outage,1,2,A,,100,50,0\n"
    )
    lookup = csv_flat._column_lookup(csv_flat._header(path))
    frame = csv_flat._normalized_eager_flat_frame(path, lookup, csv_flat._LazyBackend("pandas", pandas))
    frame_values = dict(zip(frame["line_id"], frame["loading_percent"]))
    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "python")
    parsed = parse_all_output_tables(indexed_run)
    row_values = {row["line_id"]: float(row["max_utilization_pct"]) for row in parsed["pflow_mm"].rows}
    assert frame_values == row_values == {"1": 10, "01": 20, "1.0": 30, "2": 40, "A": 50}
    build_event_index(indexed_run)
    for circuit, maximum in row_values.items():
        rows, total, _ = query_event_index(indexed_run, branch=(1, 2, circuit, ""))
        assert total == 1
        assert abs(rows[0]["loading_percent"]) == maximum


def test_contingency_summary_matches_gpu_reduction(indexed_run, monkeypatch):
    pytest.importorskip("cudf")
    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "python")
    expected = parse_all_output_tables(indexed_run)["contingency_summary"].rows
    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "cudf")
    actual = parse_all_output_tables(indexed_run)["contingency_summary"].rows
    assert actual == expected
