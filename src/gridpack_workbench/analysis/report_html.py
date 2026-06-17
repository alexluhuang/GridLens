from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import html
from pathlib import Path

from gridpack_workbench.analysis.parser_models import OutputFile


THERMAL_COLUMNS = [
    "row_index",
    "from_bus",
    "to_bus",
    "line_id",
    "voltage_class",
    "area",
    "max_utilization_pct",
    "worst_headroom_pct",
    "max_contingency",
]
LOW_VOLTAGE_COLUMNS = [
    "row_index",
    "bus_id",
    "bus_name",
    "base_kv",
    "area",
    "min_value",
    "min_voltage_margin",
    "min_contingency",
]
CONTINGENCY_COLUMNS = [
    "contingency_index",
    "success",
    "violation",
    "isolated_warning",
    "performance_index_sum",
    "performance_index_average",
]


@dataclass(slots=True)
class DecisionSupportReportView:
    """Data needed to render the local decision-support HTML report."""

    run_path: Path
    manifest_path: Path
    table_dir: Path
    summary: dict[str, object]
    success_note: str
    success_total: int
    success_rate_pct: object
    output_files: Sequence[OutputFile]
    top_bottlenecks: Sequence[dict[str, object]]
    voltage_low: Sequence[dict[str, object]]
    worst_contingencies: Sequence[dict[str, object]]
    notes: Sequence[object]


def render_decision_support_report_html(view: DecisionSupportReportView) -> str:
    """Render the report HTML without writing files."""
    output_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(item.file_name)}</td>"
        f"<td>{html.escape(item.relative_path)}</td>"
        f"<td>{item.size_bytes}</td>"
        f"<td>{html.escape(item.suffix)}</td>"
        "</tr>"
        for item in view.output_files
    )
    notes = "".join(f"<li>{html.escape(str(note))}</li>" for note in view.notes)
    thermal_facilities = _format_metric(view.summary["thermal_facility_count"])
    mean_worst_utilization = _format_metric(view.summary["mean_worst_utilization_pct"], "%")
    stress_gini = _format_metric(view.summary["gini_worst_utilization"])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>GridPACK Decision Support Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #172033; line-height: 1.42; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #c8ced8; padding: 8px 10px; text-align: left; }}
    th {{ background: #eef2f6; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .metric {{ border: 1px solid #d8dde7; padding: 12px; background: #f8fafc; }}
    .metric strong {{ display: block; font-size: 24px; margin-top: 4px; }}
    .note {{ color: #485366; }}
    .section {{ margin-top: 30px; }}
  </style>
</head>
<body>
  <h1>GridPACK Decision Support Report</h1>
  <p><strong>Run folder:</strong> {html.escape(str(view.run_path))}</p>
  <section class="section">
    <h2>Overview</h2>
    <div class="grid">
      <div class="metric">Contingencies<strong>{view.success_total}</strong></div>
      <div class="metric">Success Rate<strong>{_format_metric(view.success_rate_pct, "%")}</strong></div>
      <div class="metric">Failed<strong>{view.summary["failure_count"]}</strong></div>
      <div class="metric">Thermal Facilities<strong>{thermal_facilities}</strong></div>
      <div class="metric">Mean Worst Utilization<strong>{mean_worst_utilization}</strong></div>
      <div class="metric">Gini Stress Concentration<strong>{stress_gini}</strong></div>
      <div class="metric">Low Voltage Violations<strong>{view.summary["low_voltage_violations"]}</strong></div>
      <div class="metric">High Voltage Violations<strong>{view.summary["high_voltage_violations"]}</strong></div>
    </div>
    <p class="note">{html.escape(view.success_note)}</p>
    <img src="success_summary.svg" alt="Contingency success summary chart">
  </section>
  <section class="section">
    <h2>Top Thermal Bottlenecks</h2>
    {_html_table(view.top_bottlenecks, THERMAL_COLUMNS)}
  </section>
  <section class="section">
    <h2>Worst Low-Voltage Buses</h2>
    {_html_table(view.voltage_low, LOW_VOLTAGE_COLUMNS)}
  </section>
  <section class="section">
    <h2>Worst Contingencies By Performance Index</h2>
    {_html_table(view.worst_contingencies, CONTINGENCY_COLUMNS)}
  </section>
  <section class="section">
    <h2>Data Provenance</h2>
    <p><strong>Analysis manifest:</strong> {html.escape(str(view.manifest_path))}</p>
    <p><strong>Normalized tables:</strong> {html.escape(str(view.table_dir))}</p>
    <ul>{notes}</ul>
  </section>
  <section class="section">
    <h2>Output Files</h2>
    <table>
      <thead><tr><th>File</th><th>Path</th><th>Size bytes</th><th>Type</th></tr></thead>
      <tbody>{output_rows}</tbody>
    </table>
  </section>
</body>
</html>
"""


def _format_metric(value: object, suffix: str = "") -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _html_table(rows: Sequence[dict[str, object]], columns: Sequence[str]) -> str:
    if not rows:
        return '<p class="note">No rows available.</p>'
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


__all__ = ["DecisionSupportReportView", "render_decision_support_report_html"]
