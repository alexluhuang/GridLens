from __future__ import annotations

from typing import TypedDict


class GridpackTableSchema(TypedDict):
    """Schema for one whitespace-delimited GridPACK output table."""

    file: str
    columns: list[str]
    ints: set[str]
    strings: set[str]


TABLE_SCHEMAS: dict[str, GridpackTableSchema] = {
    "vmag": {
        "file": "vmag.txt",
        "columns": ["row_index", "bus_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": set(),
    },
    "vang": {
        "file": "vang.txt",
        "columns": ["row_index", "bus_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": set(),
    },
    "vmag_mm": {
        "file": "vmag_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": set(),
    },
    "vang_mm": {
        "file": "vang_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": set(),
    },
    "pgen": {
        "file": "pgen.txt",
        "columns": ["row_index", "bus_id", "generator_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": {"generator_id"},
    },
    "qgen": {
        "file": "qgen.txt",
        "columns": ["row_index", "bus_id", "generator_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "bus_id"},
        "strings": {"generator_id"},
    },
    "pgen_mm": {
        "file": "pgen_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "generator_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": {"generator_id"},
    },
    "qgen_mm": {
        "file": "qgen_mm.txt",
        "columns": [
            "row_index",
            "bus_id",
            "generator_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "bus_id", "min_contingency", "max_contingency"},
        "strings": {"generator_id"},
    },
    "pflow": {
        "file": "pflow.txt",
        "columns": ["row_index", "from_bus", "to_bus", "line_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "from_bus", "to_bus"},
        "strings": {"line_id"},
    },
    "qflow": {
        "file": "qflow.txt",
        "columns": ["row_index", "from_bus", "to_bus", "line_id", "average", "rms_average", "rms_base"],
        "ints": {"row_index", "from_bus", "to_bus"},
        "strings": {"line_id"},
    },
    "pflow_mm": {
        "file": "pflow_mm.txt",
        "columns": [
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_allowable",
            "max_allowable",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "from_bus", "to_bus", "min_contingency", "max_contingency"},
        "strings": {"line_id"},
    },
    "qflow_mm": {
        "file": "qflow_mm.txt",
        "columns": [
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_allowable",
            "max_allowable",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "from_bus", "to_bus", "min_contingency", "max_contingency"},
        "strings": {"line_id"},
    },
    "perf_mm": {
        "file": "perf_mm.txt",
        "columns": [
            "row_index",
            "from_bus",
            "to_bus",
            "line_id",
            "base_value",
            "min_value",
            "max_value",
            "min_deviation",
            "max_deviation",
            "min_contingency",
            "max_contingency",
        ],
        "ints": {"row_index", "from_bus", "to_bus", "min_contingency", "max_contingency"},
        "strings": {"line_id"},
    },
    "perf_sum": {
        "file": "perf_sum.txt",
        "columns": ["contingency_index", "performance_index_sum", "performance_index_average"],
        "ints": {"contingency_index"},
        "strings": set(),
    },
    "line_flt_cnt": {
        "file": "line_flt_cnt.txt",
        "columns": ["row_index", "from_bus", "to_bus", "line_id", "fault_count"],
        "ints": {"row_index", "from_bus", "to_bus", "fault_count"},
        "strings": {"line_id"},
    },
    "pq_change_cnt": {
        "file": "pq_change_cnt.txt",
        "columns": ["row_index", "bus_id", "pq_change_count"],
        "ints": {"row_index", "bus_id", "pq_change_count"},
        "strings": set(),
    },
}


__all__ = ["GridpackTableSchema", "TABLE_SCHEMAS"]
