from __future__ import annotations

from gridlens.analysis.parser_models import ParsedTable
from gridlens.gui.analysis_view_models import (
    UtilizationBranchOptions,
    max_line_utilization_rows,
    numeric_value,
    summarize_control_area_utilization,
    summarize_voltage_group_utilization,
)


def test_numeric_value_uses_default_for_invalid_values() -> None:
    assert numeric_value("2.5") == 2.5
    assert numeric_value(None, default=9.0) == 9.0
    assert numeric_value("not-a-number", default=-1.0) == -1.0


def test_requested_analysis_graph_rows_merge_filter_group_and_sort() -> None:
    tables = {
        "area_metadata": ParsedTable(
            name="area_metadata",
            source_file="training.raw",
            columns=[],
            rows=[
                {"area": 1, "area_name": "North"},
                {"area": 2, "area_name": "South"},
            ],
        ),
        "branch_metadata": ParsedTable(
            name="branch_metadata",
            source_file="training.raw",
            columns=[],
            rows=[
                _branch(101, 102, "1", 138.0, 138.0, 100.0, "North", "100-229 kV", 1, "North", 1, "North"),
                _branch(201, 202, "1", 230.0, 230.0, 200.0, "South", "230-344 kV", 2, "South", 2, "South"),
                _branch(301, 302, "1", 69.0, 69.0, 100.0, "Low", "50-99 kV"),
                _branch(401, 402, "1", 230.0, 345.0, 50.0, "North / South", "345-499 kV", 1, "North", 2, "South"),
                _branch(501, 502, "1", 49.0, 49.0, 100.0, "Subtransmission", "<50 kV"),
            ],
        ),
        "pflow": ParsedTable(
            name="pflow",
            source_file="pflow.txt",
            columns=[],
            rows=[
                _flow(101, 102, "1", 50.0),
                _flow(201, 202, "1", 120.0),
                _flow(301, 302, "1", 70.0),
                _flow(401, 402, "1", 25.0),
                _flow(501, 502, "1", 95.0),
            ],
        ),
        "qflow": ParsedTable(
            name="qflow",
            source_file="qflow.txt",
            columns=[],
            rows=[
                _flow(101, 102, "1", 0.0),
                _flow(201, 202, "1", 0.0),
                _flow(301, 302, "1", 0.0),
                _flow(401, 402, "1", 0.0),
                _flow(501, 502, "1", 0.0),
            ],
        ),
        "pflow_mm": ParsedTable(
            name="pflow_mm",
            source_file="pflow_mm.txt",
            columns=[],
            rows=[
                _pflow_mm(101, 102, "1", 0.0, 50.0, -100.0, 100.0, 1, 3),
                _pflow_mm(201, 202, "1", 0.0, 180.0, -200.0, 200.0, 1, 4),
                _pflow_mm(301, 302, "1", 0.0, 80.0, -100.0, 100.0, 1, 5),
                _pflow_mm(401, 402, "1", 0.0, 20.0, -50.0, 50.0, 1, 6),
                _pflow_mm(501, 502, "1", 0.0, 95.0, -100.0, 100.0, 1, 7),
            ],
        ),
        "perf_mm": ParsedTable(
            name="perf_mm",
            source_file="perf_mm.txt",
            columns=[],
            rows=[
                _perf(101, 102, "1", 0.25, 3),
                _perf(201, 202, "1", 0.81, 4),
                _perf(301, 302, "1", 0.64, 5),
                _perf(401, 402, "1", 0.16, 6),
                _perf(501, 502, "1", 0.9, 7),
            ],
        ),
    }

    branch_rows = max_line_utilization_rows(tables)
    area_rows = summarize_control_area_utilization(branch_rows)
    voltage_rows = summarize_voltage_group_utilization(branch_rows)
    north_voltage_rows = summarize_voltage_group_utilization(
        [row for row in branch_rows if "North" in row["control_areas"]]
    )
    all_line_rows = max_line_utilization_rows(tables)

    assert [row["control_area"] for row in area_rows] == ["Low", "South", "North"]
    assert area_rows[0]["average_utilization_pct"] == 80.0
    assert area_rows[1]["average_utilization_pct"] == 65.0
    assert area_rows[2]["average_utilization_pct"] == 45.0
    assert all(row["control_area"] != "Subtransmission" for row in area_rows)
    assert all(" / " not in row["control_area"] for row in area_rows)
    assert next(row for row in branch_rows if row["from_bus"] == 401)["control_areas"] == ["North", "South"]
    assert all(row["from_bus"] != 501 for row in branch_rows)
    assert [row["voltage_group"] for row in voltage_rows] == ["50-99 kV", "100-229 kV", "230-344 kV", "345-499 kV"]
    assert [row["average_utilization_pct"] for row in voltage_rows] == [80.0, 50.0, 90.0, 40.0]
    assert [row["voltage_group"] for row in north_voltage_rows] == ["100-229 kV", "345-499 kV"]
    assert [row["voltage_group"] for row in all_line_rows] == ["345-499 kV", "100-229 kV", "50-99 kV", "230-344 kV"]


def test_max_line_utilization_ignores_perf_mm() -> None:
    tables = {
        "branch_metadata": ParsedTable(
            name="branch_metadata",
            source_file="training.raw",
            columns=[],
            rows=[_branch(101, 102, "1", 230.0, 230.0, 5.0, "North", "230-344 kV", ratec=50.0)],
        ),
        "pflow_mm": ParsedTable(
            name="pflow_mm",
            source_file="pflow_mm.txt",
            columns=[],
            rows=[
                {
                    "from_bus": 101,
                    "to_bus": 102,
                    "line_id": "1",
                    "min_value": -120.0,
                    "max_value": 80.0,
                    "min_allowable": -50.0,
                    "max_allowable": 50.0,
                    "min_contingency": 8,
                    "max_contingency": 9,
                }
            ],
        ),
        "perf_mm": ParsedTable(
            name="perf_mm",
            source_file="perf_mm.txt",
            columns=[],
            rows=[_perf(101, 102, "1", 8100.0, 10)],
        ),
    }

    rows = max_line_utilization_rows(tables)

    assert len(rows) == 1
    assert rows[0]["max_utilization_pct"] == 240.0
    assert rows[0]["max_contingency"] == 8
    assert rows[0]["utilization_source"] == "pflow_mm"


def test_line_utilization_excludes_transformer_equivalent_branches() -> None:
    tables = {
        "branch_metadata": ParsedTable(
            name="branch_metadata",
            source_file="training.raw",
            columns=[],
            rows=[
                _branch(
                    101,
                    102,
                    "1",
                    230.0,
                    230.0,
                    100.0,
                    "North",
                    "230-344 kV",
                    ratec=100.0,
                    raw_branch_type="transformer_equivalent_branch",
                )
            ],
        ),
        "pflow": ParsedTable(
            name="pflow",
            source_file="pflow.txt",
            columns=[],
            rows=[_flow(101, 102, "1", 60.0)],
        ),
        "pflow_mm": ParsedTable(
            name="pflow_mm",
            source_file="pflow_mm.txt",
            columns=[],
            rows=[_pflow_mm(101, 102, "1", -120.0, 80.0, -100.0, 100.0, 1, 2)],
        ),
    }

    assert max_line_utilization_rows(tables) == []


def test_line_utilization_can_include_transformer_derived_branches() -> None:
    tables = {
        "branch_metadata": ParsedTable(
            name="branch_metadata",
            source_file="training.raw",
            columns=[],
            rows=[
                _branch(
                    101,
                    102,
                    "1",
                    230.0,
                    230.0,
                    100.0,
                    "North",
                    "230-344 kV",
                    ratec=100.0,
                    raw_branch_type="two_winding_transformer_branch",
                ),
                _branch(
                    201,
                    90001,
                    "A",
                    230.0,
                    0.0,
                    200.0,
                    "North",
                    "230-344 kV",
                    ratec=200.0,
                    raw_branch_type="three_winding_transformer_branch",
                ),
            ],
        ),
        "pflow": ParsedTable(
            name="pflow",
            source_file="pflow.txt",
            columns=[],
            rows=[
                _flow(101, 102, "1", 50.0),
                _flow(201, 90001, "A", 80.0),
            ],
        ),
        "pflow_mm": ParsedTable(
            name="pflow_mm",
            source_file="pflow_mm.txt",
            columns=[],
            rows=[
                _pflow_mm(101, 102, "1", -90.0, 75.0, -100.0, 100.0, 1, 2),
                _pflow_mm(201, 90001, "A", -120.0, 100.0, -200.0, 200.0, 3, 4),
            ],
        ),
    }

    assert max_line_utilization_rows(tables) == []

    two_winding_rows = max_line_utilization_rows(
        tables,
        UtilizationBranchOptions(include_two_winding_transformers=True),
    )
    all_transformer_rows = max_line_utilization_rows(
        tables,
        UtilizationBranchOptions(
            include_two_winding_transformers=True,
            include_three_winding_transformers=True,
        ),
    )

    assert [row["raw_branch_type"] for row in two_winding_rows] == ["two_winding_transformer_branch"]
    assert [row["max_utilization_pct"] for row in all_transformer_rows] == [60.0, 90.0]


def test_transformer_utilization_groups_by_step_direction() -> None:
    tables = {
        "branch_metadata": ParsedTable(
            name="branch_metadata",
            source_file="training.raw",
            columns=[],
            rows=[
                _branch(
                    101,
                    102,
                    "1",
                    115.0,
                    230.0,
                    100.0,
                    "North",
                    "100-229 kV",
                    ratec=100.0,
                    raw_branch_type="two_winding_transformer_branch",
                ),
                _branch(
                    201,
                    202,
                    "1",
                    345.0,
                    138.0,
                    100.0,
                    "South",
                    "345-499 kV",
                    ratec=100.0,
                    raw_branch_type="two_winding_transformer_branch",
                ),
                _branch(301, 302, "1", 230.0, 230.0, 100.0, "Branch", "230-344 kV", ratec=100.0),
            ],
        ),
        "pflow_mm": ParsedTable(
            name="pflow_mm",
            source_file="pflow_mm.txt",
            columns=[],
            rows=[
                _pflow_mm(101, 102, "1", -60.0, 80.0, -100.0, 100.0, 1, 2),
                _pflow_mm(201, 202, "1", -70.0, 90.0, -100.0, 100.0, 3, 4),
                _pflow_mm(301, 302, "1", -95.0, 95.0, -100.0, 100.0, 5, 6),
            ],
        ),
    }

    rows = max_line_utilization_rows(
        tables,
        UtilizationBranchOptions(
            include_nontransformer_branches=False,
            include_two_winding_transformers=True,
            include_three_winding_transformers=True,
        ),
    )
    grouped = summarize_voltage_group_utilization(rows)

    assert [row["voltage_group"] for row in rows] == ["Step-up transformer", "Step-down transformer"]
    assert [row["voltage_group"] for row in grouped] == ["Step-up transformer", "Step-down transformer"]


def _branch(
    from_bus: int,
    to_bus: int,
    line_id: str,
    from_base_kv: float,
    to_base_kv: float,
    ratea: float,
    control_area: str,
    voltage_class: str,
    from_area: int | None = None,
    from_area_name: str = "",
    to_area: int | None = None,
    to_area_name: str = "",
    ratec: float | None = None,
    raw_branch_type: str = "nontransformer_branch",
) -> dict[str, object]:
    return {
        "from_bus": from_bus,
        "to_bus": to_bus,
        "line_id": line_id,
        "from_bus_name": f"BUS{from_bus}",
        "to_bus_name": f"BUS{to_bus}",
        "from_base_kv": from_base_kv,
        "to_base_kv": to_base_kv,
        "ratea": ratea,
        "ratec": ratea if ratec is None else ratec,
        "control_area": control_area,
        "from_area": from_area,
        "from_area_name": from_area_name,
        "to_area": to_area,
        "to_area_name": to_area_name,
        "voltage_class": voltage_class,
        "raw_branch_type": raw_branch_type,
    }


def _flow(from_bus: int, to_bus: int, line_id: str, average: float) -> dict[str, object]:
    return {
        "from_bus": from_bus,
        "to_bus": to_bus,
        "line_id": line_id,
        "average": average,
    }


def _pflow_mm(
    from_bus: int,
    to_bus: int,
    line_id: str,
    min_value: float,
    max_value: float,
    min_allowable: float,
    max_allowable: float,
    min_contingency: int,
    max_contingency: int,
) -> dict[str, object]:
    return {
        "from_bus": from_bus,
        "to_bus": to_bus,
        "line_id": line_id,
        "min_value": min_value,
        "max_value": max_value,
        "min_allowable": min_allowable,
        "max_allowable": max_allowable,
        "min_contingency": min_contingency,
        "max_contingency": max_contingency,
    }


def _perf(from_bus: int, to_bus: int, line_id: str, max_value: float, max_contingency: int) -> dict[str, object]:
    return {
        "from_bus": from_bus,
        "to_bus": to_bus,
        "line_id": line_id,
        "max_value": max_value,
        "max_contingency": max_contingency,
    }
