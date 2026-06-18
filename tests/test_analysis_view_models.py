from __future__ import annotations

from gridpack_workbench.analysis.distributions import DistributionExport
from gridpack_workbench.gui.analysis_view_models import (
    DISTRIBUTION_OUTPUT_COLUMNS,
    distribution_output_rows,
    filter_performance_rows,
    metric_mapping,
    metric_notes,
    numeric_value,
    render_analysis_overview_html,
    should_select_distribution_variable,
    top_numeric_rows,
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
