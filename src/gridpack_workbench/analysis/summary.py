from __future__ import annotations

import csv
import html
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

from gridpack_workbench.analysis.charts import create_success_svg
from gridpack_workbench.analysis.dataset import RunAnalysisDataset, build_run_analysis
from gridpack_workbench.analysis.master import build_branch_master_exports
from gridpack_workbench.analysis.parsers import list_output_files, summarize_success_file


def write_output_inventory(run_dir: str | Path) -> Path:
    run_path = Path(run_dir)
    report_dir = run_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / "output_inventory.csv"

    files = list_output_files(run_path)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file_name", "relative_path", "size_bytes", "suffix"])
        writer.writeheader()
        for item in files:
            writer.writerow(
                {
                    "file_name": item.file_name,
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "suffix": item.suffix,
                }
            )
    return output_path


def generate_decision_support_report(run_dir: str | Path, dataset: RunAnalysisDataset | None = None) -> dict:
    run_path = Path(run_dir).expanduser().resolve()
    dataset = dataset or build_run_analysis(run_path)
    report_dir = dataset.report_dir

    success = summarize_success_file(run_path)
    files = list_output_files(run_path)
    inventory_csv = write_output_inventory(run_path)
    chart_svg = create_success_svg(success, report_dir / "success_summary.svg")
    master_exports = build_branch_master_exports(run_path, dataset)

    thermal = dataset.metrics.get("thermal", {})
    voltage = dataset.metrics.get("voltage", {})
    success_metrics = dataset.metrics.get("success", {})
    summary_json = report_dir / "analysis_summary.json"
    summary = {
        "run_dir": str(run_path),
        "success_file": success.file_name,
        "success_count": success.success_count,
        "failure_count": success.failure_count,
        "unknown_count": success.unknown_count,
        "total_count": success.total_count,
        "note": success.note,
        "output_file_count": len(files),
        "inventory_csv": str(inventory_csv),
        "chart_svg": str(chart_svg),
        "master": master_exports.as_dict(),
        "analysis_manifest": str(dataset.manifest_path),
        "table_dir": str(dataset.table_dir),
        "thermal_facility_count": thermal.get("facility_count", 0) if isinstance(thermal, dict) else 0,
        "mean_worst_utilization_pct": thermal.get("mean_worst_utilization_pct") if isinstance(thermal, dict) else None,
        "gini_worst_utilization": thermal.get("gini_worst_utilization") if isinstance(thermal, dict) else None,
        "low_voltage_violations": voltage.get("low_voltage_violations", 0) if isinstance(voltage, dict) else 0,
        "high_voltage_violations": voltage.get("high_voltage_violations", 0) if isinstance(voltage, dict) else 0,
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    html_report = report_dir / "decision_support_report.html"
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(item.file_name)}</td>"
        f"<td>{html.escape(item.relative_path)}</td>"
        f"<td>{item.size_bytes}</td>"
        f"<td>{html.escape(item.suffix)}</td>"
        "</tr>"
        for item in files
    )
    top_bottlenecks = thermal.get("top_bottlenecks", []) if isinstance(thermal, dict) else []
    voltage_low = voltage.get("worst_low_voltage", []) if isinstance(voltage, dict) else []
    contingency = dataset.metrics.get("contingencies", {})
    worst_contingencies = contingency.get("worst_by_performance_index", []) if isinstance(contingency, dict) else []
    notes = dataset.metrics.get("notes", [])
    html_report.write_text(
        f"""<!doctype html>
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
  <p><strong>Run folder:</strong> {html.escape(str(run_path))}</p>
  <section class="section">
    <h2>Overview</h2>
    <div class="grid">
      <div class="metric">Contingencies<strong>{success_metrics.get("total", success.total_count) if isinstance(success_metrics, dict) else success.total_count}</strong></div>
      <div class="metric">Success Rate<strong>{_format_metric(success_metrics.get("success_rate_pct") if isinstance(success_metrics, dict) else None, "%")}</strong></div>
      <div class="metric">Failed<strong>{success.failure_count}</strong></div>
      <div class="metric">Thermal Facilities<strong>{_format_metric(summary["thermal_facility_count"])}</strong></div>
      <div class="metric">Mean Worst Utilization<strong>{_format_metric(summary["mean_worst_utilization_pct"], "%")}</strong></div>
      <div class="metric">Gini Stress Concentration<strong>{_format_metric(summary["gini_worst_utilization"])}</strong></div>
      <div class="metric">Low Voltage Violations<strong>{summary["low_voltage_violations"]}</strong></div>
      <div class="metric">High Voltage Violations<strong>{summary["high_voltage_violations"]}</strong></div>
    </div>
    <p class="note">{html.escape(success.note)}</p>
    <img src="success_summary.svg" alt="Contingency success summary chart">
  </section>
  <section class="section">
    <h2>Top Thermal Bottlenecks</h2>
    {_html_table(top_bottlenecks, ["row_index", "from_bus", "to_bus", "line_id", "voltage_class", "area", "max_utilization_pct", "worst_headroom_pct", "max_contingency"])}
  </section>
  <section class="section">
    <h2>Worst Low-Voltage Buses</h2>
    {_html_table(voltage_low, ["row_index", "bus_id", "bus_name", "base_kv", "area", "min_value", "min_voltage_margin", "min_contingency"])}
  </section>
  <section class="section">
    <h2>Worst Contingencies By Performance Index</h2>
    {_html_table(worst_contingencies, ["contingency_index", "success", "violation", "isolated_warning", "performance_index_sum", "performance_index_average"])}
  </section>
  <section class="section">
    <h2>Data Provenance</h2>
    <p><strong>Analysis manifest:</strong> {html.escape(str(dataset.manifest_path))}</p>
    <p><strong>Normalized tables:</strong> {html.escape(str(dataset.table_dir))}</p>
    <ul>{''.join(f'<li>{html.escape(str(note))}</li>' for note in notes)}</ul>
  </section>
  <section class="section">
    <h2>Output Files</h2>
    <table>
      <thead><tr><th>File</th><th>Path</th><th>Size bytes</th><th>Type</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
</body>
</html>
""",
        encoding="utf-8",
    )

    summary["summary_json"] = str(summary_json)
    summary["html_report"] = str(html_report)
    legacy_html_report = report_dir / "report.html"
    if legacy_html_report != html_report:
        legacy_html_report.write_text(html_report.read_text(encoding="utf-8"), encoding="utf-8")
    summary["legacy_html_report"] = str(legacy_html_report)
    return summary


def generate_run_report(run_dir: str | Path) -> dict:
    """Compatibility wrapper for the original Analysis tab/report API."""
    return generate_decision_support_report(run_dir)


def export_run_zip(run_dir: str | Path, destination_zip: str | Path | None = None) -> Path:
    run_path = Path(run_dir).expanduser().resolve()
    if destination_zip is None:
        destination_zip = run_path.parent.parent / "exports" / f"{run_path.name}.zip"
    zip_path = Path(destination_zip).expanduser().resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(run_path.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(run_path.parent))
    return zip_path


def copy_report_bundle(run_dir: str | Path, destination_dir: str | Path) -> Path:
    source = Path(run_dir).expanduser().resolve() / "reports"
    destination = Path(destination_dir).expanduser().resolve()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def _format_metric(value: object, suffix: str = "") -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _html_table(rows: list[dict[str, object]], columns: list[str]) -> str:
    if not rows:
        return "<p class=\"note\">No rows available.</p>"
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"
