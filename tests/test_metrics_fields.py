from __future__ import annotations

from gridlens.analysis.metrics import (
    GENERATOR_DEVIATION_FIELDS,
    RANKED_COUNT_BASE_FIELDS,
    THERMAL_BOTTLENECK_FIELDS,
    VOLTAGE_EXTREME_FIELDS,
    compute_metrics,
)
from gridlens.analysis.parser_models import ParsedTable


def test_metric_field_sets_are_unique() -> None:
    for fields in (
        GENERATOR_DEVIATION_FIELDS,
        RANKED_COUNT_BASE_FIELDS,
        THERMAL_BOTTLENECK_FIELDS,
        VOLTAGE_EXTREME_FIELDS,
    ):
        assert len(fields) == len(set(fields))


def test_thermal_bottleneck_rows_follow_configured_field_order() -> None:
    branch_metadata = ParsedTable(
        name="branch_metadata",
        source_file="training.raw",
        columns=["from_bus", "to_bus", "line_id", "ratea", "ratec", "raw_branch_type"],
        rows=[
            {
                "from_bus": 101,
                "to_bus": 102,
                "line_id": "1",
                "ratea": 10.0,
                "ratec": 100.0,
                "raw_branch_type": "nontransformer_branch",
            }
        ],
    )
    pflow_mm = ParsedTable(
        name="pflow_mm",
        source_file="pflow_mm.txt",
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
            "min_allowable",
            "max_allowable",
            "min_contingency",
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
                "base_value": 50.0,
                "min_value": -120.0,
                "max_value": 80.0,
                "min_allowable": -100.0,
                "max_allowable": 100.0,
                "min_contingency": 6,
                "max_contingency": 7,
                "extra_column": "not exported",
            }
        ],
    )

    metrics = compute_metrics({"branch_metadata": branch_metadata, "pflow_mm": pflow_mm})
    thermal = metrics["thermal"]
    bottleneck = thermal["top_bottlenecks"][0]

    assert list(bottleneck) == THERMAL_BOTTLENECK_FIELDS
    assert bottleneck["max_utilization_pct"] == 120.0
    assert bottleneck["max_utilization_contingency"] == 6
    assert "extra_column" not in bottleneck
