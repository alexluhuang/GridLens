from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
import html
from pathlib import Path
from typing import Protocol

from gridpack_workbench.analysis.enrichment import voltage_class
from gridpack_workbench.analysis.parser_models import ParsedTable
from gridpack_workbench.analysis.utilization import UtilizationBranchOptions, is_utilizable_branch


DEFAULT_DISTRIBUTION_VARIABLES = frozenset(
    {
        "area",
        "voltage_class",
        "from_area",
        "to_area",
        "rate_c",
        "raw_branch_type",
    }
)
DISTRIBUTION_OUTPUT_COLUMNS = ["variable", "table_csv", "graph_png", "code_path"]
THERMAL_TABLE_COLUMNS = [
    "row_index",
    "from_bus",
    "to_bus",
    "line_id",
    "voltage_class",
    "area",
    "base_utilization_pct",
    "max_utilization_pct",
    "max_utilization_contingency",
    "max_contingency",
]
VOLTAGE_TABLE_COLUMNS = [
    "row_index",
    "bus_id",
    "bus_name",
    "base_kv",
    "area",
    "min_value",
    "min_voltage_margin",
    "min_contingency",
]
CONTINGENCY_TABLE_COLUMNS = [
    "contingency_index",
    "success",
    "violation",
    "isolated_warning",
    "performance_index_sum",
    "performance_index_average",
]
VOLTAGE_GROUP_ORDER = {
    "<100 kV": 0,
    "100-229 kV": 1,
    "230-344 kV": 2,
    "345-499 kV": 3,
    "500+ kV": 4,
    "unknown": 99,
}
BRANCH_KEY_COLUMNS = ("from_bus", "to_bus", "line_id")


class DistributionExportLike(Protocol):
    independent_variable: str
    table_csv: Path
    graph_png: Path
    code_path: Path


def should_select_distribution_variable(variable: str) -> bool:
    return variable in DEFAULT_DISTRIBUTION_VARIABLES


def distribution_output_row(result: DistributionExportLike) -> dict[str, object]:
    return {
        "variable": result.independent_variable,
        "table_csv": str(result.table_csv),
        "graph_png": str(result.graph_png),
        "code_path": str(result.code_path),
    }


def distribution_output_rows(results: Iterable[DistributionExportLike]) -> list[dict[str, object]]:
    return [distribution_output_row(result) for result in results]


def control_area_utilization_rows(
    tables: Mapping[str, ParsedTable],
    branch_options: UtilizationBranchOptions | None = None,
) -> list[dict[str, object]]:
    """Average N-1 branch utilization by control area for lines at or above 100 kV."""
    return summarize_control_area_utilization(average_n1_utilization_rows(tables, branch_options))


def average_n1_utilization_rows(
    tables: Mapping[str, ParsedTable],
    branch_options: UtilizationBranchOptions | None = None,
) -> list[dict[str, object]]:
    """Average N-1 branch utilization rows with area and voltage labels attached."""
    duplicate_area_names = _duplicate_area_names(tables.get("area_metadata"))
    rows = []
    for row in _average_n1_utilization_rows(tables, branch_options):
        area_labels = _endpoint_control_area_labels(row, duplicate_area_names)
        group = str(row.get("voltage_class") or voltage_class(_line_voltage_kv(row)) or "unknown")
        enriched = dict(row)
        enriched["control_areas"] = area_labels
        enriched["voltage_group"] = group
        rows.append(enriched)
    return rows


def summarize_control_area_utilization(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Summarize average N-1 branch utilization by actual endpoint control area."""
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if _line_voltage_kv(row) < 100:
            continue
        for area in _row_control_areas(row):
            buckets.setdefault(area, []).append(float(row["utilization_pct"]))

    summaries = _group_average_rows(buckets, "control_area")
    summaries.sort(key=lambda row: numeric_value(row.get("average_utilization_pct")), reverse=True)
    return summaries


def voltage_group_utilization_rows(
    tables: Mapping[str, ParsedTable],
    branch_options: UtilizationBranchOptions | None = None,
) -> list[dict[str, object]]:
    """Average N-1 branch utilization by voltage group."""
    return summarize_voltage_group_utilization(average_n1_utilization_rows(tables, branch_options))


def summarize_voltage_group_utilization(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Summarize average N-1 branch utilization by voltage group."""
    buckets: dict[str, list[float]] = {}
    for row in rows:
        group = str(row.get("voltage_group") or row.get("voltage_class") or voltage_class(_line_voltage_kv(row)) or "unknown")
        buckets.setdefault(group, []).append(float(row["utilization_pct"]))

    summaries = _group_average_rows(buckets, "voltage_group")
    summaries.sort(key=lambda row: (VOLTAGE_GROUP_ORDER.get(str(row["voltage_group"]), 98), str(row["voltage_group"])))
    return summaries


def max_230kv_line_utilization_rows(
    tables: Mapping[str, ParsedTable],
    branch_options: UtilizationBranchOptions | None = None,
) -> list[dict[str, object]]:
    """Maximum observed utilization for 230 kV lines, sorted from lowest to highest."""
    rows = [row for row in max_line_utilization_rows(tables, branch_options) if _is_230kv_line(row)]
    rows.sort(key=lambda item: numeric_value(item.get("max_utilization_pct")))
    return rows


def max_line_utilization_rows(
    tables: Mapping[str, ParsedTable],
    branch_options: UtilizationBranchOptions | None = None,
) -> list[dict[str, object]]:
    """Maximum observed utilization rows for branch lines, sorted from lowest to highest."""
    duplicate_area_names = _duplicate_area_names(tables.get("area_metadata"))
    branches = _table_index(tables.get("branch_metadata"))
    rows: list[dict[str, object]] = []

    for row in _table_rows(tables, "pflow_mm"):
        key = _branch_key(row)
        branch = branches.get(key)
        if not _is_utilizable_branch(branch, branch_options):
            continue
        context = _merge_rows(branch, row)
        utilization = _pflow_mm_max_utilization_pct(context)
        if utilization is None:
            continue
        rows.append(_line_utilization_row(context, utilization, duplicate_area_names, "pflow_mm"))

    rows.sort(key=lambda item: numeric_value(item.get("max_utilization_pct")))
    return rows


def _line_utilization_row(
    context: Mapping[str, object],
    utilization: float,
    duplicate_area_names: set[str],
    utilization_source: str,
) -> dict[str, object]:
    voltage_group = str(context.get("voltage_class") or voltage_class(_line_voltage_kv(context)) or "unknown")
    return {
        "line_label": _line_label(context),
        "from_bus": context.get("from_bus", ""),
        "to_bus": context.get("to_bus", ""),
        "line_id": context.get("line_id", ""),
        "from_bus_name": context.get("from_bus_name", ""),
        "to_bus_name": context.get("to_bus_name", ""),
        "from_base_kv": context.get("from_base_kv", ""),
        "to_base_kv": context.get("to_base_kv", ""),
        "control_area": context.get("control_area") or context.get("area") or "unknown",
        "control_areas": _endpoint_control_area_labels(context, duplicate_area_names),
        "voltage_group": voltage_group,
        "max_contingency": _max_flow_contingency(context),
        "max_utilization_pct": round(utilization, 6),
        "utilization_source": utilization_source,
        "raw_branch_type": context.get("raw_branch_type", ""),
    }


def _average_n1_utilization_rows(
    tables: Mapping[str, ParsedTable],
    branch_options: UtilizationBranchOptions | None = None,
) -> list[dict[str, object]]:
    branches = _table_index(tables.get("branch_metadata"))
    pflow_mm = _table_index(tables.get("pflow_mm"))
    rows: list[dict[str, object]] = []

    for row in _table_rows(tables, "pflow"):
        key = _branch_key(row)
        branch = branches.get(key)
        if not _is_utilizable_branch(branch, branch_options):
            continue
        context = _merge_rows(branch, pflow_mm.get(key, {}), row)
        rating = _line_rating(context)
        real_flow = _finite_float(row.get("average"))
        utilization = _pflow_utilization_pct(real_flow, rating)
        if utilization is None:
            continue
        context["utilization_pct"] = round(utilization, 6)
        rows.append(context)
    return rows


def _group_average_rows(buckets: Mapping[str, list[float]], key_column: str) -> list[dict[str, object]]:
    summaries = []
    for key, values in buckets.items():
        if not values:
            continue
        average = sum(values) / len(values)
        summaries.append(
            {
                key_column: key,
                "line_count": len(values),
                "average_utilization_pct": round(average, 6),
                "min_utilization_pct": round(min(values), 6),
                "max_utilization_pct": round(max(values), 6),
            }
        )
    return summaries


def _duplicate_area_names(table: ParsedTable | None) -> set[str]:
    if not table:
        return set()
    counts: dict[str, int] = {}
    for row in table.rows:
        name = _clean_label(row.get("area_name"))
        if name:
            counts[name] = counts.get(name, 0) + 1
    return {name for name, count in counts.items() if count > 1}


def _endpoint_control_area_labels(row: Mapping[str, object], duplicate_names: set[str]) -> list[str]:
    labels = []
    seen = set()
    for prefix in ("from", "to"):
        label = _endpoint_control_area_label(row, prefix, duplicate_names)
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    if labels:
        return labels
    fallback = _clean_label(row.get("control_area") or row.get("area"))
    return [fallback] if fallback else ["unknown"]


def _row_control_areas(row: Mapping[str, object]) -> list[str]:
    areas = row.get("control_areas")
    if isinstance(areas, str):
        return [_clean_label(areas)] if areas else []
    if isinstance(areas, Iterable):
        labels = [_clean_label(area) for area in areas]
        return [label for label in labels if label]
    fallback = _clean_label(row.get("control_area") or row.get("area"))
    return [fallback] if fallback else ["unknown"]


def _endpoint_control_area_label(
    row: Mapping[str, object],
    prefix: str,
    duplicate_names: set[str],
) -> str:
    area_id = row.get(f"{prefix}_area")
    area_name = _clean_label(row.get(f"{prefix}_area_name"))
    if area_name and area_name in duplicate_names and area_id not in (None, ""):
        return f"{area_name} ({area_id})"
    if area_name:
        return area_name
    return _clean_label(area_id)


def _clean_label(value: object) -> str:
    return " ".join(str(value or "").split())


def _table_rows(tables: Mapping[str, ParsedTable], table_name: str) -> list[dict[str, object]]:
    table = tables.get(table_name)
    return list(table.rows) if table else []


def _table_index(table: ParsedTable | None) -> dict[tuple[object, object, str], dict[str, object]]:
    if not table:
        return {}
    indexed: dict[tuple[object, object, str], dict[str, object]] = {}
    for row in table.rows:
        indexed.setdefault(_branch_key(row), row)
    return indexed


def _branch_key(row: Mapping[str, object]) -> tuple[object, object, str]:
    return (_integer_key(row.get("from_bus")), _integer_key(row.get("to_bus")), str(row.get("line_id") or "").strip())


def _integer_key(value: object) -> object:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return value


def _merge_rows(*rows: Mapping[str, object]) -> dict[str, object]:
    merged: dict[str, object] = {}
    for row in rows:
        for key, value in row.items():
            if value not in (None, ""):
                merged[key] = value
    return merged


def _pflow_utilization_pct(real_flow: float | None, rating: float | None) -> float | None:
    if real_flow is None or rating is None or rating <= 0:
        return None
    return abs(real_flow) / rating * 100


def _max_utilization_pct(row: Mapping[str, object]) -> float | None:
    return _pflow_mm_max_utilization_pct(row)


def _pflow_mm_max_utilization_pct(row: Mapping[str, object]) -> float | None:
    rating = _line_rating(row)
    min_flow = _finite_float(row.get("min_value"))
    max_flow = _finite_float(row.get("max_value"))
    if rating is None or (min_flow is None and max_flow is None):
        return None
    return max(abs(min_flow or 0.0), abs(max_flow or 0.0)) / rating * 100


def _line_rating(row: Mapping[str, object]) -> float | None:
    return _positive_float(row.get("ratec")) or _positive_float(row.get("rate_c"))


def _is_utilizable_branch(
    row: Mapping[str, object] | None,
    branch_options: UtilizationBranchOptions | None = None,
) -> bool:
    return is_utilizable_branch(row, branch_options)


def _max_flow_contingency(row: Mapping[str, object]) -> object:
    min_flow = _finite_float(row.get("min_value"))
    max_flow = _finite_float(row.get("max_value"))
    if min_flow is not None and abs(min_flow) > abs(max_flow or 0.0):
        return row.get("min_contingency", "")
    return row.get("max_contingency", "")


def _line_voltage_kv(row: Mapping[str, object]) -> float:
    values = _voltage_values(row)
    return max(values) if values else 0.0


def _voltage_values(row: Mapping[str, object]) -> list[float]:
    values = []
    for column in ("from_base_kv", "to_base_kv", "base_kv"):
        value = _finite_float(row.get(column))
        if value is not None:
            values.append(value)
    return values


def _is_230kv_line(row: Mapping[str, object]) -> bool:
    values = _voltage_values(row)
    if values:
        return any(abs(value - 230.0) <= 0.5 for value in values)
    return str(row.get("voltage_class") or "") == "230-344 kV"


def _line_label(row: Mapping[str, object]) -> str:
    from_label = str(row.get("from_bus_name") or row.get("from_bus") or "").strip()
    to_label = str(row.get("to_bus_name") or row.get("to_bus") or "").strip()
    line_id = str(row.get("line_id") or "").strip()
    if line_id:
        return f"{from_label} to {to_label} ({line_id})"
    return f"{from_label} to {to_label}"


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_float(value: object) -> float | None:
    parsed = _finite_float(value)
    return parsed if parsed is not None and parsed > 0 else None


def filter_performance_rows(
    rows: Iterable[dict[str, object]],
    area: object = "",
    voltage_class: object = "",
) -> list[dict[str, object]]:
    filtered = list(rows)
    if area:
        filtered = [row for row in filtered if str(row.get("area")) == str(area)]
    if voltage_class:
        filtered = [row for row in filtered if str(row.get("voltage_class")) == str(voltage_class)]
    return filtered


def top_numeric_rows(
    rows: Iterable[dict[str, object]],
    column: str,
    limit: int,
    *,
    reverse: bool,
    missing_value: float,
) -> list[dict[str, object]]:
    ranked = list(rows)
    ranked.sort(key=lambda row: numeric_value(row.get(column), missing_value), reverse=reverse)
    return ranked[:limit]


def numeric_value(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def render_analysis_overview_html(
    run_dir: Path,
    manifest_path: Path,
    metrics: Mapping[str, object],
    master: Mapping[str, object],
) -> str:
    success = metric_mapping(metrics, "success")
    thermal = metric_mapping(metrics, "thermal")
    voltage = metric_mapping(metrics, "voltage")
    notes = metric_notes(metrics)
    master_cleaned = master.get("master_cleaned_csv", "")

    return f"""
            <h2>Decision Support Overview</h2>
            <p><b>Run:</b> {_html_value(run_dir)}</p>
            <p><b>Manifest:</b> {_html_value(manifest_path)}</p>
            <table>
              <tr><th>Metric</th><th>Value</th></tr>
              <tr><td>Contingencies</td><td>{_html_value(success.get('total', 0))}</td></tr>
              <tr><td>Success rate</td><td>{_html_value(success.get('success_rate_pct', 0))}%</td></tr>
              <tr><td>Failures</td><td>{_html_value(success.get('failure', 0))}</td></tr>
              <tr><td>Thermal facilities</td><td>{_html_value(thermal.get('facility_count', 0))}</td></tr>
              <tr><td>Mean worst utilization</td><td>
                {_html_value(thermal.get('mean_worst_utilization_pct', 'n/a'))}%
              </td></tr>
              <tr><td>Stress Gini</td><td>{_html_value(thermal.get('gini_worst_utilization', 'n/a'))}</td></tr>
              <tr><td>Top 20% stress share</td><td>
                {_html_value(thermal.get('top_20_pct_stress_share', 'n/a'))}
              </td></tr>
              <tr><td>Low voltage violations</td><td>
                {_html_value(voltage.get('low_voltage_violations', 0))}
              </td></tr>
              <tr><td>High voltage violations</td><td>
                {_html_value(voltage.get('high_voltage_violations', 0))}
              </td></tr>
            </table>
            <p><b>Master cleaned CSV:</b> {_html_value(master_cleaned)}</p>
            <h3>Assumptions and Data Notes</h3>
            <ul>{''.join(f'<li>{_html_value(note)}</li>' for note in notes)}</ul>
            """


def metric_mapping(metrics: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = metrics.get(key, {})
    return value if isinstance(value, Mapping) else {}


def metric_notes(metrics: Mapping[str, object]) -> list[object]:
    notes = metrics.get("notes", [])
    if isinstance(notes, str):
        return [notes]
    if isinstance(notes, Iterable):
        return list(notes)
    return []


def _html_value(value: object) -> str:
    return html.escape(str(value))


__all__ = [
    "CONTINGENCY_TABLE_COLUMNS",
    "DEFAULT_DISTRIBUTION_VARIABLES",
    "DISTRIBUTION_OUTPUT_COLUMNS",
    "DistributionExportLike",
    "THERMAL_TABLE_COLUMNS",
    "UtilizationBranchOptions",
    "VOLTAGE_TABLE_COLUMNS",
    "average_n1_utilization_rows",
    "control_area_utilization_rows",
    "distribution_output_row",
    "distribution_output_rows",
    "filter_performance_rows",
    "max_230kv_line_utilization_rows",
    "max_line_utilization_rows",
    "metric_mapping",
    "metric_notes",
    "numeric_value",
    "render_analysis_overview_html",
    "should_select_distribution_variable",
    "summarize_control_area_utilization",
    "summarize_voltage_group_utilization",
    "top_numeric_rows",
    "voltage_group_utilization_rows",
]
