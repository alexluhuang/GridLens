from __future__ import annotations

from collections.abc import Iterable, Mapping
import html
from pathlib import Path
from typing import Protocol


DEFAULT_DISTRIBUTION_VARIABLES = frozenset(
    {
        "area",
        "voltage_class",
        "from_area",
        "to_area",
        "rate_a",
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
    "VOLTAGE_TABLE_COLUMNS",
    "distribution_output_row",
    "distribution_output_rows",
    "filter_performance_rows",
    "metric_mapping",
    "metric_notes",
    "numeric_value",
    "render_analysis_overview_html",
    "should_select_distribution_variable",
    "top_numeric_rows",
]
