from __future__ import annotations

from pathlib import Path

from gridlens.analysis import csv_flat
from gridlens.analysis.parsers import parse_all_output_tables
from gridlens.analysis.progress import AnalysisProgress, PHASE_PARSE


def test_estimate_total_rows_is_close(tmp_path) -> None:
    path = tmp_path / "estimate.csv"
    # Uniform-width rows (like real GridPACK flat output) -> accurate estimate.
    rows = ["from_bus,to_bus,loading"] + [f"{i % 1000:06d},{i % 1000:06d},{i % 100:05d}" for i in range(1000)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    estimate = csv_flat._estimate_total_rows(path, sample_bytes=4096)
    assert estimate is not None
    # Within ~6% of the true 1000 data rows for uniform-width data.
    assert 940 <= estimate <= 1060


def test_estimate_total_rows_handles_tiny_or_missing_file(tmp_path) -> None:
    assert csv_flat._estimate_total_rows(tmp_path / "missing.csv") is None
    header_only = tmp_path / "header.csv"
    header_only.write_text("a,b,c\n", encoding="utf-8")
    assert csv_flat._estimate_total_rows(header_only) is None


def test_format_rows() -> None:
    assert csv_flat._format_rows(74_701_440) == "74.7M"
    assert csv_flat._format_rows(8_500) == "8K"
    assert csv_flat._format_rows(300) == "300"
    assert csv_flat._format_rows(None) == "many"


def test_format_elapsed() -> None:
    assert csv_flat._format_elapsed(5.9) == "5s"
    assert csv_flat._format_elapsed(83) == "1:23"


def test_backend_label() -> None:
    assert "GPU" in csv_flat._backend_label("dask_cudf")
    assert "CPU" in csv_flat._backend_label("dask")
    assert csv_flat._backend_label("mystery") == "mystery"


def test_progress_heartbeat_emits_updates() -> None:
    updates: list[AnalysisProgress] = []
    # Interval is 1s; the immediate first beat should fire before we exit.
    with csv_flat._progress_heartbeat(updates.append, lambda elapsed: f"working {elapsed:.0f}"):
        pass
    assert updates
    assert updates[0].phase == PHASE_PARSE
    assert updates[0].detail.startswith("working")


def test_progress_heartbeat_is_noop_without_callback() -> None:
    # Should not raise or spawn anything when there is no callback.
    with csv_flat._progress_heartbeat(None, lambda elapsed: "x"):
        pass


def test_streaming_parse_emits_row_progress(tmp_path, monkeypatch) -> None:
    work = tmp_path / "work"
    work.mkdir()
    header = "event_idx,contingency,from_bus,to_bus,circuit_id,rate_mva,loading_percent,viol"
    lines = [header]
    # Enough rows to cross a small progress interval several times.
    for event in range(12):
        lines.append(f"{event},c{event},101,102,1,100,{10 + event},0")
    (work / "case_flat.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setenv("GRIDLENS_CSV_FLAT_BACKEND", "python")  # force streaming path
    monkeypatch.setattr(csv_flat, "_PROGRESS_ROW_INTERVAL", 4)

    updates: list[AnalysisProgress] = []
    tables = parse_all_output_tables(tmp_path, progress=updates.append)

    # The branch was still aggregated correctly.
    assert tables["pflow_mm"].rows
    row_messages = [u for u in updates if "row " in u.detail and "contingency outputs" in u.detail]
    assert row_messages, [u.detail for u in updates]
    # Row counts should be monotonically increasing multiples of the interval.
    counts = [int(m.detail.split("row ")[1].split(" ")[0].replace(",", "")) for m in row_messages]
    assert counts == sorted(counts)
    assert counts[0] == 4
