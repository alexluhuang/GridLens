from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Iterable

from gridpack_workbench.analysis.parsers import PARSER_VERSION, ParsedTable, parse_all_output_tables


ANALYSIS_DATASET_VERSION = "2026.06.13"


@dataclass(slots=True)
class RunAnalysisDataset:
    run_dir: Path
    report_dir: Path
    table_dir: Path
    manifest_path: Path
    tables: dict[str, ParsedTable]
    metrics: dict[str, object]
    table_files: dict[str, dict[str, str]] = field(default_factory=dict)
    generated_at: str = ""

    def manifest(self) -> dict[str, object]:
        return {
            "dataset_version": ANALYSIS_DATASET_VERSION,
            "parser_version": PARSER_VERSION,
            "generated_at": self.generated_at,
            "run_dir": str(self.run_dir),
            "report_dir": str(self.report_dir),
            "table_dir": str(self.table_dir),
            "metrics": self.metrics,
            "tables": {
                name: {
                    **table.schema_dict(),
                    "csv_path": self.table_files.get(name, {}).get("csv", ""),
                    "json_path": self.table_files.get(name, {}).get("json", ""),
                }
                for name, table in self.tables.items()
            },
        }


def build_run_analysis(run_dir: str | Path) -> RunAnalysisDataset:
    run_path = Path(run_dir).expanduser().resolve()
    report_dir = run_path / "reports"
    table_dir = report_dir / "tables"
    report_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)

    tables = parse_all_output_tables(run_path)
    _enrich_with_bus_metadata(tables)
    metrics = compute_metrics(tables)
    table_files = _write_tables(table_dir, tables)

    dataset = RunAnalysisDataset(
        run_dir=run_path,
        report_dir=report_dir,
        table_dir=table_dir,
        manifest_path=report_dir / "analysis_manifest.json",
        tables=tables,
        metrics=metrics,
        table_files=table_files,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    dataset.manifest_path.write_text(json.dumps(dataset.manifest(), indent=2), encoding="utf-8")
    return dataset


def compute_metrics(tables: dict[str, ParsedTable]) -> dict[str, object]:
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
            "Because GridPACK perf_mm contains min/max line performance rather than full per-contingency distributions, concentration metrics use worst-contingency utilization as a proxy.",
            "Voltage-class and area summaries require bus metadata parsed from the run RAW file.",
        ],
    }


def _write_tables(table_dir: Path, tables: dict[str, ParsedTable]) -> dict[str, dict[str, str]]:
    written: dict[str, dict[str, str]] = {}
    for name, table in tables.items():
        csv_path = table_dir / f"{name}.csv"
        json_path = table_dir / f"{name}.json"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=table.columns, extrasaction="ignore")
            writer.writeheader()
            for row in table.rows:
                writer.writerow({column: _cell_value(row.get(column)) for column in table.columns})
        json_path.write_text(json.dumps(table.rows, indent=2), encoding="utf-8")
        written[name] = {"csv": str(csv_path), "json": str(json_path)}
    return written


def _enrich_with_bus_metadata(tables: dict[str, ParsedTable]) -> None:
    metadata = tables.get("bus_metadata")
    if not metadata or not metadata.rows:
        return
    buses = {int(row["bus_id"]): row for row in metadata.rows if "bus_id" in row}

    for table_name in ("vmag", "vang", "vmag_mm", "vang_mm", "pq_change_cnt", "pgen", "qgen", "pgen_mm", "qgen_mm"):
        table = tables.get(table_name)
        if not table:
            continue
        for row in table.rows:
            bus = buses.get(int(row.get("bus_id", -1)))
            if bus:
                row.update(
                    {
                        "bus_name": bus.get("bus_name", ""),
                        "base_kv": bus.get("base_kv"),
                        "area": bus.get("area"),
                        "zone": bus.get("zone"),
                        "voltage_class": voltage_class(bus.get("base_kv")),
                    }
                )
        _append_columns(table, ["bus_name", "base_kv", "area", "zone", "voltage_class"])

    for table_name in ("pflow", "qflow", "pflow_mm", "qflow_mm", "perf_mm", "line_flt_cnt"):
        table = tables.get(table_name)
        if not table:
            continue
        for row in table.rows:
            from_bus = buses.get(int(row.get("from_bus", -1)))
            to_bus = buses.get(int(row.get("to_bus", -1)))
            from_kv = from_bus.get("base_kv") if from_bus else None
            to_kv = to_bus.get("base_kv") if to_bus else None
            from_area = from_bus.get("area") if from_bus else None
            to_area = to_bus.get("area") if to_bus else None
            row.update(
                {
                    "from_bus_name": from_bus.get("bus_name", "") if from_bus else "",
                    "to_bus_name": to_bus.get("bus_name", "") if to_bus else "",
                    "from_base_kv": from_kv,
                    "to_base_kv": to_kv,
                    "from_area": from_area,
                    "to_area": to_area,
                    "area": _area_label(from_area, to_area),
                    "voltage_class": voltage_class(max(_float_or_zero(from_kv), _float_or_zero(to_kv)) or None),
                }
            )
        _append_columns(
            table,
            [
                "from_bus_name",
                "to_bus_name",
                "from_base_kv",
                "to_base_kv",
                "from_area",
                "to_area",
                "area",
                "voltage_class",
            ],
        )


def voltage_class(base_kv: object) -> str:
    if base_kv is None or base_kv == "":
        return "unknown"
    kv = float(base_kv)
    if kv < 100:
        return "<100 kV"
    if kv < 230:
        return "100-229 kV"
    if kv < 345:
        return "230-344 kV"
    if kv < 500:
        return "345-499 kV"
    return "500+ kV"


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
        "success_rate_pct": _pct(success, total),
        "failure_rate_pct": _pct(failure, total),
        "violation_counts": violation_counts,
        "isolated_warnings": isolated,
    }


def _thermal_metrics(perf_mm: ParsedTable | None, perf_sum: ParsedTable | None) -> dict[str, object]:
    if not perf_mm or not perf_mm.rows:
        return {"facility_count": 0, "top_bottlenecks": [], "note": "perf_mm.txt was not available."}

    values = [_as_float(row.get("max_utilization_pct")) for row in perf_mm.rows]
    values = [value for value in values if value is not None]
    sorted_rows = sorted(
        perf_mm.rows,
        key=lambda row: (_as_float(row.get("max_utilization_pct")) or -math.inf),
        reverse=True,
    )
    top_bottlenecks = [
        _take_fields(
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
    sorted_rows = sorted(table.rows, key=lambda row: _as_float(row.get("performance_index_sum")) or -math.inf, reverse=True)
    base_rows = [row for row in table.rows if row.get("contingency_index") == 0]
    return {
        "row_count": len(table.rows),
        "base_case": _take_fields(base_rows[0], table.columns) if base_rows else {},
        "worst_contingencies": [_take_fields(row, table.columns) for row in sorted_rows[:10]],
    }


def _voltage_metrics(vmag_mm: ParsedTable | None, input_settings: ParsedTable | None) -> dict[str, object]:
    if not vmag_mm or not vmag_mm.rows:
        return {"bus_count": 0, "low_voltage_violations": 0, "high_voltage_violations": 0}
    min_voltage, max_voltage = _voltage_thresholds(input_settings)
    low_rows = [row for row in vmag_mm.rows if (_as_float(row.get("min_value")) or math.inf) < min_voltage]
    high_rows = [row for row in vmag_mm.rows if (_as_float(row.get("max_value")) or -math.inf) > max_voltage]
    low_sorted = sorted(vmag_mm.rows, key=lambda row: _as_float(row.get("min_value")) or math.inf)
    high_sorted = sorted(vmag_mm.rows, key=lambda row: _as_float(row.get("max_value")) or -math.inf, reverse=True)
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
        "worst_low_voltage": [_take_fields(row, fields) for row in low_sorted[:10]],
        "worst_high_voltage": [_take_fields(row, fields) for row in high_sorted[:10]],
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
    merged.sort(key=lambda row: _as_float(row.get("performance_index_sum")) or -math.inf, reverse=True)
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
            _take_fields(
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
    rows = sorted(table.rows, key=lambda row: _as_float(row.get("max_abs_deviation")) or -math.inf, reverse=True)
    return {
        "row_count": len(table.rows),
        "top_deviations": [
            _take_fields(
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
        base = _as_float(row.get("base_value")) or 0.0
        min_value = _as_float(row.get("min_value")) or 0.0
        max_value = _as_float(row.get("max_value")) or 0.0
        row["base_utilization_pct"] = round(math.sqrt(max(base, 0.0)) * 100, 6)
        row["min_utilization_pct"] = round(math.sqrt(max(min_value, 0.0)) * 100, 6)
        row["max_utilization_pct"] = round(math.sqrt(max(max_value, 0.0)) * 100, 6)
        row["worst_headroom_pct"] = round(100 - float(row["max_utilization_pct"]), 6)
    _append_columns(table, ["base_utilization_pct", "min_utilization_pct", "max_utilization_pct", "worst_headroom_pct"])


def _add_voltage_margin_columns(table: ParsedTable | None, input_settings: ParsedTable | None) -> None:
    if not table:
        return
    min_voltage, max_voltage = _voltage_thresholds(input_settings)
    for row in table.rows:
        row["min_voltage_margin"] = round((_as_float(row.get("min_value")) or 0.0) - min_voltage, 8)
        row["max_voltage_margin"] = round(max_voltage - (_as_float(row.get("max_value")) or 0.0), 8)
    _append_columns(table, ["min_voltage_margin", "max_voltage_margin"])


def _add_generator_deviation_columns(table: ParsedTable | None) -> None:
    if not table:
        return
    for row in table.rows:
        min_dev = abs(_as_float(row.get("min_deviation")) or 0.0)
        max_dev = abs(_as_float(row.get("max_deviation")) or 0.0)
        row["max_abs_deviation"] = round(max(min_dev, max_dev), 8)
    _append_columns(table, ["max_abs_deviation"])


def _voltage_thresholds(input_settings: ParsedTable | None) -> tuple[float, float]:
    if input_settings and input_settings.rows:
        row = input_settings.rows[0]
        min_voltage = _as_float(row.get("min_voltage"))
        max_voltage = _as_float(row.get("max_voltage"))
        return min_voltage if min_voltage is not None else 0.9, max_voltage if max_voltage is not None else 1.1
    return 0.9, 1.1


def _group_summary(rows: Iterable[dict[str, object]], group_column: str, value_column: str, minimum: bool = False) -> list[dict[str, object]]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        key = str(row.get(group_column) or "unknown")
        value = _as_float(row.get(value_column))
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


def gini(values: Iterable[float]) -> float:
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
    ordered = sorted((value for value in values if value >= 0), reverse=True)
    total = sum(ordered)
    if not ordered or total == 0:
        return 0.0
    count = max(1, math.ceil(len(ordered) * fraction))
    return sum(ordered[:count]) / total


def _append_columns(table: ParsedTable, columns: list[str]) -> None:
    for column in columns:
        if column not in table.columns:
            table.columns.append(column)


def _take_fields(row: dict[str, object], fields: list[str]) -> dict[str, object]:
    return {field: row.get(field, "") for field in fields if field in row}


def _area_label(from_area: object, to_area: object) -> str:
    if from_area in (None, "") and to_area in (None, ""):
        return "unknown"
    if from_area == to_area:
        return str(from_area)
    return f"{from_area}-{to_area}"


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: object) -> float:
    parsed = _as_float(value)
    return parsed if parsed is not None else 0.0


def _pct(value: int, total: int) -> float:
    if not total:
        return 0.0
    return round(value / total * 100, 4)


def _cell_value(value: object) -> object:
    if value is None:
        return ""
    return value
