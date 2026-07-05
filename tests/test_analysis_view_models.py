from __future__ import annotations

from gridpack_workbench.analysis.distributions import DistributionExport
from gridpack_workbench.analysis.parser_models import ParsedTable
from gridpack_workbench.gui.analysis_view_models import (
    DISTRIBUTION_OUTPUT_COLUMNS,
    UtilizationBranchOptions,
    average_n1_utilization_rows,
    control_area_utilization_rows,
    distribution_output_rows,
    filter_performance_rows,
    max_line_utilization_rows,
    max_230kv_line_utilization_rows,
    metric_mapping,
    metric_notes,
    numeric_value,
    render_analysis_overview_html,
    should_select_distribution_variable,
    summarize_voltage_group_utilization,
    top_numeric_rows,
    voltage_group_utilization_rows,
)


def test_filter_performance_rows_by_area_and_voltage_class() -> None:
    rows = [
        {"row_index": 1, "area": "A", "voltage_class": "230-344 kV"},
        {"row_index": 2, "area": "B", "voltage_class": "230-344 kV"},
        {"row_index": 3, "area": "A", "voltage_class": "100-229 kV"},
    ]

    filtered = filter_performance_rows(rows, area="A", voltage_class="230-344 kV")

    assert filtered == [rows[0]]


def test_top_numeric_rows_sorts_with_missing_values() -> None:
    rows = [
        {"name": "missing"},
        {"name": "low", "score": 10},
        {"name": "high", "score": "20"},
    ]

    top = top_numeric_rows(rows, "score", 2, reverse=True, missing_value=0.0)

    assert [row["name"] for row in top] == ["high", "low"]


def test_numeric_value_uses_default_for_invalid_values() -> None:
    assert numeric_value("2.5") == 2.5
    assert numeric_value(None, default=9.0) == 9.0
    assert numeric_value("not-a-number", default=-1.0) == -1.0


def test_distribution_variable_defaults_are_centralized() -> None:
    assert should_select_distribution_variable("area")
    assert should_select_distribution_variable("voltage_class")
    assert should_select_distribution_variable("rate_c")
    assert not should_select_distribution_variable("rate_a")
    assert not should_select_distribution_variable("owner_1_fraction")


def test_distribution_output_rows_match_configured_columns(tmp_path) -> None:
    result = DistributionExport(
        independent_variable="area",
        utilization_metric="max_contingency_utilization_pct",
        table_csv=tmp_path / "area.csv",
        graph_png=tmp_path / "area.png",
        code_path=tmp_path / "distributions.py",
        row_count=10,
        group_count=2,
    )

    rows = distribution_output_rows([result])

    assert list(rows[0]) == DISTRIBUTION_OUTPUT_COLUMNS
    assert rows[0]["variable"] == "area"
    assert rows[0]["table_csv"] == str(tmp_path / "area.csv")
    assert rows[0]["graph_png"] == str(tmp_path / "area.png")
    assert rows[0]["code_path"] == str(tmp_path / "distributions.py")


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
                _branch(301, 302, "1", 69.0, 69.0, 100.0, "Low", "<100 kV"),
                _branch(401, 402, "1", 230.0, 345.0, 50.0, "North / South", "345-499 kV", 1, "North", 2, "South"),
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
            ],
        ),
    }

    area_rows = control_area_utilization_rows(tables)
    branch_rows = max_line_utilization_rows(tables)
    voltage_rows = voltage_group_utilization_rows(tables)
    north_voltage_rows = summarize_voltage_group_utilization(
        [row for row in branch_rows if "North" in row["control_areas"]]
    )
    line_rows = max_230kv_line_utilization_rows(tables)
    all_line_rows = max_line_utilization_rows(tables)

    assert [row["control_area"] for row in area_rows] == ["South", "North"]
    assert area_rows[0]["average_utilization_pct"] == 65.0
    assert area_rows[1]["average_utilization_pct"] == 45.0
    assert all(row["control_area"] != "Low" for row in area_rows)
    assert all(" / " not in row["control_area"] for row in area_rows)
    assert next(row for row in branch_rows if row["from_bus"] == 401)["control_areas"] == ["North", "South"]
    assert [row["voltage_group"] for row in voltage_rows] == ["<100 kV", "100-229 kV", "230-344 kV", "345-499 kV"]
    assert [row["average_utilization_pct"] for row in voltage_rows] == [80.0, 50.0, 90.0, 40.0]
    assert [row["voltage_group"] for row in north_voltage_rows] == ["100-229 kV", "345-499 kV"]
    assert [row["max_utilization_pct"] for row in line_rows] == [40.0, 90.0]
    assert [row["max_contingency"] for row in line_rows] == [6, 4]
    assert [row["voltage_group"] for row in all_line_rows] == ["345-499 kV", "100-229 kV", "<100 kV", "230-344 kV"]


def test_average_utilization_ignores_qflow() -> None:
    tables = {
        "branch_metadata": ParsedTable(
            name="branch_metadata",
            source_file="training.raw",
            columns=[],
            rows=[_branch(101, 102, "1", 230.0, 230.0, 10.0, "North", "230-344 kV", ratec=100.0)],
        ),
        "pflow": ParsedTable(
            name="pflow",
            source_file="pflow.txt",
            columns=[],
            rows=[_flow(101, 102, "1", 60.0)],
        ),
        "qflow": ParsedTable(
            name="qflow",
            source_file="qflow.txt",
            columns=[],
            rows=[_flow(101, 102, "1", 800.0)],
        ),
    }

    rows = average_n1_utilization_rows(tables)

    assert rows[0]["utilization_pct"] == 60.0


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

    assert average_n1_utilization_rows(tables) == []
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

    assert average_n1_utilization_rows(tables) == []
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
    average_rows = average_n1_utilization_rows(
        tables,
        UtilizationBranchOptions(
            include_two_winding_transformers=True,
            include_three_winding_transformers=True,
        ),
    )

    assert [row["raw_branch_type"] for row in two_winding_rows] == ["two_winding_transformer_branch"]
    assert [row["max_utilization_pct"] for row in all_transformer_rows] == [60.0, 90.0]
    assert [row["utilization_pct"] for row in average_rows] == [50.0, 40.0]


def test_metric_helpers_tolerate_unexpected_shapes() -> None:
    metrics = {
        "success": "not-a-dict",
        "notes": "single note",
    }

    assert metric_mapping(metrics, "success") == {}
    assert metric_notes(metrics) == ["single note"]


def test_overview_html_escapes_metrics_paths_and_notes(tmp_path) -> None:
    html = render_analysis_overview_html(
        tmp_path / "run <unsafe>",
        tmp_path / "manifest <unsafe>.json",
        {
            "success": {
                "total": "<total>",
                "success_rate_pct": "99<script>",
                "failure": 1,
            },
            "thermal": {
                "facility_count": 2,
                "mean_worst_utilization_pct": 88.1,
            },
            "voltage": {
                "low_voltage_violations": 3,
                "high_voltage_violations": 4,
            },
            "notes": ["<script>alert('x')</script>"],
        },
        {"master_cleaned_csv": tmp_path / "master <cleaned>.csv"},
    )

    assert "<script>" not in html
    assert "&lt;total&gt;" in html
    assert "99&lt;script&gt;%" in html
    assert "run &lt;unsafe&gt;" in html
    assert "manifest &lt;unsafe&gt;.json" in html
    assert "master &lt;cleaned&gt;.csv" in html


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
