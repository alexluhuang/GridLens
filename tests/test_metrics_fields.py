from __future__ import annotations

from gridpack_workbench.analysis.metrics import (
    GENERATOR_DEVIATION_FIELDS,
    RANKED_COUNT_BASE_FIELDS,
    THERMAL_BOTTLENECK_FIELDS,
    VOLTAGE_EXTREME_FIELDS,
    compute_metrics,
)
from gridpack_workbench.analysis.parser_models import ParsedTable


def test_metric_field_sets_are_unique() -> None:
    for fields in (
        GENERATOR_DEVIATION_FIELDS,
        RANKED_COUNT_BASE_FIELDS,
        THERMAL_BOTTLENECK_FIELDS,
        VOLTAGE_EXTREME_FIELDS,
    ):
        assert len(fields) == len(set(fields))


def test_thermal_bottleneck_rows_follow_configured_field_order() -> None:
    perf_mm = ParsedTable(
        name="perf_mm",
        source_file="perf_mm.txt",
        columns=[
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "from_bus_name",
            "to_bus_name",
            "voltage_class",
            "area",
            "base_value",
            "min_value",
            "max_value",
            "max_contingency",
        ],
        rows=[
            {
                "row_index": 1,
                "from_bus": 101,
                "to_bus": 102,
                "line_id": "1",
                "from_bus_name": "FROM",
                "to_bus_name": "TO",
                "voltage_class": "230-344 kV",
                "area": "1-2",
                "base_value": 0.25,
                "min_value": 0.04,
                "max_value": 1.44,
                "max_contingency": 7,
                "extra_column": "not exported",
            }
        ],
    )

    metrics = compute_metrics({"perf_mm": perf_mm})
    thermal = metrics["thermal"]
    bottleneck = thermal["top_bottlenecks"][0]

    assert list(bottleneck) == THERMAL_BOTTLENECK_FIELDS
    assert "extra_column" not in bottleneck
