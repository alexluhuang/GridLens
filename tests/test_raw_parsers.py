from __future__ import annotations

from pathlib import Path

from gridpack_workbench.analysis.raw_parsers import (
    parse_raw_area_metadata,
    parse_raw_branch_metadata,
    parse_raw_bus_metadata,
)


def test_parse_raw_bus_and_branch_metadata(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    work_dir = run_dir / "work"
    work_dir.mkdir(parents=True)
    (work_dir / "training.raw").write_text(
        """0, 100.00, 33, 0, 0, 60.00
 101, 'BUS101', 138.0000, 1, 11, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
 102, 'BUS102', 230.0000, 1, 12, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
0 / END OF BUS DATA, BEGIN LOAD DATA
0 / END OF LOAD DATA, BEGIN FIXED SHUNT DATA
0 / END OF FIXED SHUNT DATA, BEGIN GENERATOR DATA
0 / END OF GENERATOR DATA, BEGIN BRANCH DATA
 101, 102, '1 ', 0.010000, 0.050000, 0.000000, 100.00, 110.00, 120.00, 0.0, 0.0, 0.0, 0.0, 1, 1, 10.0, 1, 1.0
0 / END OF BRANCH DATA, BEGIN TRANSFORMER DATA
0 / END OF TRANSFORMER DATA, BEGIN AREA DATA
 11, 101, 0.0, 10.0, 'NORTH'
 12, 102, 0.0, 10.0, 'SOUTH'
0 / END OF AREA DATA
""",
        encoding="utf-8",
    )

    buses = parse_raw_bus_metadata(run_dir)
    branches = parse_raw_branch_metadata(run_dir)
    areas = parse_raw_area_metadata(run_dir)

    assert buses.row_count == 2
    assert buses.rows[0]["bus_name"] == "BUS101"
    assert buses.rows[1]["base_kv"] == 230.0
    assert areas.row_count == 2
    assert areas.rows[0]["area_name"] == "NORTH"
    assert branches.row_count == 1
    assert branches.rows[0]["from_bus"] == 101
    assert branches.rows[0]["to_bus"] == 102
    assert branches.rows[0]["line_id"] == "1"
    assert branches.rows[0]["ratea"] == 100.0
    assert branches.rows[0]["ratec"] == 120.0


def test_parse_raw_branch_metadata_classifies_transformer_derived_rows(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    work_dir = run_dir / "work"
    work_dir.mkdir(parents=True)
    (work_dir / "training.raw").write_text(
        """0, 100.00, 33, 0, 0, 60.00
 101, 'BUS101', 138.0000, 1, 11, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
 102, 'BUS102', 230.0000, 1, 12, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
 201, 'BUS201', 230.0000, 1, 11, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
 202, 'BUS202', 115.0000, 1, 11, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
 203, 'BUS203',  13.8000, 1, 11, 1, 1, 1.0000, 0.0, 1.1000, 0.9000, 1.1000, 0.9000
0 / END OF BUS DATA, BEGIN LOAD DATA
0 / END OF LOAD DATA, BEGIN FIXED SHUNT DATA
0 / END OF FIXED SHUNT DATA, BEGIN GENERATOR DATA
0 / END OF GENERATOR DATA, BEGIN BRANCH DATA
0 / END OF BRANCH DATA, BEGIN TRANSFORMER DATA
 101, 102, 0, '1 ', 1, 1, 1, 0.0, 0.0, 2, 'XFMR-2W', 1, 1, 1.0
 0.010000, 0.050000, 100.00
 1.00000, 138.000, 0.000, 100.00, 110.00, 120.00, 0, 0, 1.100, 0.900, 1.010, 0.990, 33, 0, 0.0, 0.0, 0.0
 1.00000, 230.000
 201, 202, 203, 'A ', 1, 1, 1, 0.0, 0.0, 2, 'XFMR-3W', 1, 1, 1.0
 0.001, 0.020, 100.00, 0.002, 0.030, 100.00, 0.003, 0.040, 100.00, 1.0, 0.0
 1.00000, 230.000, 0.000, 200.00, 210.00, 220.00, 0, 0, 1.100, 0.900, 1.010, 0.990, 33, 0, 0.0, 0.0, 0.0
 1.00000, 115.000, 0.000, 150.00, 160.00, 170.00, 0, 0, 1.100, 0.900, 1.010, 0.990, 33, 0, 0.0, 0.0, 0.0
 1.00000,  13.800, 0.000,  50.00,  60.00,  70.00, 0, 0, 1.100, 0.900, 1.010, 0.990, 33, 0, 0.0, 0.0, 0.0
0 / END OF TRANSFORMER DATA, BEGIN AREA DATA
""",
        encoding="utf-8",
    )

    branches = parse_raw_branch_metadata(
        run_dir,
        branch_rows=[
            {"from_bus": 101, "to_bus": 102, "line_id": "1"},
            {"from_bus": 201, "to_bus": 90001, "line_id": "A"},
            {"from_bus": 202, "to_bus": 90001, "line_id": "A"},
            {"from_bus": 203, "to_bus": 90001, "line_id": "A"},
        ],
    )

    assert branches.row_count == 4
    assert [row["raw_branch_type"] for row in branches.rows] == [
        "two_winding_transformer_branch",
        "three_winding_transformer_branch",
        "three_winding_transformer_branch",
        "three_winding_transformer_branch",
    ]
    assert [row["ratec"] for row in branches.rows] == [120.0, 220.0, 170.0, 70.0]
    assert branches.rows[1]["transformer_internal_bus"] == 90001
    assert branches.rows[1]["transformer_winding"] == "1"


def test_parse_raw_metadata_returns_notes_for_missing_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    buses = parse_raw_bus_metadata(run_dir)
    branches = parse_raw_branch_metadata(run_dir)
    areas = parse_raw_area_metadata(run_dir)

    assert buses.row_count == 0
    assert branches.row_count == 0
    assert areas.row_count == 0
    assert buses.notes == ["training.raw was not found."]
    assert branches.notes == ["training.raw was not found."]
    assert areas.notes == ["training.raw was not found."]
