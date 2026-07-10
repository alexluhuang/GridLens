from __future__ import annotations

from gridlens.analysis.enrichment import enrich_with_bus_metadata, voltage_class
from gridlens.analysis.parser_models import ParsedTable


def test_voltage_class_handles_missing_and_invalid_values() -> None:
    assert voltage_class(None) == "unknown"
    assert voltage_class("") == "unknown"
    assert voltage_class("not-a-number") == "unknown"
    assert voltage_class(49.9) == "<50 kV"
    assert voltage_class(50.0) == "50-99 kV"
    assert voltage_class(99.9) == "50-99 kV"
    assert voltage_class(100.0) == "100-229 kV"


def test_enrich_with_bus_metadata_adds_branch_context() -> None:
    tables = {
        "bus_metadata": ParsedTable(
            name="bus_metadata",
            source_file="case.raw",
            columns=["bus_id", "bus_name", "base_kv", "area", "zone"],
            rows=[
                {"bus_id": 101, "bus_name": "FROM", "base_kv": 138.0, "area": 11, "zone": 1},
                {"bus_id": 102, "bus_name": "TO", "base_kv": 230.0, "area": 12, "zone": 1},
            ],
        ),
        "area_metadata": ParsedTable(
            name="area_metadata",
            source_file="case.raw",
            columns=["area", "area_name"],
            rows=[
                {"area": 11, "area_name": "North"},
                {"area": 12, "area_name": "South"},
            ],
        ),
        "perf_mm": ParsedTable(
            name="perf_mm",
            source_file="perf_mm.txt",
            columns=["from_bus", "to_bus", "line_id"],
            rows=[{"from_bus": "101", "to_bus": "102", "line_id": "1"}],
        ),
    }

    enrich_with_bus_metadata(tables)

    row = tables["perf_mm"].rows[0]
    assert row["from_bus_name"] == "FROM"
    assert row["to_bus_name"] == "TO"
    assert row["area"] == "11-12"
    assert row["control_area"] == "North / South"
    assert row["from_area_name"] == "North"
    assert row["voltage_class"] == "230-344 kV"
    assert "voltage_class" in tables["perf_mm"].columns
