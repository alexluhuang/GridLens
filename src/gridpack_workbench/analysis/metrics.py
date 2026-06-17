from __future__ import annotations

from collections.abc import Iterable
import math
from statistics import mean, median

from gridpack_workbench.analysis.parser_models import ParsedTable
from gridpack_workbench.analysis.table_helpers import append_missing_columns, as_float, pct, take_fields


__all__ = ["compute_metrics", "gini", "top_share"]


def compute_metrics(tables: dict[str, ParsedTable]) -> dict[str, object]:
    """Compute decision-support metrics from parsed GridPACK output tables."""
    _add_thermal_utilization_columns(tables.get("perf_mm"))
    _add_voltage_margin_columns(tables.get("vmag_mm"), tables.get("input_settings"))
    _add_generator_deviation_columns(tables.get("pgen_mm"))
    _add_generator_deviation_columns(tables.get("qgen_mm"))

    return {
        "success": _success_metrics(tables.get("success")),
        "thermal": _thermal_metrics(tables.get("perf_mm"), tables.get("perf_sum")),
        "voltage": _voltage_metrics(tables.get("vmag_mm"), tables.get("input_settings")),
        "contingencies": _contingency_metrics(tables.get("success"), tables.get("perf_sum")),
        "line_faults": _ranked_count_metrics(tables.get("line_flt_cnt"), "fault_count"),
        "pq_conversions": _ranked_count_metrics(tables.get("pq_change_cnt"), "pq_change_count"),
        "generation": {
            "pgen": _generator_metrics(tables.get("pgen_mm")),
            "qgen": _generator_metrics(tables.get("qgen_mm")),
        },
        "notes": [
            "Thermal utilization is computed as sqrt(performance_index) * 100 from perf_mm.txt.",
            (
                "Because GridPACK perf_mm contains min/max line performance rather than full "
                "per-contingency distributions, concentration metrics use worst-contingency "
                "utilization as a proxy."
            ),
            "Voltage-class and area summaries require bus metadata parsed from the run RAW file.",
        ],
    }


def gini(values: Iterable[float]) -> float:
    """Return the Gini coefficient for non-negative values."""
    ordered = sorted(value for value in values if value >= 0)
    if not ordered:
        return 0.0
    total = sum(ordered)
    if total == 0:
        return 0.0
    n = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (n * total) - (n + 1) / n


def top_share(values: Iterable[float], fraction: float) -> float:
    """Return the share of total value held by the largest fraction of rows."""
    ordered = sorted((value for value in values if value >= 0), reverse=True)
    total = sum(ordered)
    if not ordered or total == 0:
        return 0.0
    count = max(1, math.ceil(len(ordered) * fraction))
    return sum(ordered[:count]) / total


def _success_metrics(table: ParsedTable | None) -> dict[str, object]:
    if not table or not table.rows:
        return {"total": 0, "success": 0, "failure": 0, "unknown": 0, "violation_counts": {}, "isolated_warnings": 0}
    total = len(table.rows)
    success = sum(1 for row in table.rows if row.get("success") is True)
    failure = sum(1 for row in table.rows if row.get("success") is False)
    violation_counts: dict[str, int] = {}
    isolated = 0
    for row in table.rows:
        violation = str(row.get("violation", "none") or "none")
        violation_counts[violation] = violation_counts.get(violation, 0) + 1
        if row.get("isolated_warning") is True:
            isolated += 1
    return {
        "total": total,
        "success": success,
        "failure": failure,
        "unknown": max(total - success - failure, 0),
        "success_rate_pct": pct(success, total),
        "failure_rate_pct": pct(failure, total),
        "violation_counts": violation_counts,
        "isolated_warnings": isolated,
    }


def _thermal_metrics(perf_mm: ParsedTable | None, perf_sum: ParsedTable | None) -> dict[str, object]:
    if not perf_mm or not perf_mm.rows:
        return {"facility_count": 0, "top_bottlenecks": [], "note": "perf_mm.txt was not available."}

    values = [as_float(row.get("max_utilization_pct")) for row in perf_mm.rows]
    values = [value for value in values if value is not None]
    sorted_rows = sorted(
        perf_mm.rows,
        key=lambda row: (as_float(row.get("max_utilization_pct")) or -math.inf),
        reverse=True,
    )
    top_bottlenecks = [
        take_fields(
            row,
            [
                "row_index",
                "from_bus",
                "to_bus",
                "line_id",
                "from_bus_name",
                "to_bus_name",
                "voltage_class",
                "area",
                "base_utilization_pct",
                "max_utilization_pct",
                "worst_headroom_pct",
                "max_contingency",
            ],
        )
        for row in sorted_rows[:25]
    ]
    perf_summary = _perf_sum_metrics(perf_sum)
    return {
        "facility_count": len(values),
        "mean_worst_utilization_pct": round(mean(values), 4) if values else None,
        "median_worst_utilization_pct": round(median(values), 4) if values else None,
        "max_worst_utilization_pct": round(max(values), 4) if values else None,
        "facilities_over_80_pct": sum(1 for value in values if value > 80),
        "facilities_over_100_pct": sum(1 for value in values if value > 100),
        "gini_worst_utilization": round(gini(values), 6) if values else None,
        "top_20_pct_stress_share": round(top_share(values, 0.20), 6) if values else None,
        "top_bottlenecks": top_bottlenecks,
        "by_voltage_class": _group_summary(perf_mm.rows, "voltage_class", "max_utilization_pct"),
        "by_area": _group_summary(perf_mm.rows, "area", "max_utilization_pct"),
        "performance_index_by_contingency": perf_summary,
    }


def _perf_sum_metrics(table: ParsedTable | None) -> dict[str, object]:
    if not table or not table.rows:
        return {"row_count": 0}
    sorted_rows = sorted(
        table.rows,
        key=lambda row: as_float(row.get("performance_index_sum")) or -math.inf,
        reverse=True,
    )
    base_rows = [row for row in table.rows if row.get("contingency_index") == 0]
    return {
        "row_count": len(table.rows),
        "base_case": take_fields(base_rows[0], table.columns) if base_rows else {},
        "worst_contingencies": [take_fields(row, table.columns) for row in sorted_rows[:10]],
    }


def _voltage_metrics(vmag_mm: ParsedTable | None, input_settings: ParsedTable | None) -> dict[str, object]:
    if not vmag_mm or not vmag_mm.rows:
        return {"bus_count": 0, "low_voltage_violations": 0, "high_voltage_violations": 0}
    min_voltage, max_voltage = _voltage_thresholds(input_settings)
    low_rows = [row for row in vmag_mm.rows if (as_float(row.get("min_value")) or math.inf) < min_voltage]
    high_rows = [row for row in vmag_mm.rows if (as_float(row.get("max_value")) or -math.inf) > max_voltage]
    low_sorted = sorted(vmag_mm.rows, key=lambda row: as_float(row.get("min_value")) or math.inf)
    high_sorted = sorted(vmag_mm.rows, key=lambda row: as_float(row.get("max_value")) or -math.inf, reverse=True)
    fields = [
        "row_index",
        "bus_id",
        "bus_name",
        "base_kv",
        "area",
        "voltage_class",
        "base_value",
        "min_value",
        "max_value",
        "min_voltage_margin",
        "max_voltage_margin",
        "min_contingency",
        "max_contingency",
    ]
    return {
        "bus_count": len(vmag_mm.rows),
        "min_voltage_threshold": min_voltage,
        "max_voltage_threshold": max_voltage,
        "low_voltage_violations": len(low_rows),
        "high_voltage_violations": len(high_rows),
        "worst_low_voltage": [take_fields(row, fields) for row in low_sorted[:10]],
        "worst_high_voltage": [take_fields(row, fields) for row in high_sorted[:10]],
        "by_voltage_class": _group_summary(vmag_mm.rows, "voltage_class", "min_value", minimum=True),
        "by_area": _group_summary(vmag_mm.rows, "area", "min_value", minimum=True),
    }


def _contingency_metrics(success: ParsedTable | None, perf_sum: ParsedTable | None) -> dict[str, object]:
    by_index = {int(row["contingency_index"]): row for row in success.rows} if success else {}
    perf_rows = perf_sum.rows if perf_sum else []
    merged = []
    for row in perf_rows:
        idx = int(row.get("contingency_index", -1))
        item = {
            "contingency_index": idx,
            "performance_index_sum": row.get("performance_index_sum"),
            "performance_index_average": row.get("performance_index_average"),
        }
        if idx in by_index:
            item.update(
                {
                    "success": by_index[idx].get("success"),
                    "violation": by_index[idx].get("violation"),
                    "isolated_warning": by_index[idx].get("isolated_warning"),
                }
            )
        merged.append(item)
    merged.sort(key=lambda row: as_float(row.get("performance_index_sum")) or -math.inf, reverse=True)
    return {"contingency_count": len(by_index) or len(perf_rows), "worst_by_performance_index": merged[:20]}


def _ranked_count_metrics(table: ParsedTable | None, count_column: str) -> dict[str, object]:
    if not table or not table.rows:
        return {"row_count": 0, "nonzero_count": 0, "top": []}
    rows = sorted(table.rows, key=lambda row: int(row.get(count_column, 0) or 0), reverse=True)
    nonzero = [row for row in rows if int(row.get(count_column, 0) or 0) > 0]
    return {
        "row_count": len(table.rows),
        "nonzero_count": len(nonzero),
        "top": [
            take_fields(
                row,
                [
                    "row_index",
                    "bus_id",
                    "from_bus",
                    "to_bus",
                    "line_id",
                    "bus_name",
                    "from_bus_name",
                    "to_bus_name",
                    "area",
                    "voltage_class",
                    count_column,
                ],
            )
            for row in rows[:20]
        ],
    }


def _generator_metrics(table: ParsedTable | None) -> dict[str, object]:
    if not table or not table.rows:
        return {"row_count": 0, "top_deviations": []}
    rows = sorted(table.rows, key=lambda row: as_float(row.get("max_abs_deviation")) or -math.inf, reverse=True)
    return {
        "row_count": len(table.rows),
        "top_deviations": [
            take_fields(
                row,
                [
                    "row_index",
                    "bus_id",
                    "bus_name",
                    "generator_id",
                    "area",
                    "voltage_class",
                    "base_value",
                    "min_value",
                    "max_value",
                    "max_abs_deviation",
                    "min_contingency",
                    "max_contingency",
                ],
            )
            for row in rows[:20]
        ],
    }


def _add_thermal_utilization_columns(table: ParsedTable | None) -> None:
    if not table:
        return
    for row in table.rows:
        base = as_float(row.get("base_value")) or 0.0
        min_value = as_float(row.get("min_value")) or 0.0
        max_value = as_float(row.get("max_value")) or 0.0
        row["base_utilization_pct"] = round(math.sqrt(max(base, 0.0)) * 100, 6)
        row["min_utilization_pct"] = round(math.sqrt(max(min_value, 0.0)) * 100, 6)
        row["max_utilization_pct"] = round(math.sqrt(max(max_value, 0.0)) * 100, 6)
        row["worst_headroom_pct"] = round(100 - float(row["max_utilization_pct"]), 6)
    append_missing_columns(
        table,
        ["base_utilization_pct", "min_utilization_pct", "max_utilization_pct", "worst_headroom_pct"],
    )


def _add_voltage_margin_columns(table: ParsedTable | None, input_settings: ParsedTable | None) -> None:
    if not table:
        return
    min_voltage, max_voltage = _voltage_thresholds(input_settings)
    for row in table.rows:
        row["min_voltage_margin"] = round((as_float(row.get("min_value")) or 0.0) - min_voltage, 8)
        row["max_voltage_margin"] = round(max_voltage - (as_float(row.get("max_value")) or 0.0), 8)
    append_missing_columns(table, ["min_voltage_margin", "max_voltage_margin"])


def _add_generator_deviation_columns(table: ParsedTable | None) -> None:
    if not table:
        return
    for row in table.rows:
        min_dev = abs(as_float(row.get("min_deviation")) or 0.0)
        max_dev = abs(as_float(row.get("max_deviation")) or 0.0)
        row["max_abs_deviation"] = round(max(min_dev, max_dev), 8)
    append_missing_columns(table, ["max_abs_deviation"])


def _voltage_thresholds(input_settings: ParsedTable | None) -> tuple[float, float]:
    if input_settings and input_settings.rows:
        row = input_settings.rows[0]
        min_voltage = as_float(row.get("min_voltage"))
        max_voltage = as_float(row.get("max_voltage"))
        return min_voltage if min_voltage is not None else 0.9, max_voltage if max_voltage is not None else 1.1
    return 0.9, 1.1


def _group_summary(
    rows: Iterable[dict[str, object]],
    group_column: str,
    value_column: str,
    minimum: bool = False,
) -> list[dict[str, object]]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        key = str(row.get(group_column) or "unknown")
        value = as_float(row.get(value_column))
        if value is None:
            continue
        buckets.setdefault(key, []).append(value)
    summaries = []
    for key, values in buckets.items():
        values_sorted = sorted(values)
        summaries.append(
            {
                group_column: key,
                "count": len(values),
                "mean": round(mean(values), 6),
                "median": round(median(values), 6),
                "min": round(values_sorted[0], 6),
                "max": round(values_sorted[-1], 6),
            }
        )
    summaries.sort(key=lambda item: item["min" if minimum else "max"], reverse=not minimum)
    return summaries
