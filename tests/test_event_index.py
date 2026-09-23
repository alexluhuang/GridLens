from __future__ import annotations

import json

import pytest

from gridlens.analysis.event_index import IndexColumnsMissing, IndexStale, build_event_index, case_key, group_cases, scan_cases
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
    rows, total, paths = scan_cases(indexed_run, metric="loading_percent", events={1}, limit=1)
    assert total == 2 and len(rows) == 1
    assert (rows[0]["loading_percent"], rows[0]["value"]) == (125, 125)
    assert paths[0].name == "manifest.json"
    rows, total, _ = scan_cases(indexed_run, metric="loading_percent", keys={case_key(1, 2, "1", "")}, limit=0)
    assert total == 3
    assert [row["event_idx"] for row in rows] == [1, 65, 0]
    # Cases rank by absolute loading, and each keeps the loading GridPACK reported.
    rows, total, _ = scan_cases(indexed_run, metric="loading_percent", keys={case_key(1, 2, "1", "2")})
    assert total == 1 and (rows[0]["loading_percent"], rows[0]["value"]) == (-140, 140)


def test_index_rejects_stale_source_and_escaping_manifest(indexed_run):
    pytest.importorskip("pyarrow")
    build_event_index(indexed_run)
    path = indexed_run / "reports/event_index/manifest.json"
    manifest = json.loads(path.read_text())
    path.write_text(json.dumps({**manifest, "generation": "../outside"}))
    with pytest.raises(ValueError):
        scan_cases(indexed_run, metric="loading_percent", events={1})
    path.write_text(json.dumps({**manifest, "version": "2026.09.22"}))
    with pytest.raises(IndexStale):
        scan_cases(indexed_run, metric="loading_percent", events={1})
    path.write_text(json.dumps(manifest))
    source = indexed_run / manifest["source"]
    source.write_text(source.read_text() + "1,outage,1,2,3,,100,40,0\n")
    with pytest.raises(IndexStale, match="stale"):
        scan_cases(indexed_run, metric="loading_percent", events={1})


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
        rows, total, _ = scan_cases(indexed_run, metric="loading_percent", keys={case_key(1, 2, circuit, "")})
        assert total == 1 and rows[0]["line_id"] == circuit


@pytest.mark.parametrize("backend", ["pandas", "cudf"])
def test_row_frame_and_index_agree_on_literal_branch_keys(indexed_run, monkeypatch, backend):
    """Quoted, padded, and numeric-looking labels remain distinct across all result paths."""
    pytest.importorskip("pyarrow")
    module = pytest.importorskip(backend)
    from gridlens.analysis import csv_flat

    path = indexed_run / "work/test_flat.csv"
    path.write_text(
        "event_idx,contingency,from_bus,to_bus,circuit_id,section,rate_mva,loading_percent,viol\n"
        "1,outage,1,2,1,1,100,10,0\n"
        "1,outage,1,2,01,01,100,20,0\n"
        "1,outage,1,2,1.0,1.0,100,30,0\n"
        "1,outage,1,2,'2 ','2 ',100,40,0\n"
        "1,outage,1,2,A,,100,50,0\n"
    )
    lookup = csv_flat._column_lookup(csv_flat._header(path))
    frame = csv_flat._normalized_eager_flat_frame(path, lookup, csv_flat._LazyBackend(backend, module))
    if backend == "cudf":
        frame = frame.to_pandas()
    frame_values = {(row.line_id, row.section): row.loading_percent for row in frame.itertuples()}
    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "python")
    parsed = parse_all_output_tables(indexed_run)
    row_values = {(row["line_id"], row["section"]): float(row["max_utilization_pct"]) for row in parsed["pflow_mm"].rows}
    assert frame_values == row_values == {("1", "1"): 10, ("01", "01"): 20, ("1.0", "1.0"): 30, ("2", "2"): 40, ("A", ""): 50}
    build_event_index(indexed_run)
    for (circuit, section), maximum in row_values.items():
        rows, total, _ = scan_cases(indexed_run, metric="loading_percent", keys={case_key(1, 2, circuit, section)})
        assert total == 1
        assert abs(rows[0]["loading_percent"]) == maximum


def test_index_stores_flows_voltages_and_angles_as_numbers(tmp_path):
    """Flows, voltages, and angles are numbers in the index, blanks are missing, and derived metrics follow them."""
    pytest.importorskip("pyarrow")
    run = tmp_path / "run"
    (run / "work").mkdir(parents=True)
    (run / "work/case_flat.csv").write_text(
        "event_idx,contingency,from_bus,to_bus,circuit_id,p_from_mw,q_from_mvar,mva_from,rate_mva,loading_percent,viol,v_from_pu,v_to_pu,ang_from_deg,ang_to_deg\n"
        "0,base_case,1,2,1,50.0,10.0,51.0,100,51,0,1.02,1.01,-4.0,-6.0\n"
        "1,BR_1_2_1,1,3,1,-120.5,-30.25,124.2,100,124.2,1,0.94,0.97,-10.0,-2.5\n"
        "1,BR_1_2_1,2,3,1,40.0,,40.0,100,40,0,,0.99,,-3.0\n"
        "2,BR_2_3_1,1,2,1,90.0,20.0,92.2,100,92.2,0,0.99,0.96,-5.0,-17.0\n"
    )
    build_event_index(run)
    flows, total, _ = scan_cases(run, metric="mva_from", limit=0)
    assert total == 4 and [row["value"] for row in flows] == [124.2, 92.2, 51.0, 40.0]
    assert "p_from_mw" not in flows[0]  # a scan reads only the columns it needs
    extra, _, _ = scan_cases(run, metric="mva_from", limit=1, extra=("p_from_mw", "q_from_mvar"))
    assert (extra[0]["p_from_mw"], extra[0]["q_from_mvar"]) == (-120.5, -30.25)
    low, total, _ = scan_cases(run, metric="min_voltage_pu", descending=False, conditions=[("min_voltage_pu", "<", 0.97)])
    assert total == 2 and [row["value"] for row in low] == [0.94, 0.96]
    # A missing end angle leaves the difference unknown rather than zero.
    angles, total, _ = scan_cases(run, metric="angle_difference_deg", limit=0)
    assert total == 3 and [row["value"] for row in angles] == [12.0, 7.5, 2.0]
    overloads, total, _ = scan_cases(run, metric="loading_percent", conditions=[("loading_percent", ">=", 100), ("viol", "==", 1)])
    assert total == 1 and overloads[0]["event_idx"] == 1
    groups, used, _ = group_cases(run, metric="loading_percent", statistic="count", by="event", labels={0: ["base"], 1: ["BR_1_2_1"], 2: ["BR_2_3_1"]}, conditions=[("loading_percent", ">", 45)])
    assert used == 3 and {label: group.result() for label, group in groups.items()} == {"base": 1, "BR_1_2_1": 1, "BR_2_3_1": 1}
    # A count takes the case whose from-end voltage is blank; a mean of that voltage does not.
    voltages, _, _ = group_cases(run, metric="v_from_pu", statistic="count", by="event", labels={1: ["one"]}, events={1})
    means, _, _ = group_cases(run, metric="v_from_pu", statistic="mean", by="event", labels={1: ["one"]}, events={1})
    assert (voltages["one"].result(), means["one"].count, means["one"].result()) == (2, 1, 0.94)
    peaks, _, _ = group_cases(run, metric="mva_from", statistic="max", by="facility", labels={case_key(1, 2, "1", ""): ["north"], case_key(1, 3, "1", ""): ["north", "south"]})
    assert {label: group.result() for label, group in peaks.items()} == {"north": 124.2, "south": 124.2, "unknown": 40.0}
    medians, _, _ = group_cases(run, metric="loading_percent", statistic="median", by="event", labels={1: ["one"]}, events={1})
    assert medians["one"].result() == pytest.approx(82.1)
    with pytest.raises(IndexColumnsMissing):
        scan_cases(run, metric="loading_percent", conditions=[("nonexistent", ">", 1)])


def test_contingency_summary_matches_gpu_reduction(indexed_run, monkeypatch):
    pytest.importorskip("cudf")
    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "python")
    expected = parse_all_output_tables(indexed_run)["contingency_summary"].rows
    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "cudf")
    actual = parse_all_output_tables(indexed_run)["contingency_summary"].rows
    assert actual == expected
